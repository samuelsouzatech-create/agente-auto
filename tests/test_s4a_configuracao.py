"""
S4a (Fase 3): Configuração por assunto no painel do operador.
- todo campo tem um destino só (assunto, Mensagens automáticas ou A decidir);
- salvar e desfazer em cada assunto; desfazer volta só o último Salvar e só o assunto;
- conflito de versão (salvar e desfazer); sem versão, tudo continua como antes;
- campo do operador não salvo nem desfeito por papel de cliente;
- duas lojas; cada ação entra no Registro com quem e quando;
- a tela abre em cada assunto, salva, desfaz e avisa conflito (AppTest);
- as telas antigas continuam abrindo.
Tudo offline, banco temporário do conftest (ator "Teste", operador, painel).
"""
import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from banco import conectar
from app import lojas_admin
from app.ator import como
from app.config_assunto import (
    DesfazerRecusado, NadaParaDesfazer, desfazer_ultima, o_que_desfazer, ultima_alteracao,
)
from app.config_tela import (
    A_DECIDIR, ASSUNTOS, ASSUNTOS_COM_CAMPOS, CAMPOS, MENSAGENS_AUTOMATICAS, NOTAS_ASSUNTO,
    PLANO_E_LIMITES, campos_do_assunto, destino_do_campo, grupos_do_assunto, texto_confirmar,
)
from app.lojas import (
    MODULOS, ConflitoDeVersao, SemPermissao, carregar_loja, limpar_cache, salvar_config,
)
from app.registro_leitura import filtrar_registro
from app.registro_tela import linhas_do_registro

RAIZ = Path(__file__).resolve().parent.parent
TELA = RAIZ / "paginas" / "operador" / "configuracao.py"
UM_CAMPO = {
    "Identidade": ("cidade", "Olinda"),
    "Atendimento": ("atendimento.horario_humano", "08:00-17:00"),
    "Handoff": ("handoff.reaviso_min", 7),
    "Financiamento": ("financiamento.taxa_mensal", 0.022),
    PLANO_E_LIMITES: ("remarketing.limite_mensal", 300),
}


def _loja_b():
    return lojas_admin.criar_loja("Loja B", "Caruaru", "America/Recife", "veiculos")


# ------------------------------------------------------------ mapa

def test_todo_campo_tem_um_destino_so():
    destinos = {c.chave: destino_do_campo(c.chave) for c in CAMPOS}
    assert set(destinos.values()) <= set(ASSUNTOS_COM_CAMPOS) | {MENSAGENS_AUTOMATICAS, A_DECIDIR}
    mostrados = [c.chave for a in ASSUNTOS_COM_CAMPOS for c in campos_do_assunto(a)]
    assert len(mostrados) == len(set(mostrados)) == 20
    assert set(mostrados) == {k for k, d in destinos.items() if d in ASSUNTOS_COM_CAMPOS}


def test_assuntos_e_grupos_do_s4a():
    assert ASSUNTOS_COM_CAMPOS == ("Identidade", "Atendimento", "Handoff", "Financiamento",
                                   PLANO_E_LIMITES)
    assert grupos_do_assunto("Identidade") == ["Identidade"]
    assert grupos_do_assunto(PLANO_E_LIMITES) == ["Módulos", "Custos"]


def test_plano_e_limites_tem_modulos_e_limites():
    chaves = {c.chave for c in campos_do_assunto(PLANO_E_LIMITES)}
    assert chaves == {*(f"modulos.{m}" for m in MODULOS), "custos.teto_diario_llm",
                      "remarketing.limite_mensal", "instagram.limite_private_replies_h"}


def test_intervalos_e_envio_real_ficam_para_mensagens_automaticas():
    for chave in ("remarketing.intervalos_h", "remarketing.primeiro_toque_h",
                  "pos_venda.revisao_meses", "envio_real.reativacao"):
        assert destino_do_campo(chave) == MENSAGENS_AUTOMATICAS
    for chave in ("remarketing.carencia_dias", "instagram.texto_private_reply",
                  "dados.retencao_dias"):
        assert destino_do_campo(chave) == A_DECIDIR


