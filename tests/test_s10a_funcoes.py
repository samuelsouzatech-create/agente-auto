"""
S10a (Fase 3): o que só existia nas telas antigas ganha lugar no painel novo,
ANTES de qualquer tela ser removida (S10b).
- todo campo da configuração aparece em exatamente um lugar do painel novo;
- Mensagens automáticas: Resultado e histórico, Base da loja e Regras;
- Ver como a loja: Desfazer o "Não enviar" (só quando pode agir);
- Configuração: Outros ajustes e o nome da loja;
- duas lojas não se misturam; as telas não falam com o banco.
Os testes do P5 e do P7 NÃO mudam neste passo (condição do analista).
Tudo offline, banco temporário do conftest.
"""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from app import bloqueios
from app.ator import como
from app.config_tela import (
    ASSUNTOS_COM_CAMPOS, CAMPOS, OUTROS_AJUSTES, REGRAS_DAS_MENSAGENS,
    campos_das_regras, campos_de_outros_ajustes, campos_do_assunto,
)
from app.lojas import carregar_loja, criar_loja
from app.lojas_admin import listar_lojas

RAIZ = Path(__file__).resolve().parent.parent
MENSAGENS = RAIZ / "paginas" / "operador" / "mensagens_automaticas.py"
CONFIG = RAIZ / "paginas" / "operador" / "configuracao.py"
VER_COMO = RAIZ / "paginas" / "operador" / "ver_como.py"
LEAD = "5581999990000"


def _abrir(tela, loja, monkeypatch):
    monkeypatch.setenv("OPERADOR_NOME", "Teste")
    at = AppTest.from_file(str(tela), default_timeout=30)
    at.session_state["_papel"] = "operador"
    at.session_state["loja_id"] = loja
    return at.run()


def _botao(at, rotulo):
    return next(b for b in at.button if str(b.label) == rotulo)


def _rotulos(at):
    return [str(b.label) for b in at.button]


@pytest.fixture
def loja():
    return criar_loja("Loja S10a")


@pytest.fixture
def outra():
    return criar_loja("Outra loja S10a")


# ------------------------------------------------------------ mapa

def test_todo_campo_aparece_em_um_lugar_so():
    lugares = [c.chave for a in ASSUNTOS_COM_CAMPOS for c in campos_do_assunto(a)]
    lugares += [c.chave for c in campos_das_regras()]
    lugares += [c.chave for c in campos_de_outros_ajustes()]
    assert len(lugares) == len(set(lugares))
    assert set(lugares) == {c.chave for c in CAMPOS}


def test_regras_e_outros_ajustes():
    regras = {c.chave for c in campos_das_regras()}
    assert {"envio_real.remarketing", "envio_real.pos_venda", "envio_real.reativacao",
            "remarketing.intervalos_h", "remarketing.carencia_dias",
            "pos_venda.revisao_meses"} <= regras
    assert "remarketing.limite_mensal" not in regras        # é do Plano e limites
    outros = {c.chave for c in campos_de_outros_ajustes()}
    assert {"dados.retencao_dias", "instagram.texto_private_reply"} <= outros
    assert "instagram.limite_private_replies_h" not in outros


# ------------------------------------------------------------ Mensagens automáticas

def test_mensagens_tem_as_cinco_abas(loja, monkeypatch):
    at = _abrir(MENSAGENS, loja, monkeypatch)
    assert not at.exception, at.exception
    assert [t.label for t in at.tabs] == [
        "Agora", "No mês", "Resultado e histórico", "Base da loja", "Regras"]
    rotulos = _rotulos(at)
    assert "Agendar pós-venda da base" in rotulos
    assert "Montar fila de reativação" in rotulos
    assert f"💾 Salvar {REGRAS_DAS_MENSAGENS}" in rotulos
    assert {"Enviadas", "Responderam", "Agendaram visita"} <= {m.label for m in at.metric}


