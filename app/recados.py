"""
L3/L4 (Fase Cérebro): a equipe da loja fala com o Léo e deixa recados.

- Quem escreve é da equipe? (membro_da_equipe): número/Telegram cadastrado em
  `usuarios` (papel dono, gestor ou vendedor), sempre da MESMA loja.
- Recado: texto do dono ou gestor com validade (último dia, no fuso da loja).
  Sem validade dita: 7 dias. Nada é apagado: quem sai é desativado.
- Recado com condição comercial (preço, desconto, entrada, taxa, parcela, IPVA,
  brinde) nunca vira promessa: o Léo diz que a campanha existe e chama o vendedor.
Toda função recebe loja_id: a loja A nunca enxerga recado nem equipe da B.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date, timedelta

from app.chaves import exigir_loja
from app.telefone import normalizar_telefone_br
from banco import conectar

PAPEIS_DO_RECADO = ("dono", "gestor")
DIAS_PADRAO = 7
LIMITE_DIAS = 180
MAX_TEXTO = 300
DIAS_CURTOS = ("segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo")

MENSAGEM_SO_DONO = ("Oi! Por aqui eu só anoto recados do dono ou do gestor da loja. "
                    "Se tiver um aviso para os clientes, peça para um deles me mandar.")
MENSAGEM_SO_RECADOS = "Por aqui eu só anoto recados; os números ficam no painel."

_CONDICAO = re.compile(
    r"\b(preco|precos|valor|r\$|desconto|descontos|abatimento|entrada|taxa|taxas|juros|"
    r"parcela|parcelas|parcelamento|ipva|brinde|brindes|bonus|emplacamento|cashback|"
    r"gratis|gratuito|gratuita|sem juros|garantia)\b"
    r"|r\$|\d+\s*%|\d+\s*mil\b")


class RecadoInvalido(ValueError):
    pass


def _sem_acento(texto) -> str:
    sem = unicodedata.normalize("NFD", str(texto or ""))
    return "".join(c for c in sem if unicodedata.category(c) != "Mn").lower()


# ---------------------------------------------------------------- equipe

def membro_da_equipe(loja_id: int, canal: str, remetente: str) -> dict | None:
    """Pessoa ativa da equipe DESTA loja que tem este contato, ou None (cliente).
    WhatsApp e simulador comparam o celular normalizado; Telegram, o id do chat."""
    loja_id = exigir_loja(loja_id)
    remetente = str(remetente or "").strip()
    if not remetente:
        return None
    if canal == "telegram":
        coluna, chave = "contato_telegram", remetente
    elif canal in ("whatsapp", "simulador"):
        coluna, chave = "contato_whatsapp", normalizar_telefone_br(remetente)
    else:
        return None
    if not chave:
        return None
    conexao = conectar()
    try:
        linhas = conexao.execute(
            f"SELECT id, nome, papel, {coluna} AS contato FROM usuarios "
            "WHERE loja_id = ? AND ativo = 1 AND papel IN ('dono','gestor','vendedor') "
            f"AND {coluna} IS NOT NULL AND {coluna} != ''", (loja_id,)).fetchall()
    finally:
        conexao.close()
    for linha in linhas:
        contato = (normalizar_telefone_br(linha["contato"]) if coluna == "contato_whatsapp"
                   else str(linha["contato"]).strip())
        if contato == chave:
            return {"id": linha["id"], "nome": linha["nome"], "papel": linha["papel"]}
    return None


def pode_deixar_recado(membro: dict | None) -> bool:
    return bool(membro) and membro.get("papel") in PAPEIS_DO_RECADO


# ---------------------------------------------------------------- recados

def tem_condicao_comercial(texto: str) -> bool:
    return bool(_CONDICAO.search(_sem_acento(texto)))


def termos_da_condicao(texto: str) -> set[str]:
    """Palavras de condição comercial do recado (a bancada usa para pegar repetição)."""
    return {m.group(0).strip() for m in _CONDICAO.finditer(_sem_acento(texto))}


def _validade(valido_ate, hoje: date) -> tuple[date, bool]:
    """(último dia, foi_padrao). Vazio = 7 dias."""
    if valido_ate in (None, ""):
        return hoje + timedelta(days=DIAS_PADRAO), True
    if isinstance(valido_ate, date):
        dia = valido_ate
    else:
        try:
            dia = date.fromisoformat(str(valido_ate).strip()[:10])
        except ValueError:
            raise RecadoInvalido("a validade precisa ser uma data no formato AAAA-MM-DD")
    if dia < hoje:
        raise RecadoInvalido("essa data já passou")
    if dia > hoje + timedelta(days=LIMITE_DIAS):
        raise RecadoInvalido(f"a validade passa de {LIMITE_DIAS} dias")
    return dia, False


def registrar_recado(loja_id: int, autor: str, texto: str, valido_ate, *, hoje: date) -> dict:
    loja_id = exigir_loja(loja_id)
    texto = " ".join(str(texto or "").split()).rstrip(".!")
    if not texto:
        raise RecadoInvalido("o recado está vazio")
    if len(texto) > MAX_TEXTO:
        raise RecadoInvalido(f"o recado passa de {MAX_TEXTO} letras")
    dia, padrao = _validade(valido_ate, hoje)
    autor = (str(autor or "").strip() or "Equipe")[:80]
    conexao = conectar()
    try:
        cursor = conexao.execute(
            "INSERT INTO recados (loja_id, autor, texto, valido_ate) VALUES (?, ?, ?, ?)",
            (loja_id, autor, texto, dia.isoformat()))
        conexao.commit()
        recado_id = cursor.lastrowid
    finally:
        conexao.close()
    return {"id": recado_id, "texto": texto, "valido_ate": dia, "padrao": padrao,
            "condicao": tem_condicao_comercial(texto)}


def _dia_curto(dia: date) -> str:
    return f"{DIAS_CURTOS[dia.weekday()]} {dia.strftime('%d/%m')}"


def confirmacao(recado: dict) -> str:
    """O que o Léo responde ao dono depois de gravar (repete recado e validade)."""
    partes = [f"Anotado: {recado['texto']}.",
              f"Vou comentar com os clientes até {_dia_curto(recado['valido_ate'])}."]
    if recado["padrao"]:
        partes.append(f"Você não disse até quando vale, então deixei por {DIAS_PADRAO} dias.")
    if recado["condicao"]:
        partes.append("Como tem condição comercial, aos clientes eu só conto que a campanha "
                      "existe e chamo um vendedor para confirmar as condições.")
    partes.append("Se estiver errado, me diga.")
    return " ".join(partes)


def _linhas(sql: str, parametros) -> list[dict]:
    conexao = conectar()
    try:
        return [dict(l) for l in conexao.execute(sql, parametros).fetchall()]
    finally:
        conexao.close()


def recados_ativos(loja_id: int, hoje: date) -> list[dict]:
    """Ativos e dentro da validade (o último dia ainda vale)."""
    loja_id = exigir_loja(loja_id)
    linhas = _linhas("SELECT id, autor, texto, valido_ate FROM recados "
                     "WHERE loja_id = ? AND ativo = 1 AND valido_ate >= ? ORDER BY id",
                     (loja_id, hoje.isoformat()))
    for l in linhas:
        l["valido_ate"] = date.fromisoformat(l["valido_ate"])
        l["condicao"] = tem_condicao_comercial(l["texto"])
    return linhas


ATIVO, VENCIDO, DESATIVADO = "Ativo", "Vencido", "Desativado"


def listar_recados(loja_id: int, hoje: date) -> list[dict]:
    """Todos os recados da loja (mais novo primeiro), prontos para o painel:
    situacao (Ativo, Vencido ou Desativado), validade "dd/mm" e se pode desativar."""
    loja_id = exigir_loja(loja_id)
    linhas = _linhas("SELECT id, autor, texto, valido_ate, ativo, criado_em FROM recados "
                     "WHERE loja_id = ? ORDER BY id DESC", (loja_id,))
    for l in linhas:
        dia = date.fromisoformat(l["valido_ate"])
        l["situacao"] = DESATIVADO if not l["ativo"] else (VENCIDO if dia < hoje else ATIVO)
        l["validade"] = dia.strftime("%d/%m")
        l["pode_desativar"] = l["situacao"] == ATIVO
    return linhas


def desativar_recado(loja_id: int, recado_id: int) -> bool:
    """Desativa só recado desta loja e anota no Registro (exige ator, como a equipe).
    Devolve False se não achou ou se já estava desativado."""
    from app.registro import conferir_ator, registrar   # aqui dentro: evita import circular
    loja_id = exigir_loja(loja_id)
    conferir_ator(loja_id)
    conexao = conectar()
    try:
        linha = conexao.execute("SELECT texto, valido_ate FROM recados "
                                "WHERE id = ? AND loja_id = ? AND ativo = 1",
                                (int(recado_id), loja_id)).fetchone()
        if linha is None:
            return False
        conexao.execute("UPDATE recados SET ativo = 0 WHERE id = ? AND loja_id = ?",
                        (int(recado_id), loja_id))
        registrar("desativar_recado", loja_id, {"ativo": True},
                  {"ativo": False, "texto": linha["texto"], "valido_ate": linha["valido_ate"]},
                  conexao=conexao, alvo=f"recado:{int(recado_id)}")
        conexao.commit()
        return True
    finally:
        conexao.close()


def camada_dos_recados(recados: list[dict]) -> str:
    """O trecho do prompt do atendimento ao cliente. Sem recado: nada."""
    if not recados:
        return ""
    linhas = ["RECADOS DA LOJA (deixados pelo dono ou gestor; cada um vale até a data indicada)"]
    tem_condicao = False
    for r in recados:
        marca = " [CONDIÇÃO COMERCIAL]" if r["condicao"] else ""
        tem_condicao = tem_condicao or r["condicao"]
        linhas.append(f"- {r['texto']} (vale até {r['valido_ate'].strftime('%d/%m')}){marca}")
    linhas.append("- Comente o recado quando o cliente perguntar de promoção, feirão ou novidade, "
                  "ou quando estiver indeciso. Use só o que está escrito: não invente data, "
                  "horário, brinde nem detalhe. Só diga até quando o recado vale se o cliente "
                  "perguntar até quando vale.")
    if tem_condicao:
        linhas.append("- Recado com [CONDIÇÃO COMERCIAL]: diga só que a campanha existe (ex.: "
                      "\"tem um feirão no sábado\"). NÃO repita nem confirme a condição (preço, "
                      "desconto, entrada, taxa, parcela, IPVA, brinde). Se o cliente perguntar "
                      "da condição, chame acionar_handoff e diga que um vendedor confirma.")
    return "\n".join(linhas)
