"""
C2e: exporta a descrição real da API do painel para docs/api/openapi.json.

Uso, na raiz do repositório:
    python -m app.api_painel.exportar

A descrição sai de app.openapi(). Para fora, ela continua desligada
(openapi_url=None em main.py): só este script e os testes a leem.
tests/test_c2e_contrato.py falha se o arquivo commitado ficar diferente da API.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.api_painel.main import criar_app

RAIZ = Path(__file__).resolve().parents[2]
ARQUIVO = RAIZ / "docs" / "api" / "openapi.json"
METODOS = ("get", "post", "put", "patch", "delete")


def descricao_real() -> dict:
    """A descrição como ela fica depois de ir e voltar do JSON (comparável com o arquivo)."""
    return json.loads(json.dumps(criar_app().openapi(), ensure_ascii=False))


def texto() -> str:
    return json.dumps(descricao_real(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def principal() -> None:
    descricao = descricao_real()
    ARQUIVO.write_text(texto(), encoding="utf-8", newline="\n")
    operacoes = sum(1 for ops in descricao["paths"].values() for m in ops if m in METODOS)
    print(f"OK: {ARQUIVO.relative_to(RAIZ).as_posix()} atualizado "
          f"({len(descricao['paths'])} caminhos, {operacoes} operações).")


if __name__ == "__main__":
    principal()
