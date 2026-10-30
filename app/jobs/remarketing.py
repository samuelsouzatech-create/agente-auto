"""
Job de remarketing (Etapa 2, Blocos 3, 4 e 8): manda a mensagem de retomada.

Roda dentro do relógio (python -m app.jobs.runner), a cada 5 minutos.
Para cada loja ativa com o módulo ligado, pergunta à elegibilidade
(Bloco 2) quem pode receber agora, confere DE NOVO cada lead logo antes
de mandar, e escolhe como falar:

  janela aberta (Telegram; WhatsApp só se o cliente falou há < 24 h):
      o assistente escreve uma mensagem natural, no tom da loja,
      retomando o assunto da conversa. Se a IA falhar, escrever algo
      com cara de robô ou disser que já fez algo, usa um texto reserva.
  janela fechada (WhatsApp): modelo aprovado pela Meta, preenchido com
      nome, carro, agente e loja. Modelo não aprovado não sai.

Bloco 4: falhou 3 vezes -> 'bloqueado' (falhas_repetidas) e não tenta
mais sozinho. Lead pulado não ocupa vaga da rodada.

Bloco 8: carro de interesse vendido -> oferece um parecido (mesma loja,
preço até 20% de diferença); sem parecido, bloqueia (carro_vendido) e
confere de novo em 6 h. Limite do mês acabou -> avisa gestor e operador.

MODO SIMULAÇÃO é o padrão: faz tudo, menos enviar, e grava 'simulado'
com o texto que sairia. Envio de verdade só com REMARKETING_ENVIO_REAL=1
no .env, e só pelo runner (que tem a trava no Redis).

Ver o que sairia, sem enviar nada (não precisa de Redis):
    python -m app.jobs.remarketing --loja 1
    python -m app.jobs.remarketing --loja 1 --agora 2026-11-05T10:00 --de-novo
(--agora é no horário da loja; --de-novo apaga as simulações anteriores)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import banco
from banco import conectar
from app import config  # noqa: F401  (carrega o .env)
from app.aviso_limite import avisar_limite
from app.chaves import exigir_loja
from app.pausa import pausado
from app.custos import Uso, registrar_uso, uso_das_mensagens
from app.elegibilidade import Decisao, avaliar, candidatos, elegiveis
from app.lojas import PADROES, TETO_TOQUES_REMARKETING, Loja, carregar_loja, modulo_ativo
from app.relogio import agora_utc, do_banco, para_banco
from app.resultado_envio import ResultadoEnvio
from app.templates import (
    ModeloInexistente, ModeloInvalido, ValoresFaltando, categoria_para_custo,
    modelo_aprovado, modelo_do_segmento, preencher,
)

INTERVALO_S = 300                       # o runner chama a cada 5 minutos
MAX_POR_RODADA = 10                     # por loja, por rodada (só conta quem foi processado)
PAUSA_ENTRE_ENVIOS_S = 3                # não dispara tudo de uma vez
REPETIR_FALHA_APOS = timedelta(hours=6)
MAX_TENTATIVAS = 3                      # falhou 3 vezes: para e espera alguém olhar
LIMITE_TEXTO_LIVRE = 400
MENSAGENS_DE_CONTEXTO = 12
MODELO_COM_CARRO = "retomada_interesse"
MODELO_ALTERNATIVA = "retomada_alternativa"
MODELO_GERAL = "retomada_geral"
FAIXA_PRECO_ALTERNATIVA = 0.20          # parecido = até 20% mais caro ou mais barato
CANAIS_COBRADOS = {"whatsapp"}
ESTADOS = ("enviado", "simulado", "falhou", "bloqueado", "pulado", "erro")

MOTIVOS = {
    "sem_modelo": "O segmento não tem modelo de retomada",
    "faltam_dados": "Falta o nome do cliente para o modelo",
    "modelo_nao_aprovado": "Modelo ainda não aprovado pela Meta nesta loja",
    "janela_fechada": "A Meta recusou: janela de 24 h fechada",
    "erro_no_envio": "O canal recusou o envio",
    "falhas_repetidas": "Falhou 3 vezes; precisa de alguém olhar",
    "carro_vendido": "O carro de interesse foi vendido e não há outro parecido",
}

# Coisas que um vendedor de verdade não escreve.
_CARA_DE_ROBO = re.compile(
    r"(?i)(responda\s+\"?sair|digite\s|parar\s+de\s+receber|n[aã]o\s+quer\s+mais\s+receber"
    r"|rob[oô]\b|assistente\s+virtual|intelig[eê]ncia\s+artificial|sou\s+um\s+bot)"
)
# Promessa de algo que ninguém fez (o certo é OFERECER).
_PROMESSA = re.compile(
    r"(?i)\b(separei|consegui\s+separar|j[aá]\s+(te\s+)?(enviei|mandei|separei)"
    r"|reservei|deixei\s+separad)"
)


def envio_real_ligado() -> bool:
    return (os.getenv("REMARKETING_ENVIO_REAL") or "").strip().lower() in ("1", "true", "sim", "yes")


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


# ------------------------------------------------------------ envio real

class EnviadorReal:
    """Manda pelo número/bot DESTA loja. Nunca levanta exceção."""

    async def texto(self, loja_id, canal: str, lead_id: str, texto: str) -> ResultadoEnvio:
        try:
            if canal == "whatsapp":
                from app.api.enviar_whatsapp import enviar_texto_whatsapp_detalhado
                return await enviar_texto_whatsapp_detalhado(lead_id, texto, loja_id=loja_id)
            if canal == "telegram":
                from telegram import Bot
                from app.credenciais import SemCredencial, token_telegram
                try:
                    token = token_telegram(loja_id)
                except SemCredencial as erro:
                    return ResultadoEnvio(ok=False, detalhe=f"sem credencial: {erro}")
                async with Bot(token) as bot:
                    enviada = await bot.send_message(chat_id=lead_id, text=texto)
                return ResultadoEnvio(ok=True, id_externo=str(enviada.message_id))
        except Exception as erro:
            return ResultadoEnvio(ok=False, detalhe=f"{type(erro).__name__}: {erro}"[:300])
        return ResultadoEnvio(ok=False, detalhe=f"canal {canal} sem envio")

    async def modelo(self, loja_id, lead_id: str, modelo, valores: dict) -> ResultadoEnvio:
        try:
            from app.api.enviar_whatsapp import enviar_template_whatsapp
            return await enviar_template_whatsapp(lead_id, modelo, valores, loja_id=loja_id)
        except Exception as erro:
            return ResultadoEnvio(ok=False, detalhe=f"{type(erro).__name__}: {erro}"[:300])


# ------------------------------------------------------------ redação pela IA

_ORIENTACAO_DO_TOQUE = {
    1: "Primeira retomada: lembre do que ele estava vendo e ofereça uma ajuda concreta "
       "(mais detalhes, fotos, marcar uma visita).",
    2: "Segunda retomada: traga um motivo novo para conversar (tirar uma dúvida, facilitar "
       "a visita, uma opção parecida), sem pressionar.",
    3: "Última retomada: leve e sem pressão, deixe a porta aberta para quando ele quiser.",
}
_QUEM = {"cliente": "Cliente", "leo": "Você", "vendedor": "Vendedor da loja"}


def _linha_do_carro(dados: dict) -> str:
    if dados.get("alternativa"):
        return (f"{dados['carro']} (JÁ FOI VENDIDO: não ofereça esse). "
                f"Ofereça no lugar o {dados['alternativa']}, que está disponível e é parecido.")
    return dados.get("carro") or "-"


def _prompt_redator(loja: Loja, toque: int, dados: dict, historico: list[dict]) -> str:
    agente = loja.get("nome_agente") or "Léo"
    cidade = loja.get("cidade") or ""
    max_toques = min(int(loja.get("remarketing.max_toques") or TETO_TOQUES_REMARKETING),
                     TETO_TOQUES_REMARKETING)
    conversa = "\n".join(
        f"{_QUEM.get(m['direcao'], m['direcao'])}: {str(m['conteudo'] or '')[:300]}"
        for m in historico) or "(sem mensagens)"
    return f"""Você é {agente}, da equipe de vendas da {loja.nome}{' em ' + cidade if cidade else ''}.
