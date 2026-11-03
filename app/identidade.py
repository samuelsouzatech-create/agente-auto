"""
Quem está usando o painel (P6d): o nome vem do .env, não de um campo na tela.

- Painel do operador: OPERADOR_NOME (obrigatório). Sem ele, a tela não abre.
- Painel da loja: PAINEL_NOME (se faltar, "Equipe da loja").

Sem Streamlit, para dar para testar (igual ao app/acesso.py). O P8 troca
isto por usuários de verdade (vendedor, gestor, dono, suporte).
"""
import os

from app import config as _config  # noqa: F401  (carrega o .env)
from app.ator import MAX_PESSOA

VARIAVEL_OPERADOR = "OPERADOR_NOME"
VARIAVEL_PAINEL = "PAINEL_NOME"
PADRAO_PAINEL = "Equipe da loja"


class SemNomeOperador(RuntimeError):
    """O painel do operador não sabe quem está usando: ele não abre."""


def _limpo(bruto) -> str:
    return " ".join(str(bruto or "").split())


def nome_do_operador(ambiente=None) -> str:
    ambiente = os.environ if ambiente is None else ambiente
    nome = _limpo(ambiente.get(VARIAVEL_OPERADOR))
    if not nome:
        raise SemNomeOperador(
            "Falta o seu nome no .env. Abra o arquivo .env, coloque uma linha "
            "OPERADOR_NOME=Samuel e abra o painel de novo.")
    if len(nome) > MAX_PESSOA:
        raise SemNomeOperador(f"OPERADOR_NOME com mais de {MAX_PESSOA} caracteres.")
    return nome


def nome_do_painel(ambiente=None) -> str:
    ambiente = os.environ if ambiente is None else ambiente
    nome = _limpo(ambiente.get(VARIAVEL_PAINEL)) or PADRAO_PAINEL
    return nome[:MAX_PESSOA]
