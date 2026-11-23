"""
Loja de DEMONSTRAÇÃO (Maratona 2, M2 / Plano Mestre D1 e D3).

"Recife Seminovos Demo": loja claramente fictícia, marcada com "demo": true na configuração
(sem migração). No ar, só com o canal simulador e envios "só simulando" (envio_real desligado):
nada pode sair para ninguém de verdade.

- criar_loja_demo(): cria (ou recria) a loja demo com 18 carros com foto ilustrativa gerada aqui
  (Pillow), políticas na base, equipe fictícia SEM contato e 30 dias de histórico plausível
  (leads, conversas, chamados, visitas, vendas com pós-venda, remarketing, custo).
- reiniciar_demo(loja_id): apaga e recria SÓ a loja marcada como demo; recusa qualquer outra.
  O histórico sai sempre igual (sorteio com semente fixa); só as datas acompanham o dia de hoje.
Nada com nome, telefone ou placa reais.
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta

from app.chaves import exigir_loja
from app.relogio import agora_utc, para_banco
from banco import conectar

NOME_DEMO = "Recife Seminovos Demo"
SEMENTE = 2026
DIAS_DE_HISTORICO = 30

CONFIG_DEMO = {
    "demo": True,
    "nome_agente": "Léo",
    "cidade": "Recife",
    "endereco": "Rua da Demonstração, 100, Boa Viagem (endereço fictício)",
    "aceita_troca": "sim",
    "tom": "simples, cordial e direto",
    "atendimento": {"horario_semana": {"0": "08:00-18:00", "1": "08:00-18:00", "2": "08:00-18:00",
                                       "3": "08:00-18:00", "4": "08:00-18:00", "5": "08:00-13:00"}},
    "modulos": {"fotos": True, "agendamento": True, "remarketing": True, "pos_venda": True},
    "envio_real": {"remarketing": False, "pos_venda": False, "reativacao": False},
    "remarketing": {"limite_mensal": 200},
}

# (marca, modelo, ano, km, cor, câmbio, preço) — preços plausíveis para Recife.
ESTOQUE_DEMO = [
    ("Toyota", "Corolla", 2021, 38000, "Prata", "Automático", 129900.0),
    ("Honda", "Civic", 2020, 45000, "Preto", "Automático", 118900.0),
    ("Chevrolet", "Onix", 2022, 28000, "Branco", "Manual", 72900.0),
    ("Chevrolet", "Onix Plus", 2021, 41000, "Cinza", "Automático", 79900.0),
    ("Hyundai", "HB20", 2021, 36000, "Vermelho", "Manual", 66900.0),
    ("Hyundai", "HB20S", 2020, 52000, "Prata", "Automático", 71900.0),
    ("Volkswagen", "Gol", 2019, 61000, "Branco", "Manual", 48900.0),
    ("Volkswagen", "Polo", 2021, 33000, "Azul", "Automático", 84900.0),
    ("Volkswagen", "T-Cross", 2022, 27000, "Branco", "Automático", 119900.0),
    ("Fiat", "Argo", 2021, 39000, "Prata", "Manual", 64900.0),
    ("Fiat", "Strada", 2022, 31000, "Branco", "Manual", 98900.0),
    ("Fiat", "Toro", 2021, 48000, "Cinza", "Automático", 132900.0),
    ("Jeep", "Renegade", 2020, 51000, "Verde", "Automático", 94900.0),
    ("Jeep", "Compass", 2021, 44000, "Preto", "Automático", 149900.0),
    ("Renault", "Kwid", 2022, 22000, "Laranja", "Manual", 49900.0),
    ("Renault", "Duster", 2020, 58000, "Marrom", "Automático", 82900.0),
    ("Nissan", "Kicks", 2021, 40000, "Vermelho", "Automático", 99900.0),
    ("Toyota", "Hilux", 2019, 89000, "Prata", "Automático", 189900.0),
]
# Carros que JÁ foram vendidos no histórico (entram no estoque e saem como vendidos).
VENDIDOS_DEMO = [
    ("Hyundai", "Creta", 2020, 47000, "Branco", "Automático", 98900.0, "avista", None),
    ("Chevrolet", "Tracker", 2021, 35000, "Prata", "Automático", 112900.0, "financiado", 48),
    ("Fiat", "Mobi", 2021, 30000, "Vermelho", "Manual", 45900.0, "financiado", 36),
    ("Volkswagen", "Virtus", 2020, 50000, "Preto", "Automático", 82900.0, "avista", None),
    ("Toyota", "Yaris", 2021, 33000, "Cinza", "Automático", 89900.0, "financiado", 60),
    ("Honda", "City", 2019, 62000, "Branco", "Automático", 76900.0, "avista", None),
]

POLITICAS_DEMO = [
    ("Troca", "A loja aceita carro na troca como parte do pagamento. O carro do cliente é avaliado "
              "presencialmente por um vendedor, que define o valor. O assistente anota modelo, ano, "
              "quilometragem e estado, mas nunca informa valor de avaliação."),
    ("Garantia", "Todos os carros têm garantia de 3 meses para motor e câmbio, a partir da data da compra. "
                 "Itens de desgaste (pneus, pastilhas de freio, embreagem) não entram na garantia."),
    ("Financiamento", "Financiamos por bancos parceiros, de 12 a 60 parcelas. A entrada recomendada é de 20% "
                      "do valor do carro, mas pode variar conforme a análise de crédito. A aprovação do crédito "
                      "é do banco; um vendedor acompanha a análise com o cliente. A simulação do assistente é "
                      "só uma estimativa."),
    ("Test-drive", "O test-drive é feito na loja, com CNH válida do condutor e assinatura de um termo de "
                   "responsabilidade. Agende pelo assistente; a equipe confirma o horário."),
]

# Equipe fictícia, SEM telefone nem Telegram (a demo não manda aviso por canal real).
EQUIPE_DEMO = [("Ana (dona, fictícia)", "dono"), ("Bruno (gerente, fictício)", "gestor"),
               ("Carla (vendedora, fictícia)", "vendedor"), ("Diego (vendedor, fictício)", "vendedor")]
NOMES_CLIENTES = ["Marcos", "Juliana", "Paulo", "Fernanda", "Rafael", "Camila", "Lucas", "Patrícia",
                  "Thiago", "Aline", "Rodrigo", "Beatriz", "Gustavo", "Larissa", "Felipe", "Renata"]
MOTIVOS_CHAMADO = ["Cliente pediu desconto.", "Cliente quer simular financiamento com a equipe.",
                   "Cliente pediu para falar com uma pessoa.", "Cliente pediu valor da troca.",
                   "Cliente perguntou sobre laudo."]

# Tabelas com loja_id que NÃO são apagadas no reinício (identidade, acesso e auditoria).
_NAO_APAGAR = {"lojas", "estado_lojas", "canais", "registro_acoes", "config_historico", "sessoes",
               "links_senha", "acessos", "precos"}


class LojaNaoEDemo(ValueError):
    """Reiniciar/recriar só vale para loja marcada como demo."""


# ------------------------------------------------------------ fotos ilustrativas (Pillow)

def _slug(texto: str) -> str:
    import re
    import unicodedata
    sem = "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "-", sem.lower()).strip("-")


_CORES = {"Prata": (190, 190, 195), "Preto": (40, 40, 45), "Branco": (235, 235, 235), "Cinza": (120, 120, 125),
          "Vermelho": (180, 40, 40), "Azul": (40, 80, 170), "Verde": (60, 110, 70), "Laranja": (220, 120, 40),
          "Marrom": (110, 80, 50)}


def desenhar_foto_ilustrativa(marca: str, modelo: str, ano: int, cor: str) -> bytes:
    """Desenha uma silhueta simples do carro (Pillow), com modelo, cor e a faixa FOTO ILUSTRATIVA.
    Devolve os bytes (PNG). Nunca baixa nada da internet."""
    import io
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (800, 450), (225, 235, 245))
    d = ImageDraw.Draw(img)
    corpo = _CORES.get(cor, (150, 150, 150))
    d.rectangle((0, 330, 800, 450), fill=(90, 95, 100))                       # chão
    d.rounded_rectangle((120, 200, 680, 310), radius=30, fill=corpo)          # carroceria
    d.polygon([(230, 200), (300, 130), (520, 130), (600, 200)], fill=corpo)   # cabine
    d.polygon([(250, 198), (310, 145), (400, 145), (400, 198)], fill=(170, 200, 225))
    d.polygon([(410, 198), (410, 145), (510, 145), (580, 198)], fill=(170, 200, 225))
    for x in (220, 580):
        d.ellipse((x - 45, 265, x + 45, 355), fill=(30, 30, 30))
        d.ellipse((x - 20, 290, x + 20, 330), fill=(160, 160, 160))
    try:
        grande, pequena = ImageFont.load_default(size=34), ImageFont.load_default(size=24)
    except TypeError:
        grande = pequena = ImageFont.load_default()
    d.text((30, 25), f"{marca} {modelo} {ano} - {cor}", fill=(20, 20, 20), font=grande)
    d.rectangle((0, 395, 800, 450), fill=(200, 30, 30))
    d.text((250, 405), "FOTO ILUSTRATIVA", fill=(255, 255, 255), font=pequena)
    saida = io.BytesIO()
    img.save(saida, format="PNG")
    return saida.getvalue()


def foto_da_demo(loja_id: int, marca: str, modelo: str, ano: int, cor: str) -> str:
    """Maratona Fotos: a foto ilustrativa passa pelo preparo único e vai para o depósito, como a
    de qualquer loja. Devolve a referência que fica no carro."""
    from app import fotos
    return fotos.guardar(loja_id, desenhar_foto_ilustrativa(marca, modelo, ano, cor))


def _fotos_antigas(conexao, loja_id: int) -> list[str]:
    refs = []
    for linha in conexao.execute("SELECT fotos FROM estoque WHERE loja_id = ?", (loja_id,)):
        refs.extend(u.strip() for u in str(linha["fotos"] or "").split(",") if u.strip())
    return refs


# ------------------------------------------------------------ criar e reiniciar

def e_demo(loja_id: int) -> bool:
    conexao = conectar()
    try:
        linha = conexao.execute("SELECT config FROM lojas WHERE id = ?", (exigir_loja(loja_id),)).fetchone()
    finally:
        conexao.close()
    if linha is None:
        return False
    try:
        return bool((json.loads(linha["config"] or "{}") or {}).get("demo"))
    except ValueError:
        return False


def id_da_loja_demo() -> int | None:
    conexao = conectar()
    try:
        linhas = conexao.execute("SELECT id, config FROM lojas ORDER BY id").fetchall()
    finally:
        conexao.close()
    for l in linhas:
        try:
            if (json.loads(l["config"] or "{}") or {}).get("demo"):
                return l["id"]
        except ValueError:
            continue
    return None


def _tabelas_da_loja(conexao) -> list[str]:
    tabelas = [r["name"] for r in conexao.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    return [t for t in tabelas if t not in _NAO_APAGAR and
            "loja_id" in {c["name"] for c in conexao.execute(f"PRAGMA table_info({t})")}]


def _apagar_dados(conexao, loja_id: int) -> None:
    for tabela in _tabelas_da_loja(conexao):
        conexao.execute(f"DELETE FROM {tabela} WHERE loja_id = ?", (loja_id,))


def criar_loja_demo(*, loja_id: int | None = None, agora: datetime | None = None, indexar: bool = True,
                    com_historico: bool = True) -> int:
    """Cria a loja demo (ou recria, se já existir uma loja demo). Devolve o id.
    loja_id: só para a bancada (usa a loja 1 do banco temporário). indexar=False: não chama o
    índice de busca (testes e bancada)."""
    agora = agora or agora_utc()
    conexao = conectar()
    try:
        alvo = loja_id or id_da_loja_demo()
        if alvo is not None:
            existe = conexao.execute("SELECT config FROM lojas WHERE id = ?", (alvo,)).fetchone()
            # M3/N1 (revisão #1): mesmo com loja_id explícito, só recria loja que não existe ou que já é demo.
            if existe is not None and not (json.loads(existe["config"] or "{}") or {}).get("demo"):
                raise LojaNaoEDemo(f"a loja {alvo} não está marcada como demo; nada foi apagado")
        config = json.dumps(CONFIG_DEMO, ensure_ascii=False)
        if alvo is None:
            alvo = conexao.execute("INSERT INTO lojas (nome, segmento, config) VALUES (?, 'veiculos', ?)",
                                   (NOME_DEMO, config)).lastrowid
        elif conexao.execute("SELECT 1 FROM lojas WHERE id = ?", (alvo,)).fetchone():
            conexao.execute("UPDATE lojas SET nome = ?, segmento = 'veiculos', config = ?, ativo = 1 WHERE id = ?",
                            (NOME_DEMO, config, alvo))
        else:
            conexao.execute("INSERT INTO lojas (id, nome, segmento, config) VALUES (?, ?, 'veiculos', ?)",
                            (alvo, NOME_DEMO, config))
        antigas = _fotos_antigas(conexao, alvo)
        _apagar_dados(conexao, alvo)
        conexao.execute("DELETE FROM canais WHERE loja_id = ?", (alvo,))     # só o simulador (sem canal real)
        for nome, papel in EQUIPE_DEMO:
            conexao.execute("INSERT INTO usuarios (loja_id, nome, papel) VALUES (?, ?, ?)", (alvo, nome, papel))
        for titulo, texto in POLITICAS_DEMO:
            conexao.execute("INSERT INTO conhecimento (loja_id, titulo, texto) VALUES (?, ?, ?)", (alvo, titulo, texto))
        for marca, modelo, ano, km, cor, cambio, preco in ESTOQUE_DEMO:
            foto = foto_da_demo(alvo, marca, modelo, ano, cor)
            conexao.execute("INSERT INTO estoque (loja_id, marca, modelo, ano, km, cor, cambio, preco, status, fotos) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'disponivel', ?)",
                            (alvo, marca, modelo, ano, km, cor, cambio, preco, foto))
        conexao.commit()
    finally:
        conexao.close()
    from app import fotos, lojas
    for ref in antigas:                       # as fotos da demo anterior saem do depósito
        fotos.apagar(alvo, ref)
    lojas.limpar_cache()
    _no_ar(alvo, agora)
    if com_historico:
        _historico(alvo, agora)
    if indexar:
        try:
            from app.conhecimento import reindexar_loja
            reindexar_loja(alvo)
        except Exception as erro:            # sem rede/chave: a base fica no banco; reindexar depois
            print(f"[Demo] Aviso: não consegui indexar a base agora ({type(erro).__name__}).")
    return alvo


def _no_ar(loja_id: int, agora: datetime) -> None:
    """N1 (revisão #24): a demo entra no ar pelo caminho de sempre (colocar_no_ar), que grava no
    Registro. Quem age é o script da demo, com papel de operador. Já no ar: nada muda."""
    from app.ator import como
    from app.estado_loja import colocar_no_ar
    with como("Demo (script)", "operador", "job", None):
        colocar_no_ar(loja_id, agora)


def reiniciar_demo(loja_id: int, *, agora: datetime | None = None, indexar: bool = True) -> int:
    """Apaga e recria SÓ a loja demo. Recusa qualquer outra loja. Grava no Registro (exige ator)."""
    from app.registro import conferir_ator, registrar
    loja_id = exigir_loja(loja_id)
    if not e_demo(loja_id):
        raise LojaNaoEDemo(f"a loja {loja_id} não está marcada como demo; nada foi apagado")
    conferir_ator(loja_id)
    criar_loja_demo(loja_id=loja_id, agora=agora, indexar=indexar)
    registrar("reiniciar_demo", loja_id, None, {"loja": NOME_DEMO}, alvo=f"loja:{loja_id}")
    return loja_id


# ------------------------------------------------------------ histórico de 30 dias

def _historico(loja_id: int, agora: datetime) -> None:
    """Leads, conversas, chamados, visitas, remarketing e custo de 30 dias (semente fixa) e vendas
    pelo caminho único (registrar_venda), que já agenda o pós-venda."""
    rng = random.Random(SEMENTE)
    conexao = conectar()
    try:
        carros = [dict(l) for l in conexao.execute(
            "SELECT id, marca, modelo, ano, preco FROM estoque WHERE loja_id = ? ORDER BY id", (loja_id,))]
        n = 0
        for dia in range(DIAS_DE_HISTORICO, 0, -1):
            for _ in range(rng.randint(1, 3)):
                n += 1
                lead = f"demo-cliente-{n:03d}"
                carro = rng.choice(carros)
                nome = rng.choice(NOMES_CLIENTES)
                hora = rng.choice([9, 10, 11, 14, 15, 16, 19, 20, 21, 22])     # 19h+ = fora do horário
                inicio = (agora - timedelta(days=dia)).replace(hour=hora % 24, minute=rng.randint(0, 59),
                                                                 second=0, microsecond=0)
                quando = lambda minutos: para_banco(inicio + timedelta(minutes=minutos))  # noqa: E731
                nome_carro = f"{carro['marca']} {carro['modelo']} {carro['ano']}"
                conversa = [("cliente", f"Oi, ainda tem o {carro['modelo']}?", 0),
                            ("leo", f"Oi, {nome}! Tenho sim o {nome_carro}. Quer ver fotos ou saber mais detalhes?", 1),
                            ("cliente", "Quanto tá?", 3),
                            ("leo", f"O {nome_carro} está por R$ {carro['preco']:,.2f}.".replace(",", "X")
                             .replace(".", ",").replace("X", "."), 4)]
                for direcao, texto, minutos in conversa:
                    conexao.execute("INSERT INTO mensagens (lead_id, loja_id, canal, direcao, tipo, conteudo, criado_em) "
                                    "VALUES (?, ?, 'simulador', ?, 'texto', ?, ?)",
                                    (lead, loja_id, direcao, texto, quando(minutos)))
                    if direcao == "leo":
                        conexao.execute(
                            "INSERT INTO uso_custos (loja_id, lead_id, canal, execucao_id, criado_em, tokens_entrada, "
                            "tokens_saida, custo_llm, custo_meta, tipo, modelo, custo_completo, latencia_ms) "
                            "VALUES (?, ?, 'simulador', ?, ?, ?, ?, ?, 0, 'turno', 'demo', 1, ?)",
                            (loja_id, lead, f"demo-{n}-{minutos}", quando(minutos), rng.randint(2500, 6000),
                             rng.randint(80, 220), round(rng.uniform(0.004, 0.012), 4), rng.randint(1500, 4500)))
                conexao.execute("INSERT INTO leads (lead_id, loja_id, nome, interesse, criado_em, atualizado_em) "
                                "VALUES (?, ?, ?, ?, ?, ?)", (lead, loja_id, nome, nome_carro, quando(0), quando(4)))
                conexao.execute("INSERT INTO interesse_veiculo (loja_id, lead_id, veiculo_id, atualizado_em) "
                                "VALUES (?, ?, ?, ?)", (loja_id, lead, carro["id"], quando(4)))
                sorteio = rng.random()
                if sorteio < 0.25:                                            # chamado
                    estado = "aguardando_humano" if dia <= 1 else rng.choice(["encerrado", "encerrado", "humano_assumiu"])
                    conexao.execute(
                        "INSERT INTO handoffs (lead_id, loja_id, motivo, resumo, estado, vendedor, criado_em, "
                        "assumido_em, encerrado_em) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (lead, loja_id, rng.choice(MOTIVOS_CHAMADO), f"{nome} quer o {nome_carro}.", estado,
                         None if estado == "aguardando_humano" else rng.choice(["Carla", "Diego"]), quando(5),
                         None if estado == "aguardando_humano" else quando(rng.randint(8, 40)),
                         quando(rng.randint(60, 300)) if estado == "encerrado" else None))
                elif sorteio < 0.40:                                          # visita marcada
                    conexao.execute("INSERT INTO agendamentos (lead_id, loja_id, nome_cliente, tipo, data_hora, status, "
                                    "criado_em) VALUES (?, ?, ?, ?, ?, 'agendado', ?)",
                                    (lead, loja_id, nome, rng.choice(["visita", "test-drive"]),
                                     (inicio + timedelta(days=2)).strftime("%d/%m às 10:00"), quando(5)))
                elif sorteio < 0.60 and dia > 3:                              # remarketing (simulado)
                    conexao.execute(
                        "INSERT INTO remarketing_envios (loja_id, lead_id, canal, toque, veiculo_id, categoria, estado, "
                        "contexto, criado_em) VALUES (?, ?, 'simulador', 1, ?, 'livre', 'simulado', ?, ?)",
                        (loja_id, lead, carro["id"], json.dumps({"texto": f"Oi, {nome}! O {carro['modelo']} ainda está aqui. "
                                                                          "Quer marcar uma visita?"}, ensure_ascii=False),
                         para_banco(inicio + timedelta(days=2))))
        conexao.commit()
    finally:
        conexao.close()
    _vendas(loja_id, agora, rng)


def _vendas(loja_id: int, agora: datetime, rng: random.Random) -> None:
    from app.ator import como_sistema
    from app.relogio import dia_local
    from app.lojas import carregar_loja
    from app.vendas import registrar_venda
    loja = carregar_loja(loja_id)
    with como_sistema("Demo", "job"):
        for i, (marca, modelo, ano, km, cor, cambio, preco, forma, meses) in enumerate(VENDIDOS_DEMO):
            foto = foto_da_demo(loja_id, marca, modelo, ano, cor)
            conexao = conectar()
            try:
                carro_id = conexao.execute(
                    "INSERT INTO estoque (loja_id, marca, modelo, ano, km, cor, cambio, preco, status, fotos) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'disponivel', ?)",
                    (loja_id, marca, modelo, ano, km, cor, cambio, preco, foto)).lastrowid
                lead = f"demo-comprador-{i + 1:02d}"
                quando = agora - timedelta(days=25 - i * 4)
                conexao.execute("INSERT INTO mensagens (lead_id, loja_id, canal, direcao, tipo, conteudo, criado_em) "
                                "VALUES (?, ?, 'simulador', 'cliente', 'texto', ?, ?)",
                                (lead, loja_id, f"Quero ver o {modelo}.", para_banco(quando - timedelta(days=2))))
                conexao.execute("INSERT INTO leads (lead_id, loja_id, nome, interesse, criado_em) VALUES (?, ?, ?, ?, ?)",
                                (lead, loja_id, rng.choice(NOMES_CLIENTES), f"{marca} {modelo} {ano}",
                                 para_banco(quando - timedelta(days=2))))
                conexao.commit()
            finally:
                conexao.close()
            registrar_venda(loja_id, lead, carro_id, dia_local(loja, quando), forma, meses_financiamento=meses,
                            vendedor=rng.choice(["Carla", "Diego"]), agora=agora)




# ------------------------------------------------------------ leitura para o simulador (D2)

def cabecalho_do_simulador(loja_id: int) -> dict:
    """Nome do assistente e da loja, vindos da configuração (a tela só mostra)."""
    from app.lojas import carregar_loja
    loja = carregar_loja(exigir_loja(loja_id))
    return {"agente": loja.get("nome_agente") or "Léo", "loja": loja.nome, "demo": bool(loja.get("demo"))}


def mensagens_do_vendedor(loja_id: int, lead_id: str, depois_de: int) -> list[dict]:
    """Q2: o que o vendedor respondeu pelo painel nesta conversa do simulador, depois da
    mensagem de número 'depois_de'. Só lê. [{id, autor, texto}] em ordem."""
    conexao = conectar()
    try:
        linhas = conexao.execute(
            "SELECT id, autor, conteudo FROM mensagens WHERE loja_id = ? AND lead_id = ? "
            "AND direcao = 'vendedor' AND id > ? ORDER BY id", (exigir_loja(loja_id), str(lead_id), int(depois_de))
        ).fetchall()
    finally:
        conexao.close()
    return [{"id": int(l["id"]), "autor": l["autor"] or "Vendedor", "texto": l["conteudo"] or ""} for l in linhas]


def avisos_ao_vendedor(loja_id: int, lead_id: str) -> list[dict]:
    """O que o vendedor recebeu nesta conversa (motivo e resumo do chamado), sem Telegram.
    Hora já no fuso da loja, pronta para a tela."""
    from app.apresentacao import horario_para_tela
    from app.lojas import carregar_loja
    loja = carregar_loja(exigir_loja(loja_id))
    conexao = conectar()
    try:
        linhas = conexao.execute("SELECT motivo, resumo, estado, criado_em FROM handoffs "
                                 "WHERE loja_id = ? AND lead_id = ? ORDER BY id", (loja.id, str(lead_id))).fetchall()
    finally:
        conexao.close()
    rotulos = {"aguardando_humano": "esperando um vendedor", "humano_assumiu": "vendedor assumiu",
               "encerrado": "encerrado"}
    return [{"motivo": l["motivo"] or "", "resumo": l["resumo"] or "", "situacao": rotulos.get(l["estado"], ""),
             "quando": horario_para_tela(loja, l["criado_em"])} for l in linhas]
