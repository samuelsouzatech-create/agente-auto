"""
Bloco S8: último ajuste com o Gemini leve (offline, sem IA).
"""
import os
import sys

import pytest
from langchain_core.messages import AIMessage, ToolMessage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import test_comportamento_etapa2_api as api  # noqa: E402
from avisos_texto import AVISO_DE_CHEGADA, PRAZO, VIDEO_FOTO, rotulos_de_texto  # noqa: E402
from app.core import montagem  # noqa: E402

BASE = (montagem.PASTA_PROMPTS / "base.md").read_text(encoding="utf-8")
SEGMENTO = (montagem.pasta_do_segmento("veiculos") / "prompt.md").read_text(encoding="utf-8")


def test_fora_do_horario_sem_chamado_nao_promete_contato():
    assert "Fora do horário e sem chamado aberto" in BASE
    assert "NÃO diga que a equipe vai falar com o cliente" in BASE


def test_financiamento_nao_e_caso_novo_na_espera():
    assert "NÃO são caso novo" in BASE
    for texto in montagem.TEXTOS_EM_ESPERA.values():
        assert "Não chame acionar_handoff de novo pelo mesmo assunto." in texto
        assert "financiamento são do colega que já foi chamado" in texto


def test_agendamento_desligado_separa_interesse_e_prazo():
    aviso = montagem.AVISOS_MODULO_DESLIGADO["agendamento"]
    assert "campo prazo" in aviso
    assert "interesse leva só o carro" in aviso


def test_segmento_nao_promete_avisar_quando_chegar():
    assert "não diga que vai avisar quando chegar" in SEGMENTO
    assert "anote o interesse" not in SEGMENTO


@pytest.mark.parametrize("texto", [
    "Gostaria de ver outros modelos ou prefere que eu anote o seu interesse para caso chegue uma unidade?",
    "O senhor prefere que eu anote o seu interesse para avisá-lo caso chegue uma unidade?",
    "Te aviso assim que chegar uma Hilux.",
    "Assim que aparecer uma unidade, eu te aviso.",
])
def test_detector_de_aviso_de_chegada_pega(texto):
    assert AVISO_DE_CHEGADA in rotulos_de_texto(texto)


@pytest.mark.parametrize("texto", [
    "Não temos a Hilux no momento. Quer ver outras picapes?",
    "Quando chegar aqui na loja, é só procurar o pessoal da equipe.",
    "Quando chegar aqui, me avisa que eu chamo o vendedor.",
])
def test_detector_de_aviso_de_chegada_nao_pega(texto):
    assert AVISO_DE_CHEGADA not in rotulos_de_texto(texto)


def test_em_breve_continua_sendo_prazo():
    assert PRAZO in rotulos_de_texto("Anoto seu interesse para caso chegue uma unidade em breve?")


def _conversa(turnos, espera, loja_id=1):
    c = api.Conversa(loja_id=loja_id, lead_id="s8", falas=["x"] * len(turnos))
    c.novas_por_turno = [novas for novas, _ in turnos]
    c.respostas = [resposta for _, resposta in turnos]
    c.espera_por_turno = list(espera)
    return c


def _chamada(nome, ident):
    return [AIMessage(content="", tool_calls=[{"name": nome, "args": {}, "id": ident}]),
            ToolMessage(content="ok", tool_call_id=ident)]


REGISTREI = "Já registrei aqui o seu relato."


def _com_chamado_antes(espera):
    return _conversa([(_chamada("acionar_handoff", "h1"), "Vou passar para o pessoal da equipe."),
                      ([AIMessage(content=REGISTREI)], REGISTREI)], espera)


def test_registrei_com_chamado_aberto_antes_vale():
    assert not api.registro_sem_ferramenta_s8(_com_chamado_antes([False, True]))


def test_registrei_com_chamado_do_turno_anterior_vale():
    assert not api.registro_sem_ferramenta_s8(_com_chamado_antes([False, False]))


def test_registrei_sem_chamado_nem_ferramenta_avisa():
    c = _conversa([([AIMessage(content="Já registrei o seu interesse.")], "Já registrei o seu interesse.")], [False])
    assert api.registro_sem_ferramenta_s8(c)


def test_registrei_com_registrar_lead_no_turno_vale():
    c = _conversa([(_chamada("registrar_lead", "r1"), "Já registrei o seu interesse.")], [False])
    assert not api.registro_sem_ferramenta_s8(c)


def test_avisos_s7_tira_registro_so_quando_vale(monkeypatch):
    falso = [(api.AVISO, api.REGISTRO_SEM_FERRAMENTA + ': "ja registrei"'), (api.AVISO, "outro")]
    monkeypatch.setattr(api, "_avisos_s7_antes_do_s8", lambda conversas: list(falso))
    assert api.avisos_s7(_com_chamado_antes([False, True])) == [(api.AVISO, "outro")]
    sem = _conversa([([AIMessage(content="Já registrei o seu interesse.")], "Já registrei o seu interesse.")], [False])
    assert api.avisos_s7(sem) == falso


def _tem_aviso_de_foto(conversa):
    return any(str(m).startswith(VIDEO_FOTO) for _, m in api.avisos_s5(conversa))


def test_foto_so_avisa_com_modulo_desligado_ou_carro_sem_foto():
    api.configurar_loja(77, "Loja S8", {"modulos": {"fotos": True}})
    carro = api.adicionar_carro(77, "Chevrolet", "Onix", 2020, 40000, "Vermelho", "Automático", 68000.0)
    texto = "Quer que eu te mande as fotos do Onix?"
    c = _conversa([([AIMessage(content=texto)], texto)], [False], loja_id=77)
    assert not api.fotos_valem_s8(c)          # carro sem foto
    assert _tem_aviso_de_foto(c)
    api.executar_sql("UPDATE estoque SET fotos = ? WHERE id = ?", ("https://exemplo/1.jpg", carro))
    assert api.fotos_valem_s8(c)
    assert not _tem_aviso_de_foto(c)
    api.configurar_loja(77, "Loja S8", {"modulos": {"fotos": False}})
    assert not api.fotos_valem_s8(c)
    assert _tem_aviso_de_foto(c)


def test_video_sempre_avisa():
    api.configurar_loja(78, "Loja S8 b", {"modulos": {"fotos": True}})
    carro = api.adicionar_carro(78, "Chevrolet", "Onix", 2020, 40000, "Vermelho", "Automático", 68000.0)
    api.executar_sql("UPDATE estoque SET fotos = ? WHERE id = ?", ("https://exemplo/1.jpg", carro))
    texto = "Posso te mandar um vídeo do Onix?"
    c = _conversa([([AIMessage(content=texto)], texto)], [False], loja_id=78)
    assert _tem_aviso_de_foto(c)


def test_registrei_sem_campo_respostas_continua_avisando():
    """Conversa montada só com as mensagens da IA (como no teste do S7)."""
    c = api.Conversa(loja_id=1, lead_id="s8b", falas=["oi"])
    c.novas_por_turno = [[AIMessage(content="Vou registrar seu interesse em visitar a loja.")]]
    assert api.registro_sem_ferramenta_s8(c)
