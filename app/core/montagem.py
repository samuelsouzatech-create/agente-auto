"""Monta o Léo de CADA loja: prompt em camadas e ferramentas por módulo.

Camadas do prompt (item 1.3 da Arquitetura 4.0):
  1. Identidade da loja (nome do agente, loja, tom, horário) - vem da config.
  2. prompts/base.md - regras duras, iguais para todas as lojas.
  3. segmentos/<segmento>/prompt.md - persona e objetivo do ramo.
  4. Guia das ferramentas LIGADAS nesta loja + avisos dos módulos desligados.
  5. (Bloco 7A) Momento desta conversa: primeiro contato / vendedor a caminho.
  6. Data e hora no fuso da loja.

Etapa 2, Bloco 1: as ferramentas do ramo vêm da pasta do segmento
(segmentos/<segmento>/ferramentas.py), via app/segmentos.py.
Este módulo não cria o modelo de IA, então os testes podem importá-lo sem chave.
"""
from pathlib import Path
from zoneinfo import ZoneInfo

from app.leitura_config import valor_config
from app.segmentos import (
    PASTA_SEGMENTOS,  # noqa: F401  (compatibilidade; quem manda é app/segmentos.py)
    ferramentas_de_modulo_do_segmento, ferramentas_do_segmento, pasta_do_segmento,
)
from tools import (
    consultar_estoque, detalhes_veiculo, enviar_fotos, simular_financiamento,
    registrar_troca, agendar_visita, registrar_lead, acionar_handoff,
    buscar_conhecimento, registrar_interesse,
)

RAIZ = Path(__file__).resolve().parents[2]
PASTA_PROMPTS = RAIZ / "prompts"
FUSO_PADRAO = "America/Recife"

# Valem para qualquer segmento.
FERRAMENTAS_UNIVERSAIS = [registrar_lead, acionar_handoff, buscar_conhecimento, registrar_interesse]

# Enquanto o vendedor não chega (decisão 1.12, opção B), o Léo não simula:
# número de parcela é assunto que o vendedor fecha.
FERRAMENTAS_FORA_DA_ESPERA = {"simular_financiamento"}

# Lista de todas as tools conhecidas (o agente usa para injetar loja_id).
TODAS_AS_FERRAMENTAS = [
    consultar_estoque, detalhes_veiculo, enviar_fotos, simular_financiamento,
    registrar_troca, agendar_visita, registrar_lead, acionar_handoff,
    buscar_conhecimento, registrar_interesse,
]

DESCRICOES = {
    "consultar_estoque": "o cliente pergunta sobre carros, modelos, preços ou disponibilidade.",
    "detalhes_veiculo": "o cliente quer saber mais de um carro específico que já apareceu na conversa.",
    "simular_financiamento": "o cliente pede simulação de parcelas (sempre com o aviso de estimativa).",
    "registrar_troca": "o cliente diz que tem um carro para dar na troca.",
    "agendar_visita": "o cliente quer visitar a loja, fazer test-drive ou receber uma ligação.",
    "enviar_fotos": ("o cliente pede fotos. Se ele não disser de qual carro "
                     "(ex.: 'manda o que tiver'), chame sem filtros: a ferramenta "
                     "diz quais carros têm fotos."),
    "registrar_lead": "quando já souber o interesse e algum dado do cliente.",
    "acionar_handoff": "OBRIGATÓRIO em qualquer caso vermelho (ver REGRA OBRIGATÓRIA DO HANDOFF).",
    "buscar_conhecimento": ("dúvidas sobre políticas da loja: financiamento, troca, "
                            "garantia, test-drive, horário de atendimento."),
    "registrar_interesse": ("o cliente deixa claro, com as palavras dele, que quer um tempo, "
                            "que não tem mais interesse ou que não quer mais receber mensagens. "
                            "Na dúvida, não use."),
}

AVISOS_MODULO_DESLIGADO = {
    "agendamento": ("Esta loja não agenda pelo chat. Se o cliente quiser visitar, "
                    "fazer test-drive ou receber ligação, registre o interesse com "
                    "registrar_lead e diga que um vendedor vai combinar o horário com ele."),
    "fotos": ("Esta loja não envia fotos pelo chat. Se o cliente pedir fotos, diga "
              "isso com naturalidade e ofereça a ficha do carro ou uma visita."),
}

