"""
Ferramenta do Léo: o carro que o cliente quer dar na troca.

Bloco S3 (furo 8):
- A troca do mesmo cliente, na mesma loja, é ATUALIZADA, não duplicada.
  Mesmo carro = mesmo modelo (sem diferença de maiúscula e acento) e mesmo
  ano. Ano desconhecido (0) combina com qualquer ano e é completado depois.
- Km 0 ou ausente = "não informado" (vazio no banco), nunca 0 de verdade.
  Km vazio nunca apaga um km já conhecido. Estado vazio também não apaga.
- Carros diferentes do mesmo cliente continuam como trocas separadas.
- loja_id vem sempre do código (InjectedToolArg), sem valor padrão.
"""
import unicodedata
from typing import Annotated

from langchain_core.tools import tool, InjectedToolArg

from banco import conectar


def _normal(texto) -> str:
    t = unicodedata.normalize("NFD", str(texto or "")).lower()
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return " ".join(t.split())


def _ou_nada(numero):
    """Número positivo, ou None (0, vazio ou texto = não informado)."""
    try:
        n = int(numero)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def gravar_troca(loja_id, lead_id, modelo, ano, km, estado) -> dict:
    """Grava ou atualiza a troca. Devolve o que ficou gravado."""
    modelo = str(modelo or "").strip()
    ano, km = _ou_nada(ano), _ou_nada(km)
    estado = str(estado or "").strip()
    conexao = conectar()
    try:
        alvo = None
        if lead_id:
            linhas = conexao.execute(
                "SELECT id, modelo, ano, km, estado FROM trocas "
                "WHERE loja_id = ? AND lead_id = ? ORDER BY id DESC", (loja_id, lead_id)).fetchall()
            for linha in linhas:
                mesmo_modelo = _normal(linha["modelo"]) == _normal(modelo)
                mesmo_ano = ano is None or not linha["ano"] or linha["ano"] == ano
                if mesmo_modelo and mesmo_ano:
                    alvo = linha
                    break
        if alvo:
            ano = ano or _ou_nada(alvo["ano"])
            km = km or _ou_nada(alvo["km"])
            estado = estado or (alvo["estado"] or "")
            modelo = modelo or (alvo["modelo"] or "")
            conexao.execute("UPDATE trocas SET modelo = ?, ano = ?, km = ?, estado = ? WHERE id = ?",
                            (modelo, ano, km, estado, alvo["id"]))
        else:
            conexao.execute(
                "INSERT INTO trocas (loja_id, lead_id, modelo, ano, km, estado) VALUES (?, ?, ?, ?, ?, ?)",
                (loja_id, lead_id, modelo, ano, km, estado))
        conexao.commit()
    finally:
        conexao.close()
    return {"modelo": modelo, "ano": ano, "km": km, "estado": estado, "atualizada": alvo is not None}


def texto_km(km) -> str:
    km = _ou_nada(km)
    return f"{km:,} km".replace(",", ".") if km else "km não informado"


@tool
def registrar_troca(modelo: str, ano: int, km: int, estado: str,
                    lead_id: Annotated[str, InjectedToolArg] = "",
                    *, loja_id: Annotated[int, InjectedToolArg]) -> str:
    """Registra o carro que o cliente quer dar na troca. NÃO dê valor de
    avaliação - isso é feito por um vendedor presencialmente. Apenas colete
    e confirme os dados. Pode chamar de novo quando souber mais (por exemplo,
    a quilometragem): a troca é atualizada, não duplicada.

    Parâmetros:
    - modelo: ex. "Gol 1.0"
    - ano: ano do carro (0 se o cliente ainda não disse)
    - km: quilometragem (0 se o cliente ainda não disse)
    - estado: descrição geral informada pelo cliente
    """
    g = gravar_troca(loja_id, lead_id, modelo, ano, km, estado)
    verbo = "atualizada" if g["atualizada"] else "registrada"
    ano_txt = f" {g['ano']}" if g["ano"] else ""
    return (
        f"Troca {verbo}: {g['modelo']}{ano_txt}, {texto_km(g['km'])}, "
        f"estado: {g['estado'] or 'não informado'}. "
        "A avaliação com valor é feita presencialmente por um vendedor."
    )
