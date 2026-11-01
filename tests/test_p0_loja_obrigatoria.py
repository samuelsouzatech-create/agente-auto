"""
P0 (Plano Mestre, Fase 1): loja_id obrigatório.

1. As 21 funções de app/ que tinham loja_id=1 como padrão agora exigem a loja.
   Chamar sem loja tem que dar TypeError (nunca cair na loja 1 em silêncio).
2. As tabelas antigas ainda têm "loja_id ... DEFAULT 1" no banco. Este teste
   garante que nenhum INSERT do código omite loja_id, para esse padrão do
   banco nunca ser usado sem querer.
"""
import re
from pathlib import Path

import pytest

from app import estoque, handoff, mensagens, resultados

RAIZ = Path(__file__).resolve().parent.parent
PASTAS = ("app", "tools", "segmentos", "paginas")
TABELAS_COM_PADRAO = ("estoque", "leads", "agendamentos", "handoffs", "mensagens", "resultados")


@pytest.mark.parametrize("chamada", [
    lambda: handoff.estado_do_handoff("5581"),
    lambda: handoff.listar_handoffs(),
    lambda: mensagens.salvar_mensagem("5581", "cliente", "oi"),
    lambda: mensagens.historico_do_lead("5581"),
    lambda: estoque.listar_estoque(),
    lambda: estoque.adicionar_carro("Fiat", "Argo", 2021, 30000, "Prata", "Manual", 62000.0),
    lambda: resultados.registrar_resultado("5581", "comprou"),
    lambda: resultados.listar_resultados(),
], ids=[
    "handoff.estado", "handoff.listar", "mensagens.salvar", "mensagens.historico",
    "estoque.listar", "estoque.adicionar", "resultados.registrar", "resultados.listar",
])
def test_funcao_sem_loja_da_erro(chamada):
    with pytest.raises(TypeError):
        chamada()


_INSERT = re.compile(r"INSERT\s+(?:OR\s+\w+\s+)?INTO\s+(\w+)\s*(\([^)]*\))?", re.IGNORECASE)


def test_nenhum_insert_omite_loja_id():
    problemas = []
    for pasta in PASTAS:
        if not (RAIZ / pasta).is_dir():
            continue
        for arquivo in (RAIZ / pasta).rglob("*.py"):
            texto = arquivo.read_text(encoding="utf-8")
            for achado in _INSERT.finditer(texto):
                tabela, colunas = achado.group(1).lower(), achado.group(2)
                if tabela not in TABELAS_COM_PADRAO:
                    continue
                if not colunas or "loja_id" not in colunas:
                    linha = texto.count("\n", 0, achado.start()) + 1
                    problemas.append(f"{arquivo.relative_to(RAIZ)}:{linha}  INSERT INTO {tabela}")
    assert not problemas, "INSERT sem loja_id (cairia na loja 1):\n" + "\n".join(problemas)