TEXTO_EM_ESPERA = """VENDEDOR A CAMINHO
- Alguém da equipe de vendas já foi chamado para esta conversa e vai entrar em breve.
- Continue atendendo normalmente, como colega da equipe: dúvidas sobre carros, ficha técnica, fotos, horário, endereço e políticas da loja.
- Preço negociado, desconto, simulação de parcelas, aprovação de crédito e reserva: diga com naturalidade que isso o pessoal das vendas acerta com ele (ex.: "isso o vendedor fecha contigo, já já te chamam aqui").
- Não chame acionar_handoff de novo pelo mesmo assunto. Só chame se surgir um caso vermelho novo.
- Nunca diga "aguarde na fila", "transferindo" ou qualquer coisa que soe como sistema."""

TEXTO_EM_ESPERA_CONVERSAR = """VENDEDOR A CAMINHO
- Alguém da equipe de vendas já foi chamado e vai entrar em breve.
- Continue atendendo normalmente em tudo o que você já faz, inclusive simulações (sempre como estimativa).
- Desconto, preço negociado, aprovação de crédito e reserva continuam sendo do vendedor: diga com naturalidade que ele acerta isso com o cliente.
- Não chame acionar_handoff de novo pelo mesmo assunto. Só chame se surgir um caso vermelho novo.
- Nunca diga "aguarde na fila", "transferindo" ou qualquer coisa que soe como sistema."""

TEXTO_EM_ESPERA_QUIETO = """VENDEDOR A CAMINHO (esta loja prefere que você aguarde o colega)
- Um colega da equipe de vendas já foi chamado. Responda com UMA frase curta e cordial dizendo que ele já vai falar com o cliente (ex.: "Já já o pessoal das vendas te chama aqui, tá?").
- Não responda agora perguntas sobre carros, preços ou condições: o vendedor vai cuidar de tudo.
- Se o cliente disser que não quer mais ser procurado, use registrar_interesse.
- Nunca diga "aguarde na fila", "transferindo" ou qualquer coisa que soe como sistema."""

# Decisão 1.12: a loja escolhe na Configuração (atendimento.aguardando_vendedor).
TEXTOS_EM_ESPERA = {
    "conversar": TEXTO_EM_ESPERA_CONVERSAR,
    "meio_termo": TEXTO_EM_ESPERA,
    "esperar": TEXTO_EM_ESPERA_QUIETO,
}
OPCAO_ESPERA_PADRAO = "meio_termo"
FERRAMENTAS_DA_ESPERA_QUIETA = {"acionar_handoff", "registrar_interesse", "registrar_lead"}


def opcao_de_espera(loja) -> str:
    valor = valor_config(loja.config, "atendimento.aguardando_vendedor", OPCAO_ESPERA_PADRAO)
    return valor if valor in TEXTOS_EM_ESPERA else OPCAO_ESPERA_PADRAO


NOMES_DIAS = ("segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo")
DIAS_SEMANA = ("segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
               "sexta-feira", "sábado", "domingo")


def modulo_ligado(loja, modulo: str) -> bool:
    return bool(valor_config(loja.config, f"modulos.{modulo}", False))


def segmento_da_loja(loja) -> str:
    return getattr(loja, "segmento", None) or "veiculos"


def ferramentas_da_loja(loja, em_espera: bool = False) -> list:
    """Segmento + módulos ligados (do segmento) + universais. Na espera do
    vendedor, a opção da loja decide o que continua valendo."""
    segmento = segmento_da_loja(loja)
    lista = ferramentas_do_segmento(segmento)
    for modulo, tools in ferramentas_de_modulo_do_segmento(segmento).items():
        if modulo_ligado(loja, modulo):
            lista.extend(tools)
    lista.extend(FERRAMENTAS_UNIVERSAIS)
    # Sem repetir (um segmento pode declarar uma universal também).
    vistas, unicas = set(), []
    for f in lista:
        if f.name not in vistas:
            vistas.add(f.name)
            unicas.append(f)
    lista = unicas
    if em_espera:
        opcao = opcao_de_espera(loja)
        if opcao == "meio_termo":
            lista = [f for f in lista if f.name not in FERRAMENTAS_FORA_DA_ESPERA]
        elif opcao == "esperar":
            lista = [f for f in lista if f.name in FERRAMENTAS_DA_ESPERA_QUIETA]
    return lista


# Cache dos .md por data de modificação: editou o arquivo, vale na próxima mensagem.
_cache_arquivos: dict[str, tuple[int, str]] = {}


