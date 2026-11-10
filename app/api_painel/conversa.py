"""
Uma conversa (C2c): histórico, cartão "O que o Léo já sabe", estado do chamado,
janela de 24 h, aviso de loja em teste e as ações permitidas para QUEM pede.

- acoes: cada botão vem com "permitida" e, se desligado, o motivo em palavras.
- responder: só quem assumiu, com a janela aberta, por canal que aceita envio.
- devolver: quem assumiu; o dono e o gerente também devolvem a de outra pessoa.
- reativar_contato: dono e gerente, se o cliente pediu para não ser procurado
  (a rota entra no C2d, com o Registro).
- Conversa de outra loja não existe (o chamador responde 404).
Só lê: nada aqui grava no banco.
"""
from __future__ import annotations

from banco import conectar
from app.api_painel.atender import (AGUARDANDO, ASSUMIDO, CANAL_SEM_RESPOSTA, JANELA_FECHADA,
                                    NENHUM, SEM_MENSAGEM, janela_do_cartao)
from app.api_painel.formato import horario
from app.api_painel.saude import FAIXA_EM_TESTE
from app.envio_painel import CANAIS_COM_ENVIO
from app.estado_loja import esta_no_ar
from app.interesse import situacao_do_lead
from app.lojas import carregar_loja
from app.painel_leitura import cartao_do_lead
from app.relogio import agora_utc

ATUALIZAR_EM_SEGUNDOS = 10          # contrato, regra 10 (conversa aberta)
MAX_LEAD = 80
MAX_MENSAGENS = 300
DE = ("cliente", "leo", "vendedor")
TIPOS = ("texto", "audio", "imagem")
GESTAO = ("dono", "gestor")
JANELA_FECHADA_CONVERSA = (JANELA_FECHADA + " Só uma mensagem modelo aprovada pelo WhatsApp "
                           "pode reabrir a conversa.")
FORA_DA_JANELA = "Fora da janela de 24 h. O campo fica desligado até o cliente escrever de novo."
INDISPONIVEL = "Indisponível agora."
CAMPOS_DO_CARTAO = ("origem", "carro", "pagamento", "troca", "prazo", "visita",
                    "motivo_do_chamado", "etiqueta", "etapa", "etapa_rotulo", "proximo_passo")


def lead_valido(lead) -> str | None:
    texto = str(lead or "").strip()
    return texto if 0 < len(texto) <= MAX_LEAD else None


def fatos(loja_id: int, lead: str) -> dict:
    """Mensagens (as últimas), chamado aberto e se o cliente existe NESTA loja."""
    conexao = conectar()
    conexao.execute("PRAGMA query_only = ON")
    try:
        linhas = conexao.execute(
            "SELECT id, direcao, tipo, conteudo, canal, autor, criado_em FROM mensagens "
            "WHERE loja_id = ? AND lead_id = ? ORDER BY id DESC LIMIT ?",
            (loja_id, lead, MAX_MENSAGENS)).fetchall()
        chamado = conexao.execute(
            "SELECT estado, vendedor FROM handoffs WHERE loja_id = ? AND lead_id = ? "
            "AND estado != 'encerrado' ORDER BY id DESC LIMIT 1", (loja_id, lead)).fetchone()
        existe = bool(linhas) or chamado is not None or conexao.execute(
            "SELECT 1 FROM leads WHERE loja_id = ? AND lead_id = ? UNION ALL "
            "SELECT 1 FROM handoffs WHERE loja_id = ? AND lead_id = ? LIMIT 1",
            (loja_id, lead, loja_id, lead)).fetchone() is not None
    finally:
        conexao.close()
    mensagens = [dict(l) for l in reversed(linhas)]
    if chamado is None:
        estado = NENHUM
    else:
        estado = ASSUMIDO if chamado["estado"] == "humano_assumiu" else AGUARDANDO
    return {"existe": existe, "mensagens": mensagens,
            "canal": (mensagens[-1]["canal"] if mensagens else "") or "",
            "estado": estado,
            "assumido_por": chamado["vendedor"] if estado == ASSUMIDO else None}


