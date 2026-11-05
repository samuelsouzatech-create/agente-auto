"""
S5 (Fase 3): Ver como a loja.
- Em teste: o operador age (assumir, responder, registrar venda, "Não enviar")
  e a ação fica no Registro com o ator;
- No ar: cada ação é recusada em app/, mesmo chamando a função direto, e nada muda;
- a equipe da loja e os robôs continuam agindo com a loja No ar;
- pausar e retomar funcionam nos dois estados; devolver ao assistente também;
- a lista de testes antigos sem a trava só diminui;
- a tela abre nos dois estados e só mostra os botões quando pode agir.
Tudo offline, banco temporário do conftest (ator "Teste", operador, painel).
A loja 1 está No ar (migração 11); a loja criada aqui nasce Em teste.
"""
import ast
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from banco import conectar
from app import bloqueios, envio_painel, pausa, vendas
from app.ator import AtorInvalido, SemAtor, como, como_sistema, sem_ator
from app.chaves import LojaNaoInformada
from app.envio_painel import enviar_pelo_painel
from app.estado_loja import esta_no_ar
from app.handoff import assumir_conversa, assumir_handoff, devolver_ao_agente, estado_do_handoff
from app.lojas import criar_loja
from app.mensagens import historico_do_lead, salvar_mensagem
from app.permissoes import AcaoNaoPermitida, exigir_pode_agir, operador_pode_agir
from app.ver_como import conversas_para_atender

RAIZ = Path(__file__).resolve().parent.parent
TELA = RAIZ / "paginas" / "operador" / "ver_como.py"
LEAD = "5581999990000"
HOJE = date(2026, 11, 4)
AGORA = datetime(2026, 11, 4, 15, 0, tzinfo=timezone.utc)      # 12h no Recife

ANTES_DO_S5_ORIGINAL = {
    "test_etapa1_bloco3.py", "test_etapa1_bloco4.py", "test_etapa1_bloco7.py",
    "test_etapa1_bloco7b.py", "test_etapa2_bloco5.py", "test_fase_3_handoff.py",
    "test_p2_venda_unica.py", "test_p4_painel_leitura.py", "test_p5_bloqueios.py",
    "test_p6b_acoes.py", "test_p6c_handoff_config.py", "test_p6d_leitura.py",
    "test_revisao_etapa1.py", "test_s3_registro.py", "test_separar_painel.py",
}


def _um(sql, parametros=()):
    conexao = conectar()
    try:
        return conexao.execute(sql, parametros).fetchone()[0]
    finally:
        conexao.close()


def _sql(sql, parametros=()):
    conexao = conectar()
    try:
        novo = conexao.execute(sql, parametros).lastrowid
        conexao.commit()
        return novo
    finally:
        conexao.close()


def _carro(loja_id):
    return _sql("INSERT INTO estoque (loja_id, marca, modelo, ano, km, cor, cambio, preco, status) "
                "VALUES (?, 'Hyundai', 'HB20', 2020, 40000, 'Prata', 'Manual', 60000, 'disponivel')",
                (loja_id,))


def _handoff(loja_id, estado, vendedor=None, lead_id=LEAD):
    _sql("INSERT INTO handoffs (loja_id, lead_id, motivo, resumo, estado, vendedor) "
         "VALUES (?, ?, 'teste', '', ?, ?)", (loja_id, lead_id, estado, vendedor))


@pytest.fixture(autouse=True)
def envio_falso(monkeypatch):
    """Nada sai de verdade: o despacho do painel vira uma lista."""
    enviados = []

    async def falso(loja_id, canal, lead_id, texto):
        enviados.append((loja_id, canal, lead_id, texto))
        return True
    monkeypatch.setattr(envio_painel, "_despachar", falso)
    return enviados


@pytest.fixture
def loja_teste():
    loja = criar_loja("Loja Em Teste")
    assert not esta_no_ar(loja)
    return loja