Seu tom: {loja.get('tom') or 'simples, cordial e direto'}.

Este cliente conversou com a loja e parou de responder. Escreva a mensagem que você
vai mandar agora para retomar o contato (retomada {toque} de no máximo {max_toques}).

Como escrever:
- Uma mensagem só, curta: no máximo 2 frases e 300 caracteres.
- Natural, como um vendedor de verdade no WhatsApp. Sem markdown, sem listas, no máximo 1 emoji.
- Retome o assunto da conversa abaixo. Não repita o que você já disse.
- OFEREÇA, não diga que já fez: nada de "separei", "consegui separar", "já te mandei" ou "reservei".
- Não invente preço, condição nem desconto. Só fale de carros que aparecem na conversa
  ou na linha "Carro de interesse" abaixo.
- Não fale de robô, IA ou assistente virtual e não dê instruções como "responda SAIR".
- {_ORIENTACAO_DO_TOQUE.get(toque, _ORIENTACAO_DO_TOQUE[3])}
- Escreva só a mensagem, sem aspas.

Nome do cliente: {dados['nome'] or 'não informado'}
Interesse anotado: {dados['interesse'] or '-'}
Carro de interesse: {_linha_do_carro(dados)}

Conversa (mais antiga primeiro):
{conversa}"""


def _texto_da_ia(resposta) -> str:
    conteudo = getattr(resposta, "content", "")
    if isinstance(conteudo, list):
        conteudo = "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in conteudo)
    return str(conteudo or "")


def escrever_com_ia(loja: Loja, lead_id: str, canal: str, toque: int,
                    dados: dict, historico: list[dict]) -> tuple[str, Uso]:
    from app.core.agent import llm      # import tardio: os testes nunca chamam a IA
    resposta = llm.invoke([("system", _prompt_redator(loja, toque, dados, historico)),
                           ("human", "Escreva a mensagem agora.")])
    return _texto_da_ia(resposta), uso_das_mensagens([resposta])


def _limpar_texto(texto) -> str:
    if not isinstance(texto, str):
        return ""
    t = texto.replace("**", "").replace("__", "").strip().strip('"').strip()
    t = re.sub(r"\n{3,}", "\n\n", t)
    if not t or len(t) > LIMITE_TEXTO_LIVRE or _CARA_DE_ROBO.search(t) or _PROMESSA.search(t):
        return ""
    return t


def _primeiro_nome(nome: str) -> str:
    partes = (nome or "").split()
    return partes[0] if partes else ""


def _texto_reserva(loja: Loja, dados: dict) -> str:
    nome = _primeiro_nome(dados["nome"])
    oi = f"Oi, {nome}!" if nome else "Oi!"
    quem = f"{loja.get('nome_agente') or 'Léo'} aqui, da {loja.nome}."
    if dados.get("alternativa"):
        return (f"{oi} {quem} Aquele {dados['carro']} já foi vendido, mas temos um "
                f"{dados['alternativa']} bem parecido. Quer dar uma olhada?")
    if dados["carro_disponivel"]:
        return f"{oi} {quem} O {dados['carro']} que você viu continua disponível. Quer que eu te passe mais detalhes?"
    return f"{oi} {quem} Passando para saber se ainda posso te ajudar. Ficou alguma dúvida?"


# ------------------------------------------------------------ banco

def _nome_do_carro(linha) -> str:
    return f'{linha["marca"]} {linha["modelo"]} {linha["ano"]}'


def _alternativa(conexao, loja_id: int, carro) -> dict | None:
    """Carro disponível parecido com o vendido: mesma loja, preço até 20% de
    diferença; mesmo modelo primeiro, depois mesma marca, depois o preço mais perto."""
    if carro is None or carro["preco"] is None:
        return None
    preco = float(carro["preco"])
    linha = conexao.execute(
        "SELECT id, marca, modelo, ano FROM estoque "
        "WHERE loja_id = ? AND status = 'disponivel' AND id != ? AND preco BETWEEN ? AND ? "
        "ORDER BY (modelo = ?) DESC, (marca = ?) DESC, ABS(preco - ?) LIMIT 1",
        (loja_id, carro["id"], preco * (1 - FAIXA_PRECO_ALTERNATIVA),
         preco * (1 + FAIXA_PRECO_ALTERNATIVA), carro["modelo"], carro["marca"], preco),
    ).fetchone()
    return dict(linha) if linha else None


def _dados_do_lead(loja_id: int, lead_id: str) -> dict:
    conexao = conectar()
    try:
        lead = conexao.execute(
            "SELECT nome, interesse FROM leads WHERE loja_id = ? AND lead_id = ?",
            (loja_id, lead_id)).fetchone()
        carro = conexao.execute(
            "SELECT e.id, e.marca, e.modelo, e.ano, e.preco, e.status FROM interesse_veiculo i "
            "JOIN estoque e ON e.id = i.veiculo_id AND e.loja_id = i.loja_id "
            "WHERE i.loja_id = ? AND i.lead_id = ?", (loja_id, lead_id)).fetchone()
        vendido = bool(carro) and carro["status"] != "disponivel"
        alternativa = _alternativa(conexao, loja_id, carro) if vendido else None
    finally:
        conexao.close()
    return {
        "nome": (lead["nome"] or "").strip() if lead else "",
        "interesse": (lead["interesse"] or "").strip() if lead else "",
        "veiculo_id": carro["id"] if carro else None,
        "carro": _nome_do_carro(carro) if carro else "",
        "carro_disponivel": bool(carro) and not vendido,
        "carro_vendido": vendido,
        "alternativa": _nome_do_carro(alternativa) if alternativa else "",
        "alternativa_id": alternativa["id"] if alternativa else None,
    }


def _historico(loja_id: int, lead_id: str, canal: str) -> list[dict]:
    conexao = conectar()
    try:
        linhas = conexao.execute(
            "SELECT direcao, conteudo FROM mensagens WHERE loja_id = ? AND lead_id = ? "
            "AND canal = ? ORDER BY id DESC LIMIT ?",
            (loja_id, lead_id, canal, MENSAGENS_DE_CONTEXTO)).fetchall()
    finally:
        conexao.close()
    return [dict(l) for l in reversed(linhas)]


def _tentativa_anterior(loja_id: int, lead_id: str, canal: str, toque: int) -> dict | None:
    conexao = conectar()
    try:
        linha = conexao.execute(
            "SELECT estado, motivo_bloqueio, contexto, criado_em FROM remarketing_envios "
            "WHERE loja_id = ? AND lead_id = ? AND canal = ? AND toque = ?",
            (loja_id, lead_id, canal, toque)).fetchone()
    finally:
        conexao.close()
    return dict(linha) if linha else None


def _tentativas_ate_agora(anterior: dict | None) -> int:
    if not anterior or anterior["estado"] != "falhou":
        return 0
    try:
        return int(json.loads(anterior["contexto"] or "{}").get("tentativas") or 1)
    except (TypeError, ValueError):
        return 1


def _deve_pular(anterior: dict | None, real: bool, agora: datetime) -> bool:
    if not anterior:
        return False
    if anterior["estado"] == "enviado":
        return True
    if anterior.get("motivo_bloqueio") == "falhas_repetidas":
        return True                      # só alguém olhando destrava
    if not real:                         # simulação: uma vez por toque basta
        return True
    if anterior["estado"] == "simulado":  # ligou o envio: agora vai de verdade
        return False
    quando = do_banco(anterior["criado_em"])
    return quando is not None and agora - quando < REPETIR_FALHA_APOS


def _gravar_envio(loja_id: int, d: Decisao, agora: datetime, estado: str, *, modelo, categoria,
                  motivo, contexto: dict, veiculo_id, custo_meta, execucao_id: str) -> None:
    quando = para_banco(agora)
    conexao = conectar()
    try:
        conexao.execute(
            """INSERT INTO remarketing_envios (loja_id, lead_id, canal, toque, veiculo_id, modelo,
                   categoria, estado, motivo_bloqueio, contexto, enviado_em, criado_em,
                   custo_meta, execucao_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT (loja_id, lead_id, canal, toque) DO UPDATE SET
                   veiculo_id = excluded.veiculo_id, modelo = excluded.modelo,
                   categoria = excluded.categoria, estado = excluded.estado,
                   motivo_bloqueio = excluded.motivo_bloqueio, contexto = excluded.contexto,
                   enviado_em = excluded.enviado_em, criado_em = excluded.criado_em,
                   custo_meta = excluded.custo_meta, execucao_id = excluded.execucao_id
               WHERE remarketing_envios.estado != 'enviado'""",
            (loja_id, d.lead_id, d.canal, d.toque, veiculo_id, modelo, categoria, estado, motivo,
             json.dumps(contexto, ensure_ascii=False),
             quando if estado == "enviado" else None, quando, custo_meta, execucao_id))
        conexao.commit()
    finally:
        conexao.close()


def _gravar_na_conversa(loja_id: int, lead_id: str, canal: str, texto: str, agora: datetime) -> None:
    """A mensagem enviada aparece no histórico do painel, como fala do assistente."""
    conexao = conectar()
    try:
        conexao.execute(
            "INSERT INTO mensagens (lead_id, loja_id, canal, direcao, tipo, conteudo, autor, criado_em) "
            "VALUES (?, ?, ?, 'leo', 'texto', ?, 'remarketing', ?)",
            (lead_id, loja_id, canal, texto, para_banco(agora)))
        conexao.commit()
    finally:
        conexao.close()


def limpar_simulacoes(loja_id) -> int:
    loja_id = exigir_loja(loja_id)
    conexao = conectar()
    try:
        n = conexao.execute("DELETE FROM remarketing_envios WHERE loja_id = ? AND estado = 'simulado'",
                            (loja_id,)).rowcount
        conexao.commit()
    finally:
        conexao.close()
    return n


# ------------------------------------------------------------ um lead

def _registrar(loja: Loja, d: Decisao, agora: datetime, estado: str, *, real: bool,
               texto: str = "", origem: str = "", modelo: str | None = None,
               categoria: str | None = None, motivo: str | None = None,
               veiculo_id=None, uso: Uso | None = None, detalhe: str = "",
               tentativas: int = 0, extra: dict | None = None) -> str:
    uso = uso or Uso()
    execucao_id = uuid.uuid4().hex
    custo_meta = None
    if estado == "enviado":
        registro = registrar_uso(
            loja.id, d.lead_id, d.canal, uso, tipo="remarketing",
            msgs_servico=1 if categoria == "livre" and d.canal in CANAIS_COBRADOS else 0,
            msgs_utilidade=1 if categoria == "utilidade" else 0,
            msgs_marketing=1 if categoria == "marketing" else 0,
            execucao_id=execucao_id, agora=agora)
        custo_meta = registro["custo_meta"] if registro else None
        _gravar_na_conversa(loja.id, d.lead_id, d.canal, texto, agora)
    elif not uso.vazio:                  # a IA escreveu: os tokens foram gastos
        registrar_uso(loja.id, d.lead_id, d.canal, uso,
                      tipo="remarketing" if real else "remarketing_simulado",
                      execucao_id=execucao_id, agora=agora)
    contexto = {"texto": texto, "origem": origem, "janela_aberta": bool(d.janela_aberta),
                "modo": "real" if real else "simulacao"}
    if extra:
        contexto.update(extra)
    if detalhe:
        contexto["detalhe"] = detalhe[:300]
    if tentativas:
        contexto["tentativas"] = tentativas
    _gravar_envio(loja.id, d, agora, estado, modelo=modelo, categoria=categoria, motivo=motivo,
                  contexto=contexto, veiculo_id=veiculo_id, custo_meta=custo_meta,
                  execucao_id=execucao_id)
    rotulo = {"enviado": "ENVIADO", "simulado": "SIMULADO (nada saiu)",
              "falhou": "FALHOU", "bloqueado": "BLOQUEADO"}[estado]
    print(f"[Remarketing][loja {loja.id}] {rotulo} toque {d.toque} -> {d.lead_id} ({d.canal})"
          + (f" | {MOTIVOS.get(motivo, motivo)}" if motivo else ""))
    if texto and estado in ("simulado", "enviado"):
        print(f'    "{texto}"')
    return estado


def _depois_do_envio(loja, d, agora, resultado: ResultadoEnvio, comum: dict) -> str:
    if resultado.ok:
        return _registrar(loja, d, agora, "enviado", **comum)
    anterior = _tentativa_anterior(loja.id, d.lead_id, d.canal, d.toque)
    tentativas = _tentativas_ate_agora(anterior) + 1
    if tentativas >= MAX_TENTATIVAS:
        return _registrar(loja, d, agora, "bloqueado", motivo="falhas_repetidas",
                          detalhe=resultado.detalhe, tentativas=tentativas, **comum)
    motivo = "janela_fechada" if resultado.janela_fechada else "erro_no_envio"
    return _registrar(loja, d, agora, "falhou", motivo=motivo, detalhe=resultado.detalhe,
                      tentativas=tentativas, **comum)


def _extra_da_alternativa(dados: dict) -> dict | None:
    return {"alternativa_de": dados["carro"]} if dados.get("alternativa") else None


def _mensagem_livre(loja, d, agora, dados, *, real, redator, enviador) -> str:
    try:
        bruto, uso = redator(loja, d.lead_id, d.canal, d.toque, dados,
                             _historico(loja.id, d.lead_id, d.canal))
    except Exception as erro:
        print(f"[Remarketing][loja {loja.id}] IA falhou ({type(erro).__name__}); usando texto reserva.")
        bruto, uso = "", Uso()
    texto, origem = _limpar_texto(bruto), "ia"
    if not texto:
        texto, origem = _texto_reserva(loja, dados), "reserva"
    comum = dict(real=real, texto=texto, origem=origem, categoria="livre",
                 veiculo_id=dados["alternativa_id"] or dados["veiculo_id"], uso=uso,
                 extra=_extra_da_alternativa(dados))
    if not real:
        return _registrar(loja, d, agora, "simulado", **comum)
    resultado = asyncio.run(enviador.texto(loja.id, d.canal, d.lead_id, texto))
    return _depois_do_envio(loja, d, agora, resultado, comum)


def _mensagem_modelo(loja, d, agora, dados, *, real, enviador) -> str:
    if dados["alternativa"]:
        nome_modelo, carro = MODELO_ALTERNATIVA, dados["alternativa"]
    elif dados["carro_disponivel"]:
        nome_modelo, carro = MODELO_COM_CARRO, dados["carro"]
    else:
        nome_modelo, carro = MODELO_GERAL, dados["carro"]
    base = dict(real=real, origem="modelo",
                veiculo_id=dados["alternativa_id"] or dados["veiculo_id"],
                extra=_extra_da_alternativa(dados))
    try:
        modelo = modelo_do_segmento(loja.segmento, nome_modelo)
    except (ModeloInexistente, ModeloInvalido):
        return _registrar(loja, d, agora, "bloqueado", motivo="sem_modelo", modelo=nome_modelo, **base)
    valores = {"nome": _primeiro_nome(dados["nome"]), "carro": carro,
               "agente": loja.get("nome_agente") or "Léo", "loja": loja.nome}
    try:
        texto = preencher(modelo, valores)
    except ValoresFaltando:
        return _registrar(loja, d, agora, "bloqueado", motivo="faltam_dados", modelo=modelo.nome, **base)
    comum = dict(texto=texto, modelo=modelo.nome, categoria=categoria_para_custo(loja.id, modelo), **base)
    if not real:
        return _registrar(loja, d, agora, "simulado", **comum)
    if not modelo_aprovado(loja.id, modelo.nome, modelo.idioma):
        return _registrar(loja, d, agora, "bloqueado", motivo="modelo_nao_aprovado", **comum)
    resultado = asyncio.run(enviador.modelo(loja.id, d.lead_id, modelo, valores))
    return _depois_do_envio(loja, d, agora, resultado, comum)


def processar_lead(loja: Loja, decisao: Decisao, agora: datetime, *, real: bool,
                   redator, enviador) -> str:
    # Confere de novo: o cliente pode ter respondido ou um vendedor assumido.
    d = avaliar(loja.id, decisao.lead_id, decisao.canal, agora)
    if not d.elegivel:
        return "pulado"
    if _deve_pular(_tentativa_anterior(loja.id, d.lead_id, d.canal, d.toque), real, agora):
        return "pulado"
    dados = _dados_do_lead(loja.id, d.lead_id)
    if dados["carro_vendido"] and not dados["alternativa"]:
        # Carro vendido e nada parecido: não manda "ainda tem interesse?".
        # Confere de novo em 6 h (pode entrar um parecido no estoque).
        return _registrar(loja, d, agora, "bloqueado", real=real, origem="regra",
                          motivo="carro_vendido", veiculo_id=dados["veiculo_id"])
    if d.janela_aberta:
        return _mensagem_livre(loja, d, agora, dados, real=real, redator=redator, enviador=enviador)
    return _mensagem_modelo(loja, d, agora, dados, real=real, enviador=enviador)


# ------------------------------------------------------------ rodada

def _ids_lojas_ativas() -> list[int]:
    from app.lojas_admin import listar_lojas
    return [l["id"] for l in listar_lojas() if l["ativo"]]


def rodar_remarketing(agora: datetime | None = None, *, envio_real: bool | None = None,
                      redator=None, enviador=None, pausa_s: float | None = None,
                      max_por_loja: int = MAX_POR_RODADA, lojas: list[int] | None = None) -> dict:
    agora = _utc(agora or agora_utc())
    real = envio_real_ligado() if envio_real is None else bool(envio_real)
    redator = redator or escrever_com_ia
    enviador = enviador or EnviadorReal()
    pausa = PAUSA_ENTRE_ENVIOS_S if pausa_s is None else pausa_s
    totais = dict.fromkeys(ESTADOS, 0)

    for loja_id in (lojas or _ids_lojas_ativas()):
        try:
            loja = carregar_loja(loja_id)
            if not loja.ativo or not modulo_ativo(loja, "remarketing") or pausado(loja_id):
                continue
            fila = elegiveis(loja_id, agora)
        except Exception as erro:        # uma loja com problema não trava as outras
            print(f"[Remarketing] Erro na loja {loja_id}: {erro!r}")
            continue
        try:
            avisar_limite(loja, agora, real=real)
        except Exception as erro:        # o aviso nunca trava os envios
            print(f"[Remarketing] Erro no aviso de limite da loja {loja_id}: {erro!r}")
        processados = 0
        for decisao in fila:
            if processados >= max_por_loja:
                break
            try:
                estado = processar_lead(loja, decisao, agora, real=real,
                                        redator=redator, enviador=enviador)
            except Exception as erro:
                print(f"[Remarketing][loja {loja_id}] Erro com {decisao.lead_id}: {erro!r}")
                estado = "erro"
            totais[estado] += 1
            if estado != "pulado":       # pulado não ocupa vaga da rodada
                processados += 1
            if estado == "enviado" and pausa:
                time.sleep(pausa)
    return totais


# ------------------------------------------------------------ linha de comando (só simulação)

def _ler_agora(texto: str | None) -> datetime:
    if not texto:
        return agora_utc()
    dt = datetime.fromisoformat(texto)
    if dt.tzinfo is None:                # horário da loja
        dt = dt.replace(tzinfo=ZoneInfo(PADROES["fuso"]))
    return _utc(dt)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Remarketing em SIMULAÇÃO (não envia nada).")
    parser.add_argument("--loja", type=int, help="só esta loja")
    parser.add_argument("--agora", help='fingir outra hora, no horário da loja: "2026-11-05T10:00"')
    parser.add_argument("--de-novo", action="store_true", help="apaga as simulações anteriores")
    args = parser.parse_args(argv)

    banco.criar_tabelas()
    agora = _ler_agora(args.agora)
    ids = [args.loja] if args.loja else _ids_lojas_ativas()
    print(f"[Remarketing] SIMULAÇÃO: nada é enviado. Hora usada (UTC): {agora:%Y-%m-%d %H:%M}")

    for loja_id in ids:
        if args.de_novo:
            print(f"Loja {loja_id}: {limpar_simulacoes(loja_id)} simulações apagadas.")
        print(f"\nLoja {loja_id} - situação de cada lead:")
        lista = candidatos(loja_id, agora)
        if not lista:
            print("  (nenhum lead com conversa no WhatsApp ou Telegram)")
        for d in lista:
            extra = f" (próximo: {d.proximo_em:%d/%m %H:%M} UTC)" if d.proximo_em and not d.elegivel else ""
            print(f"  {d.lead_id} ({d.canal}): {d.rotulo}{extra}")

    print()
    totais = rodar_remarketing(agora, envio_real=False, lojas=ids, pausa_s=0)
    print(f"\n[Remarketing] Resultado: {totais}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
