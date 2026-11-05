"""
Como o Registro aparece na tela (S3 da Fase 3). Só LÊ; sem Streamlit.

A tela não converte horário nem monta texto: recebe aqui as linhas prontas.
- "Quando" no fuso da loja de cada linha (evento sem loja: Brasília);
- cliente pelo nome ou telefone formatado (uma consulta por loja, nunca por linha);
- nada técnico: sem id, sem UTC, sem "lead:" nem "config:".
"""
from __future__ import annotations

from datetime import timedelta

from app.apresentacao import data_para_tela, horario_para_tela, nome_do_canal, nomes_dos_clientes
from app.chaves import exigir_loja
from app.config_tela import ROTULO as ROTULO_CAMPO
from app.config_tela import campo, formatar
from app.lojas import LojaNaoEncontrada, carregar_loja
from app.registro_leitura import ACAO_DA_CONFIG, FUSO_GERAL
from app.relogio import agora_utc, dia_local

LIMITE_TELA = 200
DIAS_PADRAO = 30
MAX_DETALHE = 160
SEM_LOJA = "Sistema"
VAZIO = "—"
ROTULOS_PAPEL = {"operador": "Operador", "cliente": "Loja", "sistema": "Sistema"}
FORMAS = {"avista": "à vista", "financiado": "financiado"}


class _Geral:
    """Para eventos sem loja e para o nível Geral: horário de Brasília."""
    nome = SEM_LOJA

    def get(self, chave, padrao=None):
        return FUSO_GERAL if chave == "fuso" else padrao


# ------------------------------------------------------------ período

def periodo_padrao(loja_id, agora=None):
    """Últimos 30 dias, contados no fuso da loja (hoje entra)."""
    loja = carregar_loja(exigir_loja(loja_id))
    hoje = dia_local(loja, agora or agora_utc())
    return hoje - timedelta(days=DIAS_PADRAO - 1), hoje


def periodo_padrao_geral(agora=None):
    """Últimos 30 dias no horário de Brasília (nível Geral)."""
    hoje = dia_local(_Geral(), agora or agora_utc())
    return hoje - timedelta(days=DIAS_PADRAO - 1), hoje


# ------------------------------------------------------------ texto

def _cortar(texto: str) -> str:
    texto = " ".join(str(texto or "").split())
    return texto if len(texto) <= MAX_DETALHE else texto[:MAX_DETALHE - 1] + "…"


def _lead(alvo) -> str | None:
    if isinstance(alvo, str) and alvo.startswith("lead:"):
        return alvo[5:] or None
    return None


def _valor_campo(c, valor) -> str:
    try:
        return formatar(c, valor)
    except (TypeError, ValueError, KeyError, IndexError):
        return str(valor)


def _generico(valor) -> str:
    if isinstance(valor, dict):
        partes = [f"{k.replace('_', ' ')}: {v}" for k, v in valor.items()
                  if k != "id" and not k.endswith("_id") and v not in (None, "", [], {})]
        return ", ".join(partes)
    if valor in (None, "", [], {}):
        return ""
    return str(valor)


def _rotulo_item(chave) -> str:
    from app.implantacao import ITENS      # aqui dentro: evita import circular
    return next((i.rotulo for i in ITENS if i.chave == chave), str(chave or ""))


def _por_acao(item: dict) -> str:
    acao = item["acao"]
    antes = item["antes"] if item["antes"] is not None else None
    depois = item["depois"] if item["depois"] is not None else None
    d = depois if isinstance(depois, dict) else {}
    a = antes if isinstance(antes, dict) else {}

    from app.equipe_canais import ACOES_S4B, detalhe_do_registro  # evita import circular
    if acao in ACOES_S4B:
        return detalhe_do_registro(acao, antes, depois)
    if acao == ACAO_DA_CONFIG:
        alvo = str(item["alvo"] or "")
        chave = alvo[len("config:"):] if alvo.startswith("config:") else alvo
        if chave in ROTULO_CAMPO:
            c = campo(chave)
            return f"{c.rotulo}: {_valor_campo(c, antes)} → {_valor_campo(c, depois)}"
        return f"Ajuste da configuração: {_generico(antes) or 'vazio'} → {_generico(depois) or 'vazio'}"
    if acao == "registrar_venda":
        partes = []
        if d.get("carro"):
            partes.append(str(d["carro"]))
        if d.get("data_venda"):
            partes.append(f"venda em {data_para_tela(d['data_venda'])}")
        if d.get("forma_pagamento") == "financiado" and d.get("meses"):
            partes.append(f"financiado em {d['meses']} meses")
        elif d.get("forma_pagamento"):
            partes.append(FORMAS.get(d["forma_pagamento"], str(d["forma_pagamento"])))
        return ", ".join(partes)
    if acao == "pausar_envios":
        return f"Motivo: {d['motivo']}" if d.get("motivo") else ""
    if acao == "retomar_envios":
        return ""
    if acao == "colocar_no_ar":
        return "Saiu de Em teste e passou a No ar"
    if acao == "criar_loja":
        partes = [str(d[k]) for k in ("nome", "cidade") if d.get(k)]
        return " · ".join(partes + ["começou em teste"])
    if acao in ("marcar_item_implantacao", "desmarcar_item_implantacao"):
        texto = _rotulo_item(d.get("item") or a.get("item"))
        obs = d.get("observacao") if acao == "marcar_item_implantacao" else None
        return f"{texto} · Observação: {obs}" if obs else texto
    if acao == "mensagem_canal_sem_cadastro":
        return f"Canal: {nome_do_canal(d.get('tipo_canal'))}"
    return _generico(depois) or _generico(antes)


def detalhe(item: dict, cliente: str | None = None) -> str:
    partes = [f"Cliente: {cliente}"] if cliente else []
    texto = _por_acao(item)
    if texto:
        partes.append(texto)
    return _cortar(" · ".join(partes)) or VAZIO


# ------------------------------------------------------------ linhas

def linhas_do_registro(itens: list[dict], *, com_loja: bool, agora=None) -> list[dict]:
    """Itens de app/registro_leitura -> linhas prontas para a tabela da tela."""
    lojas: dict = {}

    def _loja_de(loja_id):
        if loja_id is None:
            return _Geral()
        if loja_id not in lojas:
            try:
                lojas[loja_id] = carregar_loja(loja_id)
            except LojaNaoEncontrada:
                lojas[loja_id] = _Geral()
        return lojas[loja_id]

    leads_por_loja: dict = {}
    for i in itens:
        lead = _lead(i.get("alvo"))
        if lead and i.get("loja_id") is not None:
            leads_por_loja.setdefault(i["loja_id"], set()).add(lead)
    nomes = {}
    for loja_id, leads in leads_por_loja.items():
        for lead, nome in nomes_dos_clientes(loja_id, sorted(leads)).items():
            nomes[(loja_id, lead)] = nome

    linhas = []
    for i in itens:
        loja = _loja_de(i.get("loja_id"))
        lead = _lead(i.get("alvo"))
        cliente = nomes.get((i.get("loja_id"), lead)) if lead else None
        linha = {"Quando": horario_para_tela(loja, i["quando"], agora=agora)}
        if com_loja:
            linha["Loja"] = getattr(loja, "nome", SEM_LOJA)
        linha["Quem"] = i["pessoa"] or VAZIO
        linha["Papel"] = ROTULOS_PAPEL.get(i["papel"], VAZIO)
        linha["O quê"] = i["rotulo"]
        linha["Detalhe"] = detalhe(i, cliente)
        linhas.append(linha)
    return linhas