def test_assunto_sem_campos_e_assunto_desconhecido():
    assert campos_do_assunto("Equipe") == [] and grupos_do_assunto("Canais") == []
    with pytest.raises(ValueError):
        campos_do_assunto("Nada")
    with pytest.raises(ValueError):
        grupos_do_assunto("Nada")


def test_dono_continua_no_codigo():
    assert all(c.dono == "operador" for c in campos_do_assunto(PLANO_E_LIMITES))
    for assunto in ("Identidade", "Atendimento", "Handoff", "Financiamento"):
        assert all(c.dono == "cliente" for c in campos_do_assunto(assunto))
    assert "contrato" in texto_confirmar(PLANO_E_LIMITES)
    assert "cliente" in texto_confirmar("Identidade")


def test_textos_sem_termo_tecnico():
    textos = list(NOTAS_ASSUNTO.values()) + [texto_confirmar(a) for a in ASSUNTOS]
    for a in ASSUNTOS_COM_CAMPOS:
        textos += [c.rotulo for c in campos_do_assunto(a)] + [c.ajuda for c in campos_do_assunto(a)]
    for texto in textos:
        for proibido in (".env", "Etapa", "Bloco", "UTC", "código"):
            assert proibido not in texto, (proibido, texto)


# ------------------------------------------------------------ salvar e desfazer

@pytest.mark.parametrize("assunto", list(UM_CAMPO))
def test_salvar_e_desfazer_em_cada_assunto(assunto):
    chave, novo = UM_CAMPO[assunto]
    antes = carregar_loja(1).get(chave)
    salvar_config(1, {chave: novo}, "Samuel")
    assert carregar_loja(1).get(chave) == novo
    assert ultima_alteracao(1, assunto)["quem"] == "Samuel"
    assert ultima_alteracao(1, assunto)["quando"].startswith("hoje ")
    plano = o_que_desfazer(1, assunto)
    assert [i["chave"] for i in plano["itens"]] == [chave]
    desfazer_ultima(1, assunto, "Samuel", "operador")
    assert carregar_loja(1).get(chave) == antes


def test_desfazer_volta_so_o_ultimo_salvar():
    salvar_config(1, {"cidade": "Olinda"}, "Samuel")
    salvar_config(1, {"cidade": "Recife"}, "Samuel")
    plano = o_que_desfazer(1, "Identidade")
    assert plano["itens"] == [{"chave": "cidade", "rotulo": "Cidade",
                               "agora": "Recife", "volta_para": "Olinda"}]
    desfazer_ultima(1, "Identidade", "Samuel", "operador")
    assert carregar_loja(1).get("cidade") == "Olinda"


def test_salvo_junto_desfaz_junto():
    salvar_config(1, {"cidade": "Olinda", "tom": "bem formal"}, "Samuel")
    desfazer_ultima(1, "Identidade", "Samuel", "operador")
    loja = carregar_loja(1)
    assert loja.get("cidade") == "" and loja.get("tom") == "simples, cordial e direto"


def test_desfazer_so_mexe_no_proprio_assunto():
    salvar_config(1, {"cidade": "Olinda"}, "Samuel")
    salvar_config(1, {"handoff.reaviso_min": 7}, "Samuel")
    desfazer_ultima(1, "Handoff", "Samuel", "operador")
    loja = carregar_loja(1)
    assert loja.get("handoff.reaviso_min") == 5 and loja.get("cidade") == "Olinda"
    assert [i["chave"] for i in o_que_desfazer(1, "Identidade")["itens"]] == ["cidade"]