def _ler_arquivo(caminho: str) -> str:
    p = Path(caminho)
    modificado = p.stat().st_mtime_ns
    guardado = _cache_arquivos.get(caminho)
    if guardado and guardado[0] == modificado:
        return guardado[1]
    texto = p.read_text(encoding="utf-8").strip()
    _cache_arquivos[caminho] = (modificado, texto)
    return texto


_ler_arquivo.cache_clear = _cache_arquivos.clear   # compatibilidade com o lru_cache antigo


def fuso_da_loja(loja) -> ZoneInfo:
    try:
        return ZoneInfo(valor_config(loja.config, "fuso", FUSO_PADRAO))
    except Exception:
        return ZoneInfo(FUSO_PADRAO)


def descrever_dias(dias) -> str:
    try:
        dias = sorted({int(d) for d in dias if 0 <= int(d) <= 6})
    except (TypeError, ValueError):
        return ""
    if not dias:
        return ""
    if len(dias) > 2 and dias == list(range(dias[0], dias[-1] + 1)):
        return f"de {NOMES_DIAS[dias[0]]} a {NOMES_DIAS[dias[-1]]}"
    return ", ".join(NOMES_DIAS[d] for d in dias)


def _camada_da_loja(loja) -> str:
    cfg = loja.config
    nome_agente = valor_config(cfg, "nome_agente", "Léo")
    tom = valor_config(cfg, "tom", "simples, cordial e direto")
    cidade = valor_config(cfg, "cidade", "")
    linhas = [
        "IDENTIDADE (desta loja)",
        f"- Seu nome é {nome_agente}. Você é o assistente virtual da loja {loja.nome}"
        + (f", em {cidade}." if cidade else "."),
        f"- Tom de voz: {tom}.",
    ]
    horario = valor_config(cfg, "atendimento.horario_humano", "")
    dias = descrever_dias(valor_config(cfg, "atendimento.dias_humano", []))
    if horario and "-" in horario:
        inicio, fim = horario.split("-", 1)
        linhas.append(f"- Atendimento com vendedores: {dias}, das {inicio} às {fim}.".replace(": ,", ":"))
    return "\n".join(linhas)


def _guia_ferramentas(loja, ferramentas) -> str:
    linhas = ["QUANDO USAR CADA FERRAMENTA (só estas existem nesta loja)"]
    for f in ferramentas:
        linhas.append(f"- {f.name}: {DESCRICOES.get(f.name, f.description.strip().splitlines()[0])}")
    # Só avisa de módulo que o segmento tem (barbearia não ouve falar de "ficha do carro").
    modulos_do_segmento = ferramentas_de_modulo_do_segmento(segmento_da_loja(loja))
    avisos = [texto for modulo, texto in AVISOS_MODULO_DESLIGADO.items()
              if modulo in modulos_do_segmento and not modulo_ligado(loja, modulo)]
    if avisos:
        linhas.append("")
        linhas.append("LIMITES DESTA LOJA")
        linhas.extend(f"- {a}" for a in avisos)
    return "\n".join(linhas)


def _camada_do_momento(loja, em_espera: bool, primeiro_contato: bool) -> str:
    nome = valor_config(loja.config, "nome_agente", "Léo")
    blocos = []
    if primeiro_contato:
        blocos.append(
            "PRIMEIRO CONTATO\n"
            f"- Esta é a sua primeira resposta para este cliente. Cumprimente e se apresente UMA vez, "
            f"de forma natural, como {nome}, assistente virtual da {loja.nome} "
            f"(ex.: \"Oi! Aqui é o {nome}, assistente virtual da {loja.nome}.\").\n"
            "- Depois disso, não repita a apresentação."
        )
    if em_espera:
        blocos.append(TEXTOS_EM_ESPERA[opcao_de_espera(loja)])
    return "\n\n".join(blocos)


def montar_prompt(loja, ferramentas, agora, *, em_espera: bool = False,
                  primeiro_contato: bool = False) -> str:
    base = _ler_arquivo(str(PASTA_PROMPTS / "base.md"))
    segmento = _ler_arquivo(str(pasta_do_segmento(segmento_da_loja(loja)) / "prompt.md"))
    data = (f"DATA E HORA ATUAL: {agora.strftime('%d/%m/%Y %H:%M')} "
            f"({DIAS_SEMANA[agora.weekday()]}).")
    camadas = [
        _camada_da_loja(loja),
        base,
        segmento,
        _guia_ferramentas(loja, ferramentas),
        _camada_do_momento(loja, em_espera, primeiro_contato),
        data,
    ]
    return "\n\n".join(c for c in camadas if c)
