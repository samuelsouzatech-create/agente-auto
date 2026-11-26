"""
SE2 (Maratona Segurança), item 3: o link de senha por e-mail, pelo provedor FALSO (arquivo .eml numa
pasta temporária). OFFLINE. Nada sai do computador.
"""
from __future__ import annotations

import email
import re
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import autenticacao, email_envio, links_senha
from app.relogio import agora_utc
from banco import conectar


@pytest.fixture
def caixa(monkeypatch, tmp_path):
    pasta = tmp_path / "emails"
    monkeypatch.setenv("LEO_EMAIL_PROVEDOR", "arquivo")
    monkeypatch.setenv("LEO_EMAIL_PASTA", str(pasta))
    monkeypatch.setenv("PAINEL_URL", "https://painel.exemplo.invalid")
    monkeypatch.setattr(links_senha, "ENVIADOR", links_senha.enviar_por_email)
    return pasta


def _emails(pasta: Path) -> list:
    return [email.message_from_bytes(p.read_bytes()) for p in sorted(pasta.glob("*.eml"))] if pasta.exists() else []


def _pessoa(email_de_login="ana@loja-a.invalid", loja=1, papel="dono"):
    from app.ator import como
    with como("Teste", "operador", "painel", None):
        return autenticacao.criar_usuario_com_login(loja, "Ana Teste", papel, email_de_login, "senha-forte-de-teste-1")


def _cliente():
    from app.api_painel.main import app
    return TestClient(app)


def _token(mensagem) -> str:
    corpo = mensagem.get_payload(decode=True).decode("utf-8")
    return re.search(r"#token=([A-Za-z0-9_\-]+)", corpo).group(1)


def test_esqueci_a_senha_manda_o_link_por_email(caixa):
    _pessoa()
    r = _cliente().post("/api/v1/auth/esqueci-senha", json={"email": "ana@loja-a.invalid"})
    assert r.status_code == 202
    [m] = _emails(caixa)
    assert m["To"] == "ana@loja-a.invalid" and "senha" in m["Subject"].lower()
    corpo = m.get_payload(decode=True).decode("utf-8")
    assert "https://painel.exemplo.invalid/criar-senha#token=" in corpo and "1 hora" in corpo


def test_resposta_igual_exista_ou_nao_o_email(caixa):
    _pessoa()
    existe = _cliente().post("/api/v1/auth/esqueci-senha", json={"email": "ana@loja-a.invalid"})
    nao = _cliente().post("/api/v1/auth/esqueci-senha", json={"email": "ninguem@loja-a.invalid"})
    assert existe.status_code == nao.status_code == 202
    assert existe.json() == nao.json()
    assert "e-mail estiver cadastrado" in existe.json()["mensagem"].lower()
    assert len(_emails(caixa)) == 1                                  # só quem existe recebe


def test_link_por_email_e_de_uso_unico_e_vence(caixa):
    _pessoa()
    links_senha.pedir_link("ana@loja-a.invalid")
    token = _token(_emails(caixa)[0])
    from app.ator import como
    pessoa = links_senha.pessoa_do_link(token)
    with como(pessoa["nome"], "cliente", "painel", pessoa["loja_id"]):
        links_senha.criar_senha(token, "outra-senha-forte-123")
    with pytest.raises(links_senha.LinkInvalido):                     # uso único
        with como(pessoa["nome"], "cliente", "painel", pessoa["loja_id"]):
            links_senha.criar_senha(token, "mais-uma-senha-forte-1")
    links_senha.pedir_link("ana@loja-a.invalid", agora=agora_utc())
    token2 = _token(_emails(caixa)[-1])
    assert links_senha.pessoa_do_link(token2, agora=agora_utc() + timedelta(hours=1, minutes=1)) is None   # venceu


def test_limite_por_email(caixa):
    _pessoa()
    for _ in range(links_senha.MAX_PEDIDOS):
        links_senha.pedir_link("ana@loja-a.invalid")
    with pytest.raises(autenticacao.MuitasTentativas):
        links_senha.pedir_link("ana@loja-a.invalid")
    assert len(_emails(caixa)) == links_senha.MAX_PEDIDOS


def test_limite_por_endereco(caixa):
    """Alguém tentando muitos e-mails diferentes do mesmo endereço (IP) é barrado."""
    c = _cliente()
    respostas = [c.post("/api/v1/auth/esqueci-senha", json={"email": f"teste{i}@x.invalid"}).status_code
                 for i in range(links_senha.MAX_PEDIDOS_POR_ORIGEM + 2)]
    assert respostas[:links_senha.MAX_PEDIDOS_POR_ORIGEM] == [202] * links_senha.MAX_PEDIDOS_POR_ORIGEM
    assert respostas[-1] == 429


def test_link_e_token_nunca_no_log_nem_no_terminal(caixa, capsys, tmp_path):
    _pessoa()
    links_senha.pedir_link("ana@loja-a.invalid")
    token = _token(_emails(caixa)[0])
    saida = capsys.readouterr()
    assert token not in saida.out + saida.err
    for arquivo in Path(tmp_path).rglob("*.log"):
        assert token not in arquivo.read_text(encoding="utf-8", errors="replace")
    from app import logs
    pasta_log = logs.PASTA_LOGS
    if Path(pasta_log).exists():
        for arquivo in Path(pasta_log).rglob("*.log"):
            assert token not in arquivo.read_text(encoding="utf-8", errors="replace")


def test_o_padrao_nao_escreve_o_link_no_terminal(capsys, monkeypatch, tmp_path):
    """Antes do SE2 o link ia para o terminal (e para o log do Docker). Agora o padrão é o e-mail."""
    monkeypatch.setenv("LEO_EMAIL_PASTA", str(tmp_path / "e"))
    assert links_senha.ENVIADOR is links_senha.enviar_por_email
    _pessoa()
    links_senha.pedir_link("ana@loja-a.invalid")
    saida = capsys.readouterr()
    assert "#token=" not in saida.out + saida.err


def test_falha_do_provedor_nao_muda_a_resposta(caixa, monkeypatch):
    _pessoa()

    class Quebrado:
        nome = "quebrado"

        def enviar(self, e):
            raise RuntimeError("provedor fora")
    monkeypatch.setattr(email_envio, "provedor", lambda: Quebrado())
    r = _cliente().post("/api/v1/auth/esqueci-senha", json={"email": "ana@loja-a.invalid"})
    assert r.status_code == 202


def test_email_de_outra_loja(caixa):
    from app.estado_loja import colocar_no_ar
    from app.lojas import criar_loja
    loja_b = criar_loja("Loja B E-mail")
    colocar_no_ar(loja_b)
    _pessoa("ana@loja-a.invalid", 1)
    _pessoa("bia@loja-b.invalid", loja_b)
    links_senha.pedir_link("bia@loja-b.invalid")
    [m] = _emails(caixa)
    assert m["To"] == "bia@loja-b.invalid"
    pessoa = links_senha.pessoa_do_link(_token(m))
    assert pessoa["loja_id"] == loja_b


def test_pasta_dos_emails_fora_do_git():
    raiz = Path(__file__).resolve().parent.parent
    assert email_envio.PASTA_PADRAO.replace("\\", "/").startswith("logs/")
    assert "logs/" in (raiz / ".gitignore").read_text(encoding="utf-8").splitlines()
