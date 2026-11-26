"""
Do Instagram para o WhatsApp e o "mesmo cliente" (IG3, Maratona 4).

1. Levar para o WhatsApp (padrão da loja, instagram.oferecer_whatsapp):
   - "pedido_ou_vendedor" (padrão): o Léo atende no direct e só oferece o WhatsApp quando o
     cliente pede ou quando chama o vendedor (o chamado foi aberto neste turno);
   - "nunca": não oferece.
   Ele pede o telefone e manda o link wa.me do número da loja (instagram.whatsapp_da_loja).
   É CÓDIGO (não instrução para a IA): a frase é fixa, sem emoji, e o link é o do cadastro.
2. Mesmo cliente: o telefone que o lead do Instagram passou fica gravado (leads.telefone). Quando
   chega no WhatsApp DA MESMA LOJA uma mensagem desse telefone, dentro do prazo
   (instagram.prazo_mesmo_cliente_dias, padrão 7), as duas conversas viram UM cliente
   (clientes_vinculados, migração 21). Nunca entre lojas diferentes.
   SE0 (Maratona Segurança): só junta se o contato do WhatsApp é NOVO nesta loja, ou seja, não
   tem nenhuma mensagem aqui de antes da hora em que o telefone foi dado no Instagram. Se já
   havia conversa (pode ser outra pessoa com esse número, ou um número digitado errado), NÃO
   junta e anota no Registro da loja (uma vez), para a equipe conferir.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import timedelta

from app.chaves import exigir_loja
from app.telefone import formatar_telefone_br, normalizar_telefone_br
from banco import conectar

OFERECER_PADRAO = "pedido_ou_vendedor"
OPCOES_OFERECER = ("pedido_ou_vendedor", "nunca")
PRAZO_PADRAO_DIAS = 7
EVENTO_NAO_JUNTOU = "mesmo_cliente_nao_juntou"

_PEDIU_WHATSAPP = re.compile(r"\b(whats\w*|zap|zapzap|wpp|uats\w*|watsap\w*)\b")
_SEQUENCIA_DE_NUMERO = re.compile(r"(?:\+?\d[\d\s().-]{8,}\d)")


def _sem_acento(texto: str) -> str:
    t = unicodedata.normalize("NFD", str(texto or "")).lower()
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def pediu_whatsapp(texto: str) -> bool:
    return bool(_PEDIU_WHATSAPP.search(_sem_acento(texto)))


def telefone_do_texto(texto: str) -> str:
    """O primeiro celular brasileiro que aparece no texto (normalizado), ou ""."""
    for m in _SEQUENCIA_DE_NUMERO.finditer(str(texto or "")):
        fone = normalizar_telefone_br(m.group(0))
        if fone:
            return fone
    return ""


def link_whatsapp(loja) -> str:
    fone = normalizar_telefone_br(loja.get("instagram.whatsapp_da_loja") or "")
    return f"https://wa.me/{fone}" if fone else ""


def frase_do_whatsapp(loja, texto_do_cliente: str, abriu_chamado: bool, ja_tem_telefone: bool) -> str:
    """A frase que vai junto da resposta do Léo no direct, ou "" (não oferece)."""
    if (loja.get("instagram.oferecer_whatsapp") or OFERECER_PADRAO) == "nunca":
        return ""
    if not (pediu_whatsapp(texto_do_cliente) or abriu_chamado):
        return ""
    link = link_whatsapp(loja)
    if not link:
        return ""
    if ja_tem_telefone:
        return f"Se preferir, a gente continua pelo WhatsApp da loja: {link}"
    return (f"Se preferir continuar pelo WhatsApp, me passa seu telefone com DDD ou chama a gente "
            f"direto no WhatsApp da loja: {link}")


def gravar_telefone(loja_id, lead_id: str, telefone: str) -> bool:
    """O lead do Instagram passou o telefone: grava (e quando). True se gravou."""
    from app.relogio import agora_utc, para_banco
    fone = normalizar_telefone_br(telefone)
    if not fone:
        return False
    loja_id = exigir_loja(loja_id)
    conexao = conectar()
    try:
        conexao.execute(
            "INSERT INTO leads (lead_id, loja_id, telefone, telefone_em) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (loja_id, lead_id) DO UPDATE SET telefone = EXCLUDED.telefone, "
            "telefone_em = EXCLUDED.telefone_em", (lead_id, loja_id, fone, para_banco(agora_utc())))
        conexao.commit()
    finally:
        conexao.close()
    return True


def telefone_do_lead(loja_id, lead_id: str) -> str:
    loja_id = exigir_loja(loja_id)
    conexao = conectar()
    try:
        linha = conexao.execute("SELECT telefone FROM leads WHERE loja_id = ? AND lead_id = ?",
                                (loja_id, lead_id)).fetchone()
    finally:
        conexao.close()
    return (linha["telefone"] or "") if linha else ""


def vincular_mesmo_cliente(loja_id, canal: str, lead_id: str, agora=None) -> str | None:
    """Mensagem chegou no WhatsApp: é o telefone que um lead do Instagram DESTA loja passou, dentro
    do prazo? Junta as duas conversas (uma vez). Devolve o lead principal (o do Instagram) ou None."""
    from app.lojas import carregar_loja
    from app.relogio import agora_utc, para_banco
    if canal != "whatsapp":
        return None
    loja_id = exigir_loja(loja_id)
    fone = normalizar_telefone_br(lead_id)
    if not fone:
        return None
    loja = carregar_loja(loja_id)
    dias = int(loja.get("instagram.prazo_mesmo_cliente_dias") or PRAZO_PADRAO_DIAS)
    desde = para_banco((agora or agora_utc()) - timedelta(days=dias))
    conexao = conectar()
    try:
        ja = conexao.execute("SELECT lead_principal FROM clientes_vinculados WHERE loja_id = ? AND lead_vinculado = ?",
                             (loja_id, str(lead_id))).fetchone()
        if ja:
            return ja["lead_principal"]
        linha = conexao.execute(
            "SELECT lead_id, telefone_em FROM leads WHERE loja_id = ? AND telefone = ? AND lead_id LIKE 'ig:%' "
            "AND telefone_em >= ? ORDER BY telefone_em DESC LIMIT 1", (loja_id, fone, desde)).fetchone()
        if not linha:
            return None
        antiga = conexao.execute(
            "SELECT 1 FROM mensagens WHERE loja_id = ? AND lead_id = ? AND criado_em < ? LIMIT 1",
            (loja_id, str(lead_id), linha["telefone_em"])).fetchone()
        if antiga:
            ja_anotado = conexao.execute(
                "SELECT 1 FROM registro_acoes WHERE loja_id = ? AND acao = ? AND alvo = ? LIMIT 1",
                (loja_id, EVENTO_NAO_JUNTOU, f"whatsapp:{lead_id}")).fetchone()
            if not ja_anotado:
                _anotar_que_nao_juntou(loja_id, str(lead_id), linha["lead_id"])
            return None
        conexao.execute(
            "INSERT INTO clientes_vinculados (loja_id, lead_principal, lead_vinculado, canal_vinculado) "
            "VALUES (?, ?, ?, 'whatsapp') ON CONFLICT (loja_id, lead_vinculado) DO NOTHING",
            (loja_id, linha["lead_id"], str(lead_id)))
        conexao.commit()
    finally:
        conexao.close()
    return linha["lead_id"]


def _anotar_que_nao_juntou(loja_id: int, lead_whatsapp: str, lead_instagram: str) -> None:
    """SE0: o telefone dado no Instagram já tinha conversa no WhatsApp desta loja. Vai para o
    Registro (evento de sistema). Nunca derruba o webhook."""
    try:
        from app.ator import como_sistema
        from app.registro import registrar
        with como_sistema("Sistema", "webhook"):
            registrar(EVENTO_NAO_JUNTOU, loja_id, None,
                      {"motivo": "o WhatsApp já tinha conversa antes do telefone ser dado no Instagram",
                       "conversa_do_instagram": lead_instagram}, alvo=f"whatsapp:{lead_whatsapp}")
    except Exception as erro:
        print(f"[Instagram][loja {loja_id}] Não consegui anotar no Registro: {erro!r}")


def vinculos(loja_id) -> dict[str, str]:
    """lead vinculado -> lead principal, desta loja."""
    loja_id = exigir_loja(loja_id)
    conexao = conectar(somente_leitura=True)
    try:
        linhas = conexao.execute("SELECT lead_vinculado, lead_principal FROM clientes_vinculados WHERE loja_id = ?",
                                 (loja_id,)).fetchall()
    finally:
        conexao.close()
    return {l["lead_vinculado"]: l["lead_principal"] for l in linhas}


def conversas_do_cliente(loja_id, lead_id: str) -> list[str]:
    """Todas as conversas do mesmo cliente nesta loja (a principal primeiro)."""
    mapa = vinculos(loja_id)
    principal = mapa.get(lead_id, lead_id)
    return [principal] + sorted(v for v, p in mapa.items() if p == principal and v != principal)


def telefone_para_tela(lead_id: str) -> str:
    return formatar_telefone_br(lead_id)


ROTULOS_DE_CHEGADA = {"anuncio": "Anúncio", "perfil": "Perfil", "comentario": "Comentário", "direto": "Direto"}


def resumo_dos_clientes(loja_id, leads) -> dict[str, dict]:
    """Para o painel (IG3): lead -> {"canais": ["Instagram", "WhatsApp"], "como_chegou": "Anúncio"|None}.
    Junta as conversas do MESMO cliente (clientes_vinculados) desta loja."""
    from app.apresentacao import nome_do_canal
    loja_id = exigir_loja(loja_id)
    leads = [str(l) for l in leads or []]
    if not leads:
        return {}
    mapa = vinculos(loja_id)
    grupos = {l: conversas_do_cliente(loja_id, l) if (l in mapa or l in mapa.values()) else [l] for l in leads}
    todos = sorted({x for g in grupos.values() for x in g})
    marcas = ",".join("?" * len(todos))
    conexao = conectar(somente_leitura=True)
    try:
        canais = {}
        for l in conexao.execute(f"SELECT lead_id, canal, MAX(id) AS ultimo FROM mensagens WHERE loja_id = ? "
                                 f"AND lead_id IN ({marcas}) GROUP BY lead_id, canal ORDER BY ultimo",
                                 (loja_id, *todos)).fetchall():
            canais.setdefault(l["lead_id"], []).append(l["canal"])
        origens = {l["lead_id"]: l["origem"] for l in conexao.execute(
            f"SELECT lead_id, origem FROM leads WHERE loja_id = ? AND lead_id IN ({marcas})",
            (loja_id, *todos)).fetchall()}
    finally:
        conexao.close()
    saida = {}
    for lead, grupo in grupos.items():
        nomes = []
        for membro in grupo:
            for canal in canais.get(membro, []):
                nome = nome_do_canal(canal)
                if canal and nome not in nomes:
                    nomes.append(nome)
        chegada = next((origens[m] for m in grupo if origens.get(m)), None)
        saida[lead] = {"canais": nomes, "como_chegou": ROTULOS_DE_CHEGADA.get(chegada)}
    return saida


def mensagens_das_outras_conversas(loja_id, lead_id: str, limite: int) -> list[dict]:
    """As mensagens das OUTRAS conversas do mesmo cliente (para o histórico único no painel)."""
    outras = [x for x in conversas_do_cliente(loja_id, lead_id) if x != lead_id]
    if not outras:
        return []
    marcas = ",".join("?" * len(outras))
    conexao = conectar(somente_leitura=True)
    try:
        linhas = conexao.execute(
            f"SELECT id, direcao, tipo, conteudo, canal, autor, criado_em FROM mensagens "
            f"WHERE loja_id = ? AND lead_id IN ({marcas}) ORDER BY id DESC LIMIT ?",
            (exigir_loja(loja_id), *outras, limite)).fetchall()
    finally:
        conexao.close()
    return [dict(l) for l in linhas]