# ação -> (preparar(loja), executar(loja, preparado), consulta que conta o efeito na loja)
ACOES = {
    "assumir_conversa": (
        lambda l: None,
        lambda l, p: assumir_conversa(LEAD, "Teste", l),
        "SELECT COUNT(*) FROM handoffs WHERE loja_id = ? AND estado = 'humano_assumiu'"),
    "assumir_handoff": (
        lambda l: _handoff(l, "aguardando_humano"),
        lambda l, p: assumir_handoff(LEAD, "Teste", l),
        "SELECT COUNT(*) FROM handoffs WHERE loja_id = ? AND estado = 'humano_assumiu'"),
    "enviar_pelo_painel": (
        lambda l: _handoff(l, "humano_assumiu", "Teste"),
        lambda l, p: enviar_pelo_painel(l, "telegram", LEAD, "Oi, aqui é da loja.", "Teste"),
        "SELECT COUNT(*) FROM mensagens WHERE loja_id = ? AND direcao = 'vendedor'"),
    "registrar_venda": (
        lambda l: _carro(l),
        lambda l, p: vendas.registrar_venda(l, LEAD, p, HOJE, "avista",
                                            vendedor="Teste", agora=AGORA),
        "SELECT COUNT(*) FROM vendas WHERE loja_id = ?"),
    "bloquear": (
        lambda l: None,
        lambda l, p: bloqueios.bloquear(l, LEAD, "todos", None, "Teste"),
        "SELECT COUNT(*) FROM bloqueios_envio WHERE loja_id = ?"),
}

# nome da ação no Registro (o envio pelo painel grava a mensagem com o autor)
NO_REGISTRO = {"assumir_conversa": "assumir_conversa", "assumir_handoff": "assumir_atendimento",
               "registrar_venda": "registrar_venda", "bloquear": "bloquear_envio",
               "enviar_pelo_painel": None}


# ------------------------------------------------------------ em teste: age

@pytest.mark.parametrize("acao", sorted(ACOES))
def test_em_teste_o_operador_age_e_fica_registrado(acao, loja_teste):
    preparar, executar, efeito = ACOES[acao]
    preparado = preparar(loja_teste)
    antes = _um(efeito, (loja_teste,))
    executar(loja_teste, preparado)
    assert _um(efeito, (loja_teste,)) == antes + 1
    nome = NO_REGISTRO[acao]
    if nome is None:
        ultima = historico_do_lead(LEAD, loja_teste)[-1]
        assert (ultima["direcao"], ultima["autor"]) == ("vendedor", "Teste")
        return
    conexao = conectar()
    try:
        linha = conexao.execute(
            "SELECT pessoa, papel, loja_id FROM registro_acoes WHERE acao = ? ORDER BY id DESC",
            (nome,)).fetchone()
    finally:
        conexao.close()
    assert tuple(linha) == ("Teste", "operador", loja_teste)


# ------------------------------------------------------------ no ar: recusa em app/

@pytest.mark.parametrize("acao", sorted(ACOES))
def test_no_ar_cada_acao_e_recusada_chamando_direto(acao):
    assert esta_no_ar(1)
    preparar, executar, efeito = ACOES[acao]
    preparado = preparar(1)
    antes = _um(efeito, (1,))
    antes_registro = _um("SELECT COUNT(*) FROM registro_acoes")
    with pytest.raises(AcaoNaoPermitida):
        executar(1, preparado)
    assert _um(efeito, (1,)) == antes
    assert _um("SELECT COUNT(*) FROM registro_acoes") == antes_registro


def test_no_ar_nada_sai_pelo_painel(envio_falso):
    _handoff(1, "humano_assumiu", "Teste")
    with pytest.raises(AcaoNaoPermitida):
        enviar_pelo_painel(1, "telegram", LEAD, "oi", "Teste")
    assert envio_falso == []


def test_a_equipe_da_loja_continua_agindo_no_ar():
    with como("Ana", "cliente", "painel", loja_id=1):
        assert assumir_conversa(LEAD, "Ana", 1) == "Lead assumido por Ana."
        bloqueios.bloquear(1, LEAD, "todos", None, "Ana")
    assert estado_do_handoff(LEAD, 1) == "humano_assumiu"


def test_robos_nao_sao_travados():
    with como_sistema("Relógio", "job"):
        assert exigir_pode_agir(1).papel == "sistema"


def test_sem_ator_outra_loja_e_sem_loja(loja_teste):
    with sem_ator(), pytest.raises(SemAtor):
        exigir_pode_agir(loja_teste)
    with como("Ana", "cliente", "painel", loja_id=1), pytest.raises(AtorInvalido):
        exigir_pode_agir(loja_teste)
    with pytest.raises(LojaNaoInformada):
        exigir_pode_agir(None)