def test_regras_salvam_pela_tela_sem_mexer_na_outra_loja(loja, outra, monkeypatch):
    antes_outra = carregar_loja(outra).get("remarketing.max_toques")
    novo = 1 if carregar_loja(loja).get("remarketing.max_toques") != 1 else 2
    at = _abrir(MENSAGENS, loja, monkeypatch)
    campo = next(n for n in at.number_input
                 if str(n.label).startswith("Máximo de toques por lead"))
    campo.set_value(novo)
    _botao(at, f"💾 Salvar {REGRAS_DAS_MENSAGENS}").click().run()
    assert not at.exception, at.exception
    assert carregar_loja(loja).get("remarketing.max_toques") == novo
    assert carregar_loja(outra).get("remarketing.max_toques") == antes_outra


# ------------------------------------------------------------ Configuração

def test_outros_ajustes_salvam_pela_tela(loja, monkeypatch):
    at = _abrir(CONFIG, loja, monkeypatch)
    at.radio(key="config_assunto").set_value(OUTROS_AJUSTES).run()
    assert not at.exception, at.exception
    assert any(s.value == OUTROS_AJUSTES for s in at.subheader)
    antes = bool(carregar_loja(loja).get("instagram.resposta_publica"))
    chave = next(t for t in at.toggle if str(t.label).startswith("Responder também em público"))
    chave.set_value(not antes)
    _botao(at, f"💾 Salvar {OUTROS_AJUSTES}").click().run()
    assert not at.exception, at.exception
    assert bool(carregar_loja(loja).get("instagram.resposta_publica")) == (not antes)


def test_nome_da_loja_fica_em_identidade(loja, outra, monkeypatch):
    at = _abrir(CONFIG, loja, monkeypatch)
    at.text_input(key=f"s10_nome_{loja}").set_value("Loja S10a Renomeada")
    _botao(at, "💾 Salvar nome").click().run()
    assert not at.exception, at.exception
    nomes = {l["id"]: l["nome"] for l in listar_lojas()}
    assert nomes[loja] == "Loja S10a Renomeada"
    assert nomes[outra] == "Outra loja S10a"


# ------------------------------------------------------------ Ver como a loja

def test_desfazer_com_loja_em_teste_e_outra_loja_intacta(loja, outra, monkeypatch):
    bloqueios.bloquear(loja, LEAD, "todos", None, "Teste")
    bloqueios.bloquear(outra, LEAD, "todos", None, "Teste")
    at = _abrir(VER_COMO, loja, monkeypatch)
    at.button(key="vc_desfazer").click().run()
    assert not at.exception, at.exception
    assert bloqueios.listar_ativos(loja) == []
    assert len(bloqueios.listar_ativos(outra)) == 1


def test_loja_no_ar_nao_mostra_desfazer(monkeypatch):
    with como("Ana", "cliente", "painel", loja_id=1):
        bloqueios.bloquear(1, LEAD, "todos", None, "Ana")
    at = _abrir(VER_COMO, 1, monkeypatch)
    assert not at.exception, at.exception
    assert "vc_desfazer" not in [b.key for b in at.button]


# ------------------------------------------------------------ regras da seção 4

@pytest.mark.parametrize("tela", [MENSAGENS, CONFIG, VER_COMO])
def test_telas_nao_falam_com_o_banco(tela):
    fonte = tela.read_text(encoding="utf-8")
    assert "import banco" not in fonte and "conectar(" not in fonte and "sqlite3" not in fonte


def test_sem_texto_tecnico_na_tela(loja, monkeypatch):
    for tela in (MENSAGENS, CONFIG):
        at = _abrir(tela, loja, monkeypatch)
        textos = " ".join(str(e.value) for e in
                          [*at.caption, *at.info, *at.markdown, *at.warning])
        for proibido in (".env", "Etapa", "Bloco", "UTC"):
            assert proibido not in textos, (tela.name, proibido)
