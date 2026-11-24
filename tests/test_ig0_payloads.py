"""IG0 (Maratona 4): os payloads de exemplo do Instagram existem, são JSON e são fictícios, e a
tabela "confirmado / não confirmado" com os links oficiais está no diário."""
import json
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
PASTA = RAIZ / "tests" / "payloads" / "instagram"
ESPERADOS = {"mensagem_texto.json", "mensagem_varias.json", "eco_vendedor.json", "eco_do_leo.json",
             "nao_suportado.json", "comentario_post.json", "comentario_post_entry_direto.json",
             "comentario_anuncio.json", "comentario_da_propria_loja.json", "legenda_do_post.json",
             "resposta_privada_ok.json", "envio_ok.json"}


def test_payloads_existem_e_sao_json():
    assert ESPERADOS <= {p.name for p in PASTA.glob("*.json")}
    for p in PASTA.glob("*.json"):
        json.loads(p.read_text(encoding="utf-8"))


def test_payloads_sao_ficticios():
    for p in PASTA.glob("*.json"):
        texto = p.read_text(encoding="utf-8")
        assert "access_token" not in texto and "@" not in texto, p.name


def test_tabela_da_meta_no_diario():
    diario = (RAIZ / "docs" / "maratona4.md").read_text(encoding="utf-8")
    parte = diario.split("## IG0", 1)[1]
    assert parte.count("developers.facebook.com") >= 10
    assert "não confirmado" in parte and "confirmado" in parte
    for assunto in ("is_echo", "Resposta privada", "anúncio", "legenda", "1000 bytes", "24 h",
                    "Revisão do app", "Exclusão de dados"):
        assert assunto in parte, assunto