def test_operador_pode_agir_segue_o_estado(loja_teste):
    assert operador_pode_agir(loja_teste) is True
    assert operador_pode_agir(1) is False


# ------------------------------------------------------------ sempre liberados

@pytest.mark.parametrize("no_ar", [True, False])
def test_pausar_e_retomar_nos_dois_estados(no_ar, loja_teste):
    loja = 1 if no_ar else loja_teste
    assert esta_no_ar(loja) is no_ar
    pausa.pausar(loja, usuario="Teste", papel="operador", motivo="teste")
    assert pausa.pausado(loja)
    pausa.retomar(loja, usuario="Teste", papel="operador")
    assert not pausa.pausado(loja)


def test_devolver_ao_assistente_continua_liberado_no_ar():
    _handoff(1, "humano_assumiu", "Teste")
    assert devolver_ao_agente(LEAD, 1) == "Lead devolvido ao agente."
    assert estado_do_handoff(LEAD, 1) == "ativo"


# ------------------------------------------------------------ leitura do Atender

def test_atender_poe_quem_espera_primeiro_e_separa_lojas(loja_teste):
    salvar_mensagem("A", "cliente", "oi", canal="telegram", loja_id=loja_teste)
    salvar_mensagem("B", "cliente", "oi", canal="telegram", loja_id=loja_teste)
    salvar_mensagem("C", "cliente", "de outra loja", canal="telegram", loja_id=1)
    _handoff(loja_teste, "aguardando_humano", lead_id="A")
    lista = conversas_para_atender(loja_teste)
    assert [c["lead_id"] for c in lista] == ["A", "B"]
    assert lista[0]["estado"] == "aguardando_humano"
    assert "C" not in {c["lead_id"] for c in lista}


# ------------------------------------------------------------ catraca da lista antiga

def _lista_do_conftest() -> set:
    arvore = ast.parse((RAIZ / "tests" / "conftest.py").read_text(encoding="utf-8"))
    for no in ast.walk(arvore):
        if isinstance(no, ast.Assign) and any(
                getattr(a, "id", "") == "ANTES_DO_S5" for a in no.targets):
            return set(ast.literal_eval(no.value))
    raise AssertionError("ANTES_DO_S5 sumiu do conftest.py")


def test_lista_dos_antigos_so_diminui():
    lista = _lista_do_conftest()
    assert lista <= ANTES_DO_S5_ORIGINAL, lista - ANTES_DO_S5_ORIGINAL
    assert "test_s5_ver_como.py" not in lista


def test_arquivos_da_lista_existem():
    for nome in _lista_do_conftest():
        assert (RAIZ / "tests" / nome).is_file(), nome


# ------------------------------------------------------------ tela

def _abrir(loja, monkeypatch):
    monkeypatch.setenv("OPERADOR_NOME", "Teste")
    at = AppTest.from_file(str(TELA), default_timeout=30)
    at.session_state["_papel"] = "operador"
    at.session_state["loja_id"] = loja
    return at.run()


def test_tela_em_teste_mostra_faixa_e_botoes(loja_teste, monkeypatch):
    salvar_mensagem(LEAD, "cliente", "oi", canal="telegram", loja_id=loja_teste)
    at = _abrir(loja_teste, monkeypatch)
    assert not at.exception, at.exception
    assert any("você pode agir" in w.value for w in at.warning)
    rotulos = [b.label for b in at.button]
    assert "✋ Assumir conversa" in rotulos and "⏸️ Pausar os envios" in rotulos


def test_tela_no_ar_so_le_mas_pausa(monkeypatch):
    salvar_mensagem(LEAD, "cliente", "oi", canal="telegram", loja_id=1)
    at = _abrir(1, monkeypatch)
    assert not at.exception, at.exception
    assert any("só para ver" in i.value for i in at.info)
    rotulos = [b.label for b in at.button]
    assert "✋ Assumir conversa" not in rotulos
    assert "⏸️ Pausar os envios" in rotulos


def test_tela_pausa_com_a_loja_no_ar(monkeypatch):
    at = _abrir(1, monkeypatch)
    at.button(key="vc_pausar").click().run()
    assert not at.exception, at.exception
    assert pausa.pausado(1)


def test_tela_nao_fala_com_o_banco():
    usados = TELA.read_text(encoding="utf-8")
    assert "import banco" not in usados and "conectar(" not in usados
