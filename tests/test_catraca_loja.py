"""
Catraca do loja_id (validação final da Etapa 1).

Risco apontado pelo analista: funções com `loja_id=1` como padrão. Se um
código novo (ex.: job de remarketing) esquecer o argumento, lê ou grava na
loja 1 em silêncio.

Regra a partir daqui:
- Código NOVO: loja_id obrigatório, sem valor padrão. Este teste reprova.
- Código ANTIGO: fica na lista LEGADO até ser corrigido. A lista só pode
  diminuir: quando uma função perde o padrão, o segundo teste pede para
  apagá-la daqui.
"""
import ast
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PASTAS = ("app", "tools", "paginas")
ARQUIVOS_SOLTOS = ("banco.py",)

LEGADO = {
    # app/mensagens.py
    "app/mensagens.py:salvar_mensagem",
    "app/mensagens.py:historico_do_lead",
    "app/mensagens.py:listar_leads",
    "app/mensagens.py:listar_conversas",
    "app/mensagens.py:ja_respondeu",
    "app/mensagens.py:mensagens_desde_a_ultima_resposta_do_leo",
    # app/handoff.py
    "app/handoff.py:estado_do_handoff",
    "app/handoff.py:quem_assumiu",
    "app/handoff.py:assumir_handoff",
    "app/handoff.py:assumir_conversa",
    "app/handoff.py:devolver_ao_agente",
    "app/handoff.py:encerrar_handoff",
    "app/handoff.py:listar_handoffs",
    # app/estoque.py
    "app/estoque.py:listar_estoque",
    "app/estoque.py:buscar_carro",
    "app/estoque.py:adicionar_carro",
    "app/estoque.py:atualizar_carro",
    "app/estoque.py:marcar_status",
    # app/resultados.py
    "app/resultados.py:registrar_resultado",
    "app/resultados.py:resultado_do_lead",
    "app/resultados.py:listar_resultados",
    # tools/ (loja_id injetado pelo código, nunca vem da IA)
    "tools/acionar_handoff.py:acionar_handoff",
    "tools/agendar_visita.py:agendar_visita",
    "tools/buscar_conhecimento.py:buscar_conhecimento",
    "tools/consultar_estoque.py:consultar_estoque",
    "tools/detalhes_veiculo.py:detalhes_veiculo",
    "tools/enviar_fotos.py:enviar_fotos",
    "tools/registrar_interesse.py:registrar_interesse",
    "tools/registrar_lead.py:registrar_lead",
    "tools/registrar_troca.py:registrar_troca",
    "tools/simular_financiamento.py:simular_financiamento",
}


def _arquivos():
    for pasta in PASTAS:
        yield from sorted((RAIZ / pasta).rglob("*.py"))
    for nome in ARQUIVOS_SOLTOS:
        caminho = RAIZ / nome
        if caminho.exists():
            yield caminho


def _padrao_perigoso(no) -> bool:
    """loja_id=1, loja_id=LOJA_PADRAO ou parecido. (None não cai na loja 1.)"""
    if isinstance(no, ast.Constant):
        return isinstance(no.value, int) and not isinstance(no.value, bool)
    return isinstance(no, (ast.Name, ast.Attribute))


def _funcoes_com_loja_padrao() -> set:
    achadas = set()
    for caminho in _arquivos():
        arvore = ast.parse(caminho.read_text(encoding="utf-8"))
        relativo = caminho.relative_to(RAIZ).as_posix()
        for no in ast.walk(arvore):
            if not isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            a = no.args
            posicionais = a.posonlyargs + a.args
            pares = list(zip(posicionais[len(posicionais) - len(a.defaults):], a.defaults))
            pares += [(arg, d) for arg, d in zip(a.kwonlyargs, a.kw_defaults) if d is not None]
            if any(arg.arg == "loja_id" and _padrao_perigoso(d) for arg, d in pares):
                achadas.add(f"{relativo}:{no.name}")
    return achadas


def test_nenhuma_funcao_nova_com_loja_padrao():
    novas = sorted(_funcoes_com_loja_padrao() - LEGADO)
    assert not novas, (
        "Função com loja_id padrão (risco de cair na loja 1 em silêncio).\n"
        "Se for código NOVO: tire o padrão.\n"
        "Se for código ANTIGO (já existia antes desta catraca), copie para o LEGADO:\n"
        + "\n".join(f'    "{n}",' for n in novas)
    )


def test_legado_so_diminui():
    corrigidas = sorted(LEGADO - _funcoes_com_loja_padrao())
    assert not corrigidas, (
        "Estas funções já não têm padrão (ótimo!). Apague-as do LEGADO:\n"
        + "\n".join(f'    "{n}",' for n in corrigidas)
    )