def test_so_confirmar_nao_e_alteracao():
    salvar_config(1, {"cidade": ""}, "Samuel")          # mesmo valor: só confirma
    assert ultima_alteracao(1, "Identidade")["quem"] == "Samuel"
    assert o_que_desfazer(1, "Identidade") is None
    with pytest.raises(NadaParaDesfazer):
        desfazer_ultima(1, "Identidade", "Samuel", "operador")


def test_sem_nada_salvo():
    assert ultima_alteracao(1, "Handoff") is None and o_que_desfazer(1, "Handoff") is None
    assert ultima_alteracao(1, "Equipe") is None


def test_valor_mudado_por_fora_recusa_desfazer():
    salvar_config(1, {"cidade": "Olinda"}, "Samuel")
    conexao = conectar()
    try:
        config = json.loads(conexao.execute("SELECT config FROM lojas WHERE id = 1")
                            .fetchone()["config"])
        config["cidade"] = "Recife"
        conexao.execute("UPDATE lojas SET config = ?, versao_config = versao_config + 1 "
                        "WHERE id = 1", (json.dumps(config),))
        conexao.commit()
    finally:
        conexao.close()
    limpar_cache()
    with pytest.raises(DesfazerRecusado):
        desfazer_ultima(1, "Identidade", "Samuel", "operador")
    assert carregar_loja(1).get("cidade") == "Recife"


# ------------------------------------------------------------ conflito de versão

def test_conflito_de_versao_ao_salvar():
    vista = carregar_loja(1).versao_config
    salvar_config(1, {"cidade": "Olinda"}, "Ana")
    with pytest.raises(ConflitoDeVersao):
        salvar_config(1, {"tom": "bem formal"}, "Samuel", versao_esperada=vista)
    assert carregar_loja(1).get("tom") == "simples, cordial e direto"
    salvar_config(1, {"tom": "bem formal"}, "Samuel",
                  versao_esperada=carregar_loja(1).versao_config)
    assert carregar_loja(1).get("tom") == "bem formal"


def test_conflito_de_versao_ao_desfazer():
    salvar_config(1, {"cidade": "Olinda"}, "Samuel")
    vista = carregar_loja(1).versao_config
    salvar_config(1, {"handoff.reaviso_min": 7}, "Ana")
    with pytest.raises(ConflitoDeVersao):
        desfazer_ultima(1, "Identidade", "Samuel", "operador", versao_esperada=vista)
    assert carregar_loja(1).get("cidade") == "Olinda"


def test_sem_versao_esperada_continua_como_antes():
    salvar_config(1, {"cidade": "Olinda"}, "Ana")
    salvar_config(1, {"cidade": "Recife"}, "Samuel")
    assert carregar_loja(1).get("cidade") == "Recife"


# ------------------------------------------------------------ dono do campo

def test_cliente_nao_salva_nem_desfaz_campo_do_operador():
    salvar_config(1, {"remarketing.limite_mensal": 300}, "Samuel")
    with como("Ana", "cliente", "painel", loja_id=1):
        with pytest.raises(SemPermissao):
            salvar_config(1, {"remarketing.limite_mensal": 10}, "Ana", papel="operador")
        with pytest.raises(SemPermissao):
            desfazer_ultima(1, PLANO_E_LIMITES, "Ana", "operador")
    assert carregar_loja(1).get("remarketing.limite_mensal") == 300


# ------------------------------------------------------------ duas lojas

def test_duas_lojas_nao_se_misturam():
    b = _loja_b()
    salvar_config(b, {"cidade": "Gravatá"}, "Bia")
    salvar_config(1, {"cidade": "Olinda"}, "Samuel")
    assert ultima_alteracao(b, "Identidade")["quem"] == "Bia"
    desfazer_ultima(b, "Identidade", "Bia", "operador")
    assert carregar_loja(b).get("cidade") == "Caruaru"
    assert carregar_loja(1).get("cidade") == "Olinda"
    assert o_que_desfazer(1, "Identidade")["quem"] == "Samuel"