def montar_mensagem(loja, m: dict, agora=None) -> dict | None:
    quando = horario(loja, m.get("criado_em"), agora)
    if quando is None or m.get("direcao") not in DE:
        return None
    tipo = m.get("tipo") or "texto"
    return {"id": m["id"], "de": m["direcao"],
            "autor": m.get("autor") if m["direcao"] == "vendedor" else None,
            "tipo": tipo if tipo in TIPOS else "outro",
            "texto": m.get("conteudo") or "", "canal": m.get("canal") or "", "quando": quando}


def _acao(motivo) -> dict:
    return {"permitida": motivo is None, "motivo": motivo}


def motivo_para_nao_assumir(f: dict, nome: str):
    if f["estado"] != ASSUMIDO:
        return None
    if f["assumido_por"] == nome:
        return "Você já assumiu esta conversa."
    return f"{f['assumido_por'] or 'Outra pessoa'} já assumiu esta conversa."


def motivo_para_nao_responder(f: dict, janela: dict, nome: str):
    if f["estado"] != ASSUMIDO:
        return "Assuma a conversa antes de responder."
    if f["assumido_por"] != nome:
        return f"Esta conversa está com {f['assumido_por'] or 'outra pessoa'}."
    canal = f["canal"]
    if canal not in CANAIS_COM_ENVIO:
        if canal == "simulador":
            return "O simulador não recebe mensagens do painel."
        return CANAL_SEM_RESPOSTA if canal else SEM_MENSAGEM
    if not janela["aberta"]:
        return FORA_DA_JANELA
    return None


def motivo_para_nao_devolver(f: dict, sessao: dict):
    if f["estado"] == NENHUM:
        return "A conversa já está com o Léo."
    if f["estado"] == AGUARDANDO:
        return "A conversa ainda não foi assumida."
    if f["assumido_por"] != sessao["nome"] and sessao["papel"] not in GESTAO:
        return f"Esta conversa está com {f['assumido_por'] or 'outra pessoa'}."
    return None


def _motivo_para_nao_reativar(loja_id: int, lead: str, sessao: dict):
    if sessao["papel"] not in GESTAO:
        return INDISPONIVEL
    situacao = situacao_do_lead(loja_id, lead) or {}
    if situacao.get("situacao") not in ("nao_contatar", "sem_interesse"):
        return INDISPONIVEL
    return None


def montar_conversa(loja_id: int, lead: str, sessao: dict, agora=None) -> dict | None:
    """A conversa no formato do contrato, ou None se ela não existe nesta loja."""
    agora = agora or agora_utc()
    f = fatos(loja_id, lead)
    if not f["existe"]:
        return None
    loja = carregar_loja(loja_id)
    janela = janela_do_cartao(loja, loja_id, lead, f["canal"], agora)
    if janela["explicacao"] == JANELA_FECHADA:
        janela["explicacao"] = JANELA_FECHADA_CONVERSA

    cartao = cartao_do_lead(loja_id, lead, agora=agora)
    cliente = {"lead": lead, "nome": cartao["nome"]}
    if cartao.get("telefone"):
        cliente["telefone"] = cartao["telefone"]
    cliente.update({campo: cartao.get(campo) or "" for campo in CAMPOS_DO_CARTAO})
    ultima = f["mensagens"][-1]["criado_em"] if f["mensagens"] else None
    cliente["ultimo_contato"] = horario(loja, ultima, agora)

    mensagens = [x for x in (montar_mensagem(loja, m, agora) for m in f["mensagens"]) if x]
    return {
        "atualizar_em_segundos": ATUALIZAR_EM_SEGUNDOS,
        "cliente": cliente,
        "mensagens": mensagens,
        "estado_do_chamado": f["estado"],
        "assumido_por": f["assumido_por"],
        "janela": janela,
        "aviso": None if esta_no_ar(loja_id) else FAIXA_EM_TESTE,
        "acoes": {
            "assumir": _acao(motivo_para_nao_assumir(f, sessao["nome"])),
            "responder": _acao(motivo_para_nao_responder(f, janela, sessao["nome"])),
            "devolver": _acao(motivo_para_nao_devolver(f, sessao)),
            "registrar_venda": _acao(None),
            "reativar_contato": _acao(_motivo_para_nao_reativar(loja_id, lead, sessao)),
        },
    }
