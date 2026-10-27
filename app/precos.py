"""
Tabela de preços (Etapa 1, Bloco 6 - item 1.9).

Os preços NUNCA ficam no código: cada um tem data de vigência. Mudou o preço,
cadastra-se um novo com a data nova, e o antigo continua valendo para o passado.

Os itens de IA são neutros (não dizem o fornecedor). Trocou o modelo de IA?
Cadastre os preços do modelo novo com a data da troca.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from banco import conectar

MOEDAS = ("USD", "BRL")
POR_MILHAO = 1_000_000

ITENS = {
    "ia.entrada":     {"rotulo": "IA: tokens de entrada (texto)", "unidade": "1 milhão de tokens", "moeda": "USD"},
    "ia.saida":       {"rotulo": "IA: tokens de saída",           "unidade": "1 milhão de tokens", "moeda": "USD"},
    "ia.audio":       {"rotulo": "IA: tokens de áudio (entrada)", "unidade": "1 milhão de tokens", "moeda": "USD"},
    "cambio.usd_brl": {"rotulo": "Cotação do dólar (R$ por US$ 1)", "unidade": "1 dólar", "moeda": "BRL"},
    "meta.servico":   {"rotulo": "WhatsApp: mensagem de serviço",   "unidade": "mensagem", "moeda": "BRL"},
    "meta.utilidade": {"rotulo": "WhatsApp: mensagem de utilidade", "unidade": "mensagem", "moeda": "BRL"},
    "meta.marketing": {"rotulo": "WhatsApp: mensagem de marketing", "unidade": "mensagem", "moeda": "BRL"},
}

# Sem estes, nenhuma resposta do agente tem custo em R$.
ESSENCIAIS = ("ia.entrada", "ia.saida", "cambio.usd_brl")


class PrecoInvalido(ValueError):
    def __init__(self, erros: list[str]):
        self.erros = erros
        super().__init__("; ".join(erros))


def hoje_utc() -> date:
    return datetime.now(timezone.utc).date()


def _data_iso(valor) -> str:
    if isinstance(valor, datetime):
        return valor.date().isoformat()
    if isinstance(valor, date):
        return valor.isoformat()
    texto = str(valor).strip()[:10]
    datetime.strptime(texto, "%Y-%m-%d")      # levanta ValueError se for inválida
    return texto


def cadastrar_preco(item: str, valor, vigente_desde, moeda: str | None = None) -> None:
    """Cadastra (ou corrige, se já existir na mesma data) um preço."""
    erros = []
    if item not in ITENS:
        erros.append(f"Item desconhecido: {item}")
    try:
        valor = float(valor)
        if item == "cambio.usd_brl" and valor <= 0:
            erros.append("Cotação: precisa ser maior que zero")
        elif valor < 0:
            erros.append("Valor: não pode ser negativo")
    except (TypeError, ValueError):
        erros.append("Valor: precisa ser um número")
    if item == "cambio.usd_brl":
        moeda = "BRL"                          # a cotação é sempre em reais
    moeda = moeda or (ITENS[item]["moeda"] if item in ITENS else "BRL")
    if moeda not in MOEDAS:
        erros.append(f"Moeda: use {' ou '.join(MOEDAS)}")
    try:
        dia = _data_iso(vigente_desde)
    except ValueError:
        erros.append("Data: use o formato AAAA-MM-DD")
    if erros:
        raise PrecoInvalido(erros)

    conexao = conectar()
    try:
        conexao.execute(
            """INSERT INTO precos (item, valor, moeda, unidade, vigente_desde)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT (item, vigente_desde)
               DO UPDATE SET valor = excluded.valor, moeda = excluded.moeda,
                             unidade = excluded.unidade""",
            (item, valor, moeda, ITENS[item]["unidade"], dia),
        )
        conexao.commit()
    finally:
        conexao.close()


def preco_vigente(item: str, dia) -> dict | None:
    """O preço que valia naquele dia (o mais recente com vigente_desde <= dia)."""
    conexao = conectar()
    try:
        linha = conexao.execute(
            "SELECT * FROM precos WHERE item = ? AND vigente_desde <= ? "
            "ORDER BY vigente_desde DESC LIMIT 1",
            (item, _data_iso(dia)),
        ).fetchone()
    finally:
        conexao.close()
    return dict(linha) if linha else None


def valor_em_brl(item: str, dia) -> float | None:
    """Preço em reais naquele dia. None se faltar o preço (ou a cotação, se for em dólar)."""
    preco = preco_vigente(item, dia)
    if preco is None:
        return None
    if preco["moeda"] == "BRL":
        return float(preco["valor"])
    cambio = preco_vigente("cambio.usd_brl", dia)
    if cambio is None:
        return None
    return float(preco["valor"]) * float(cambio["valor"])


def faltando(dia=None) -> list[str]:
    """Itens essenciais sem preço vigente no dia (hoje, se não disser)."""
    dia = dia or hoje_utc()
    return [item for item in ESSENCIAIS if preco_vigente(item, dia) is None]


def listar_precos() -> list[dict]:
    conexao = conectar()
    try:
        linhas = conexao.execute(
            "SELECT id, item, valor, moeda, unidade, vigente_desde FROM precos "
            "ORDER BY item, vigente_desde DESC"
        ).fetchall()
    finally:
        conexao.close()
    return [dict(l) for l in linhas]


def apagar_preco(preco_id: int) -> bool:
    conexao = conectar()
    try:
        cursor = conexao.execute("DELETE FROM precos WHERE id = ?", (preco_id,))
        conexao.commit()
        return cursor.rowcount > 0
    finally:
        conexao.close()
