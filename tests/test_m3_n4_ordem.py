"""
Maratona 3, N4: o pós-processamento do turno é uma lista única, ordenada e com nomes; _mantem_linhas
é aplicado onde cada guarda é definida. OFFLINE. Comportamento igual ao de antes (os outros testes
não mudaram de expectativa).
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

RAIZ = Path(__file__).resolve().parents[1]


def test_lista_unica_na_ordem_combinada():
    from app.core.pos_processamento import PASSOS
    assert [p.__name__ for p in PASSOS] == [
        "texto_interno", "preco_inventado", "frases_proibidas", "regra_de_entrada", "risco_e_politica",
        "promessa_de_foto", "elogio_da_foto", "estado_sem_ficha", "agendamento", "chamado_pelo_codigo",
        "pos_venda_e_urgencia", "aviso_de_chamado", "falso_dono", "emoji", "palavra_de_tempo", "repeticoes",
        "frase_de_oferta"]   # N5: + palavra_de_tempo


def test_guardas_linha_a_linha_na_definicao_e_sem_reatribuir_no_fim():
    import app.guarda_politica as g
    nomes = ["trocar_frases_proibidas", "corrigir_regra_de_entrada", "trocar_politica_sem_base",
             "tirar_promessa_de_foto", "trocar_frases_de_risco", "cortar_estado_inventado",
             "tirar_agendamento_falso", "tirar_elogio_do_estado"]
    assert all(hasattr(getattr(g, n), "__wrapped__") for n in nomes)
    fonte = (RAIZ / "app" / "guarda_politica.py").read_text(encoding="utf-8")
    assert not any(f"{n} = _mantem_linhas(" in fonte for n in nomes)
    assert all(f"@_mantem_linhas\ndef {n}(" in fonte for n in nomes)


def test_turno_usa_a_lista():
    fonte = (RAIZ / "app" / "core" / "turno.py").read_text(encoding="utf-8")
    assert "pos_processar(Contexto(" in fonte and "resposta, trocou = trocar_frases_proibidas(resposta)" not in fonte