def test_loja_obrigatoria():
    with pytest.raises(ValueError):
        ultima_alteracao(None, "Identidade")
    with pytest.raises(ValueError):
        o_que_desfazer(None, "Identidade")
    with pytest.raises(ValueError):
        desfazer_ultima(None, "Identidade", "Samuel", "operador")


# ------------------------------------------------------------ registro

def test_salvar_e_desfazer_entram_no_registro():
    salvar_config(1, {"cidade": "Olinda"}, "Samuel")
    desfazer_ultima(1, "Identidade", "Samuel", "operador")
    linhas = linhas_do_registro(filtrar_registro(1, acao="salvar_configuracao"), com_loja=False)
    assert len(linhas) == 2
    assert all(l["Quem"] == "Samuel" and l["Quando"].startswith("hoje ") for l in linhas)
    assert {l["Detalhe"] for l in linhas} == {"Cidade: vazio → Olinda", "Cidade: Olinda → vazio"}


# ------------------------------------------------------------ tela

@pytest.fixture
def nome_operador(monkeypatch):
    monkeypatch.setenv("OPERADOR_NOME", "Samuel Tela")


def _abrir(loja=1):
    at = AppTest.from_file(str(TELA), default_timeout=30)
    at.session_state["_papel"] = "operador"
    at.session_state["loja_id"] = loja
    return at.run()


def _texto(at, comeco):
    return next(w for w in at.text_input if str(w.label).startswith(comeco))


def _botao(at, rotulo):
    return next(b for b in at.button if str(b.label) == rotulo)


def test_tela_abre_em_cada_assunto(nome_operador):
    at = _abrir()
    assert not at.exception, at.exception
    for assunto in ASSUNTOS:
        at.radio(key="config_assunto").set_value(assunto).run()
        assert not at.exception, (assunto, at.exception)
        assert any(s.value == assunto for s in at.subheader), assunto


def test_tela_salva_e_desfaz(nome_operador):
    at = _abrir()
    _texto(at, "Cidade").set_value("Olinda")
    _botao(at, "💾 Salvar Identidade").click().run()
    assert not at.exception, at.exception
    assert carregar_loja(1).get("cidade") == "Olinda"
    assert any("salvo" in s.value for s in at.success)
    assert any("por Samuel Tela" in c.value for c in at.caption)
    _botao(at, "↩️ Desfazer").click().run()
    assert not at.exception, at.exception
    assert carregar_loja(1).get("cidade") == ""
    assert any("desfeita" in s.value for s in at.success)


def test_tela_salva_plano_e_limites(nome_operador):
    at = _abrir()
    at.radio(key="config_assunto").set_value(PLANO_E_LIMITES).run()
    _texto(at, "Limite mensal de envios").set_value("300")
    _botao(at, "💾 Salvar Plano e limites").click().run()
    assert not at.exception, at.exception
    assert carregar_loja(1).get("remarketing.limite_mensal") == 300


def test_tela_avisa_conflito_e_nao_grava(nome_operador):
    at = _abrir()
    salvar_config(1, {"tom": "bem formal"}, "Ana")       # outra pessoa salva no meio
    _texto(at, "Cidade").set_value("Olinda")
    _botao(at, "💾 Salvar Identidade").click().run()
    assert not at.exception, at.exception
    assert carregar_loja(1).get("cidade") == ""
    assert any("Outra pessoa salvou" in w.value for w in at.warning)


def test_telas_antigas_continuam_abrindo(nome_operador):
    cliente = AppTest.from_file(str(RAIZ / "paginas" / "configuracao.py"), default_timeout=30)
    cliente.session_state["_papel"] = "cliente"
    cliente.session_state["_loja_cliente"] = 1
    cliente.run()
    assert not cliente.exception, cliente.exception
    # S10b: a tela antiga "Plano e limites" saiu (o assunto Plano e limites ficou).
    assert not (RAIZ / "paginas" / "plano.py").exists()
