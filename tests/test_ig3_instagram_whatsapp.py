"""
IG3 (Maratona 4): do Instagram para o WhatsApp, o mesmo cliente nos dois canais, o painel
(contrato 1.3.0) e a exclusão de dados (I6). OFFLINE, duas lojas.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import canais, instagram_whatsapp as iw, lojas
from app.api import dados
from app.estado_loja import colocar_no_ar
from app.lojas import criar_loja
from app.relogio import para_banco
from banco import conectar

FONE = "5581999998888"


def _exec(sql, args=()):
    c = conectar()
    c.execute(sql, args)
    c.commit()
    c.close()


def _ler(sql, args=()):
    c = conectar()
    try:
        return [dict(l) for l in c.execute(sql, args).fetchall()]
    finally:
        c.close()


def _msg(loja, lead, canal, direcao, texto, quando):
    _exec("INSERT INTO mensagens (lead_id, loja_id, canal, direcao, conteudo, criado_em) VALUES (?, ?, ?, ?, ?, ?)",
          (lead, loja, canal, direcao, texto, para_banco(quando)))


@pytest.fixture
def loja_b():
    loja = criar_loja("Loja B IG3")
    colocar_no_ar(loja)
    return loja


# ------------------------------------------------------------------ levar para o WhatsApp
def test_pediu_whatsapp_e_telefone_no_texto():
    assert iw.pediu_whatsapp("pode me chamar no zap?") and iw.pediu_whatsapp("tem WhatsApp?")
    assert not iw.pediu_whatsapp("quanto custa o civic?")
    assert iw.telefone_do_texto("meu número é (81) 99999-8888, valeu") == FONE
    assert iw.telefone_do_texto("o carro é 2019 e tem 50.000 km") == ""


def test_frase_so_quando_pede_ou_chama_o_vendedor():
    lojas.salvar_config(1, {"instagram.whatsapp_da_loja": "81 98888-7777"}, "teste")
    loja = lojas.carregar_loja(1)
    assert loja.get("instagram.oferecer_whatsapp") == "pedido_ou_vendedor"
    assert iw.frase_do_whatsapp(loja, "quanto custa?", False, False) == ""
    frase = iw.frase_do_whatsapp(loja, "me chama no zap", False, False)
    assert "https://wa.me/5581988887777" in frase and "telefone" in frase
    assert "https://wa.me/5581988887777" in iw.frase_do_whatsapp(loja, "ok", True, True)
    from app.guarda_politica import tem_emoji
    assert not tem_emoji(frase)
    lojas.salvar_config(1, {"instagram.oferecer_whatsapp": "nunca"}, "teste")
    assert iw.frase_do_whatsapp(lojas.carregar_loja(1), "me chama no zap", True, False) == ""


def test_sem_whatsapp_cadastrado_nao_oferece():
    assert iw.frase_do_whatsapp(lojas.carregar_loja(1), "me chama no zap", True, False) == ""


def test_whatsapp_da_loja_invalido_e_recusado():
    with pytest.raises(lojas.ConfigInvalida):
        lojas.salvar_config(1, {"instagram.whatsapp_da_loja": "123"}, "teste")


# ------------------------------------------------------------------ mesmo cliente
def test_mesmo_cliente_na_mesma_loja_dentro_do_prazo(loja_b):
    assert iw.gravar_telefone(1, "ig:111", "(81) 99999-8888")
    assert iw.vincular_mesmo_cliente(1, "whatsapp", FONE) == "ig:111"
    assert iw.vincular_mesmo_cliente(1, "whatsapp", FONE) == "ig:111"            # uma vez só
    assert _ler("SELECT COUNT(*) AS n FROM clientes_vinculados") == [{"n": 1}]
    assert iw.conversas_do_cliente(1, FONE) == ["ig:111", FONE]
    assert iw.conversas_do_cliente(1, "ig:111") == ["ig:111", FONE]


def test_telefone_igual_em_lojas_diferentes_nao_junta(loja_b):
    iw.gravar_telefone(1, "ig:111", FONE)
    assert iw.vincular_mesmo_cliente(loja_b, "whatsapp", FONE) is None          # a B não tem esse lead
    iw.gravar_telefone(loja_b, "ig:222", FONE)
    assert iw.vincular_mesmo_cliente(loja_b, "whatsapp", FONE) == "ig:222"
    assert iw.vincular_mesmo_cliente(1, "whatsapp", FONE) == "ig:111"
    assert {(l["loja_id"], l["lead_principal"]) for l in _ler("SELECT loja_id, lead_principal FROM clientes_vinculados")} \
        == {(1, "ig:111"), (loja_b, "ig:222")}


def test_fora_do_prazo_nao_junta():
    iw.gravar_telefone(1, "ig:111", FONE)
    depois = datetime.now(timezone.utc) + timedelta(days=8)
    assert iw.vincular_mesmo_cliente(1, "whatsapp", FONE, agora=depois) is None
    lojas.salvar_config(1, {"instagram.prazo_mesmo_cliente_dias": 10}, "teste")
    assert iw.vincular_mesmo_cliente(1, "whatsapp", FONE, agora=depois) == "ig:111"


def test_so_whatsapp_junta():
    iw.gravar_telefone(1, "ig:111", FONE)
    assert iw.vincular_mesmo_cliente(1, "telegram", FONE) is None


# ------------------------------------------------------------------ painel: um cartão, dois canais
def _cliente_nos_dois_canais(loja=1):
    agora = datetime.now(timezone.utc)
    _msg(loja, "ig:111", "instagram", "cliente", "vi o civic no insta", agora - timedelta(hours=2))
    _msg(loja, "ig:111", "instagram", "leo", "Oi! O Civic está aqui.", agora - timedelta(hours=2, minutes=-1))
    from app.instagram import anotar_origem
    anotar_origem(loja, "ig:111", "anuncio", "238")
    iw.gravar_telefone(loja, "ig:111", FONE)
    iw.vincular_mesmo_cliente(loja, "whatsapp", FONE)
    _msg(loja, FONE, "whatsapp", "cliente", "oi, sou eu do instagram", agora - timedelta(minutes=30))
    _msg(loja, FONE, "whatsapp", "leo", "Oi de novo!", agora - timedelta(minutes=29))


def test_leads_mostra_um_cartao_com_os_dois_canais_e_como_chegou():
    from app.api_painel.leads import montar_leads
    _cliente_nos_dois_canais()
    itens = montar_leads(1)["itens"]
    meus = [i for i in itens if i["lead"] in ("ig:111", FONE)]
    assert len(meus) == 1 and meus[0]["lead"] == "ig:111"
    assert meus[0]["canais"] == ["Instagram", "WhatsApp"] and meus[0]["como_chegou"] == "Anúncio"


def test_conversa_tem_o_historico_dos_dois_canais_em_ordem():
    from app.api_painel.conversa import montar_conversa
    _cliente_nos_dois_canais()
    c = montar_conversa(1, "ig:111", {"nome": "Ana", "papel": "dono", "usuario_id": 1})
    assert [m["texto"] for m in c["mensagens"]] == ["vi o civic no insta", "Oi! O Civic está aqui.",
                                                    "oi, sou eu do instagram", "Oi de novo!"]
    assert c["cliente"]["canais"] == ["Instagram", "WhatsApp"]


def test_atender_mostra_canal_e_como_chegou_sem_cartao_repetido():
    from app.api_painel.atender import montar_atender
    _cliente_nos_dois_canais()
    hoje = montar_atender(1)["conversas_de_hoje"]
    meus = [c for c in hoje if c["lead"] in ("ig:111", FONE)]
    assert len(meus) == 1 and meus[0]["como_chegou"] == "Anúncio"
    assert set(meus[0]["canais"]) == {"Instagram", "WhatsApp"}


def test_outra_loja_nao_ve_o_cliente_junto(loja_b):
    from app.api_painel.leads import montar_leads
    _cliente_nos_dois_canais(1)
    assert [i for i in montar_leads(loja_b)["itens"] if i["lead"] in ("ig:111", FONE)] == []


def test_mocks_do_contrato_conferem():
    import subprocess
    import sys
    from pathlib import Path
    raiz = Path(__file__).resolve().parents[1]
    r = subprocess.run([sys.executable, str(raiz / "docs" / "api" / "conferir_mocks.py")], capture_output=True,
                       text=True, cwd=str(raiz), encoding="utf-8", errors="replace")
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    assert "version: 1.3.0" in (raiz / "docs" / "api" / "openapi.yaml").read_text(encoding="utf-8")


# ------------------------------------------------------------------ exclusão de dados (I6)
SEGREDO = "segredo-falso"


def _assinado(dados_pedido: dict, segredo=SEGREDO) -> str:
    corpo = base64.urlsafe_b64encode(json.dumps(dados_pedido).encode()).decode().rstrip("=")
    sig = base64.urlsafe_b64encode(hmac.new(segredo.encode(), corpo.encode(), hashlib.sha256).digest()).decode().rstrip("=")
    return f"{sig}.{corpo}"


def test_pedido_assinado_e_conferido():
    assert dados.ler_pedido_assinado(_assinado({"algorithm": "HMAC-SHA256", "user_id": "9"}), SEGREDO)["user_id"] == "9"
    for ruim in (_assinado({"algorithm": "HMAC-SHA256", "user_id": "9"}, "outro"), "lixo", ""):
        with pytest.raises(dados.PedidoInvalido):
            dados.ler_pedido_assinado(ruim, SEGREDO)
    with pytest.raises(dados.PedidoInvalido):
        dados.ler_pedido_assinado(_assinado({"algorithm": "HMAC-SHA256", "user_id": "9"}), "")


def test_excluir_apaga_so_o_cliente_pedido_na_loja_certa(loja_b, monkeypatch):
    agora = datetime.now(timezone.utc)
    for loja, lead in ((1, "ig:900"), (1, "ig:901"), (loja_b, "ig:902"), (loja_b, "5581977776666")):
        _msg(loja, lead, "instagram", "cliente", f"oi de {lead}", agora)
        _exec("INSERT INTO leads (lead_id, loja_id, nome) VALUES (?, ?, 'X')", (lead, loja))
    _exec("INSERT INTO handoffs (lead_id, loja_id, motivo, resumo, estado) VALUES ('ig:900', 1, 'm', 'r', 'aguardando_humano')")
    monkeypatch.setenv("INSTAGRAM_APP_SECRET", SEGREDO)
    from app.api.webhook import app
    r = TestClient(app).post("/dados/excluir", data={"signed_request": _assinado({"algorithm": "HMAC-SHA256", "user_id": "900"})})
    assert r.status_code == 200
    corpo = r.json()
    assert set(corpo) == {"url", "confirmation_code"} and corpo["url"].endswith(corpo["confirmation_code"])
    assert _ler("SELECT COUNT(*) AS n FROM mensagens WHERE lead_id = 'ig:900'") == [{"n": 0}]
    assert _ler("SELECT COUNT(*) AS n FROM handoffs WHERE lead_id = 'ig:900'") == [{"n": 0}]
    assert _ler("SELECT COUNT(*) AS n FROM leads WHERE lead_id = 'ig:900'") == [{"n": 0}]
    for loja, lead in ((1, "ig:901"), (loja_b, "ig:902"), (loja_b, "5581977776666")):
        assert _ler("SELECT COUNT(*) AS n FROM mensagens WHERE loja_id = ? AND lead_id = ?", (loja, lead)) == [{"n": 1}]
    [pedido] = _ler("SELECT * FROM pedidos_exclusao")
    assert pedido["codigo"] == corpo["confirmation_code"] and "900" not in json.dumps(pedido, default=str)
    assert TestClient(app).get(f"/dados/excluir/{corpo['confirmation_code']}").status_code == 200
    assert TestClient(app).get("/dados/excluir/naoexiste").status_code == 404


def test_excluir_sem_segredo_ou_assinatura_errada_recusa(monkeypatch):
    from app.api.webhook import app
    monkeypatch.setenv("INSTAGRAM_APP_SECRET", "")
    pedido = _assinado({"algorithm": "HMAC-SHA256", "user_id": "900"})
    assert TestClient(app).post("/dados/excluir", data={"signed_request": pedido}).status_code == 400
    monkeypatch.setenv("INSTAGRAM_APP_SECRET", "outro")
    assert TestClient(app).post("/dados/excluir", data={"signed_request": pedido}).status_code == 400


def test_rascunhos_da_meta_marcados():
    from pathlib import Path
    pasta = Path(__file__).resolve().parents[1] / "docs" / "meta"
    for nome in ("privacidade.md", "termos.md", "justificativas.md", "roteiro_video.md"):
        assert "RASCUNHO, revisar com advogado" in (pasta / nome).read_text(encoding="utf-8"), nome
