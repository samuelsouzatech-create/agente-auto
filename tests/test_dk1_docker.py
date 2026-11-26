"""
DK1 (Maratona Docker): o Léo inteiro sobe com um comando.

Confere o desenho dos arquivos do Docker (sem ligar o Docker: roda offline):
- só o porteiro publica porta; banco e Redis só em 127.0.0.1; operador e simulador só em 127.0.0.1;
- toda peça tem verificação de saúde e reinicia sozinha;
- volumes com nome para banco, Chroma, fotos e logs;
- senhas só do .env; a API só confia no IP fixo do porteiro (nunca "*");
- imagem com versões fixas e usuário sem poder de administrador;
- a verificação de saúde do relógio (sinal no Redis).
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import fakeredis
import pytest
import yaml

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "docker"))
import saude  # noqa: E402  (docker/saude.py)

PECAS_LEO = {"webhook", "api-painel", "relogio", "operador", "simulador", "telegram"}


@pytest.fixture(scope="module")
def compose() -> dict:
    return yaml.safe_load((RAIZ / "docker-compose.yml").read_text(encoding="utf-8"))


def _portas(servico: dict) -> list[str]:
    return [str(p) for p in servico.get("ports", [])]


def test_tem_todas_as_pecas(compose):
    esperadas = {"postgres", "redis", "migrar", "webhook", "api-painel", "relogio", "operador",
                 "porteiro", "simulador", "telegram"}
    assert esperadas <= set(compose["services"])


def test_so_o_porteiro_publica_porta_para_fora(compose):
    for nome, servico in compose["services"].items():
        for porta in _portas(servico):
            if nome == "porteiro" and porta.startswith("${PORTEIRO_IP"):
                continue
            assert porta.startswith("127.0.0.1:"), f"{nome} publica {porta} fora de 127.0.0.1"
    for nome in PECAS_LEO | {"migrar"}:
        assert not compose["services"][nome].get("ports"), f"{nome} não pode publicar porta"


def test_porteiro_fica_em_127_por_padrao_e_paineis_sem_login_sempre_em_127(compose):
    portas = _portas(compose["services"]["porteiro"])
    assert "${PORTEIRO_IP:-127.0.0.1}:${PORTEIRO_PORTA:-443}:443" in portas
    for interna in ("8501", "8502"):
        assert f"127.0.0.1:{interna}:{interna}" in " ".join(portas)


def test_banco_e_redis_so_em_127_e_com_senha_do_env(compose):
    s = compose["services"]
    assert _portas(s["postgres"]) == ["127.0.0.1:${BANCO_PORTA:-5432}:5432"]
    assert _portas(s["redis"]) == ["127.0.0.1:${REDIS_PORTA:-6379}:6379"]
    assert s["postgres"]["environment"]["POSTGRES_PASSWORD"].startswith("${POSTGRES_SENHA")
    assert s["redis"]["environment"]["REDIS_SENHA"].startswith("${REDIS_SENHA")
    assert "--requirepass" in " ".join(s["redis"]["command"])


def test_toda_peca_tem_saude_e_reinicia_sozinha(compose):
    for nome, servico in compose["services"].items():
        if nome == "migrar":                      # roda uma vez e sai
            assert servico["restart"] == "no"
            continue
        assert servico.get("restart") == "unless-stopped", nome
        assert servico.get("healthcheck", {}).get("test"), f"{nome} sem verificação de saúde"


def test_volumes_com_nome(compose):
    volumes = compose["volumes"]
    for nome in ("leo_banco", "leo_chroma", "leo_fotos", "leo_logs", "leo_redis", "leo_caddy_dados"):
        assert volumes[nome]["name"] == nome
    montados = compose["services"]["webhook"]["volumes"]
    assert set(montados) == {"leo_chroma:/app/chroma_db", "leo_fotos:/app/fotos_deposito",
                             "leo_logs:/app/logs"}


def test_api_e_webhook_confiam_so_no_ip_do_porteiro(compose):
    s = compose["services"]
    ip = s["porteiro"]["networks"]["interna"]["ipv4_address"]
    for nome in ("api-painel", "webhook"):
        comando = s[nome]["command"]
        assert "--proxy-headers" in comando
        assert comando[comando.index("--forwarded-allow-ips") + 1] == ip
    assert "*" not in json.dumps([s["api-painel"]["command"], s["webhook"]["command"]])


def test_compose_nao_tem_senha_escrita(compose):
    texto = (RAIZ / "docker-compose.yml").read_text(encoding="utf-8")
    for linha in texto.splitlines():
        if re.search(r"(SENHA|PASSWORD|TOKEN|SECRET|KEY)\s*[:=]", linha, re.I):
            assert "${" in linha, linha
    ambiente = compose["services"]["api-painel"]["environment"]
    # SE3: o app usa o usuário leo_app (senha BANCO_APP_SENHA); o dono (POSTGRES_SENHA) só no migrar
    assert "${BANCO_APP_SENHA" in ambiente["BANCO_URL"] and "@postgres:5432/" in ambiente["BANCO_URL"]
    assert "${POSTGRES_SENHA" in compose["services"]["migrar"]["environment"]["BANCO_URL"]
    assert "${REDIS_SENHA" in ambiente["REDIS_URL"] and "@redis:6379/" in ambiente["REDIS_URL"]


def test_simulador_e_telegram_so_com_perfil(compose):
    assert compose["services"]["simulador"]["profiles"] == ["demo"]
    assert compose["services"]["telegram"]["profiles"] == ["telegram"]


def test_dockerfile_versao_fixa_e_usuario_sem_administrador():
    texto = (RAIZ / "Dockerfile").read_text(encoding="utf-8")
    for imagem in re.findall(r"^FROM (\S+)", texto, re.M):
        assert re.search(r":\d+\.\d+\.\d+", imagem), f"imagem sem versão exata: {imagem}"
    usuarios = re.findall(r"^USER (\S+)", texto, re.M)
    assert usuarios and usuarios[-1] not in ("root", "0")
    porteiro = (RAIZ / "docker" / "porteiro.Dockerfile").read_text(encoding="utf-8")
    for imagem in re.findall(r"^FROM (\S+)", porteiro, re.M):
        assert re.search(r":\d+\.\d+\.\d+", imagem), imagem
    for servico in yaml.safe_load((RAIZ / "docker-compose.yml").read_text(encoding="utf-8"))["services"].values():
        if "image" in servico and "build" not in servico:
            assert re.search(r":\d+\.\d+(\.\d+)?(-\w+)?$", servico["image"]), servico["image"]


def test_pacotes_python_com_versao_fixa():
    for linha in (RAIZ / "requirements.txt").read_text(encoding="utf-8").splitlines():
        linha = linha.split("#")[0].strip()
        if linha:
            assert "==" in linha, f"pacote sem versão fixa: {linha}"


def test_segredos_e_dados_fora_da_imagem():
    ignorados = (RAIZ / ".dockerignore").read_text(encoding="utf-8").splitlines()
    for item in (".env", "*.db", "chroma_db/", "fotos_deposito/", "logs/", "venv/", "diagnostico_meta.py"):
        assert item in ignorados, item


def test_caddy_repassa_o_endereco_real_e_nao_confia_no_visitante():
    texto = (RAIZ / "docker" / "Caddyfile").read_text(encoding="utf-8")
    assert "header_up X-Forwarded-For {remote_host}" in texto
    assert "X-Forwarded-Proto {scheme}" in texto and "Host {host}" in texto
    assert "trusted_proxies" not in texto
    assert "reverse_proxy api-painel:8001" in texto


def test_env_exemplo_tem_redis_senha_de_exemplo():
    texto = (RAIZ / ".env.example").read_text(encoding="utf-8")
    assert "REDIS_SENHA=TROQUE-ESTA-SENHA" in texto


# ------------------------------------------------------------ verificação de saúde do relógio
@pytest.fixture
def redis_falso(monkeypatch):
    cliente = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(saude, "_redis", lambda: cliente)
    return cliente


def _sinal(cliente, estado, quando):
    cliente.set("saude:relogio", json.dumps({"estado": estado,
                                             "quando": quando.strftime("%Y-%m-%d %H:%M:%S")}))


def test_relogio_saudavel_quando_girou_agora(redis_falso):
    _sinal(redis_falso, "girando", datetime.now(timezone.utc))
    assert saude.main(["relogio"]) == 0


def test_relogio_doente_quando_parado_atrasado_ou_sem_sinal(redis_falso):
    assert saude.main(["relogio"]) == 1
    _sinal(redis_falso, "girando", datetime.now(timezone.utc) - timedelta(minutes=10))
    assert saude.main(["relogio"]) == 1
    _sinal(redis_falso, "parado", datetime.now(timezone.utc))
    assert saude.main(["relogio"]) == 1


def test_redis_fora_do_ar_e_doente(monkeypatch):
    def quebra():
        raise ConnectionError("fora")
    monkeypatch.setattr(saude, "_redis", quebra)
    assert saude.main(["relogio"]) == 1
    assert saude.main(["redis"]) == 1


def test_http_fora_do_ar_e_doente():
    assert saude.main(["http", "http://127.0.0.1:9/"]) == 1


# ------------------------------------------------------------ relógio parado pelo Docker
def test_sigterm_do_docker_vira_ctrl_c_no_relogio():
    """O Docker para o relógio com SIGTERM: tem de virar Ctrl+C para o runner soltar a trava."""
    import signal

    from app.jobs import runner
    antes = signal.getsignal(signal.SIGTERM)
    try:
        runner._parar_com_sigterm()
        tratador = signal.getsignal(signal.SIGTERM)
        with pytest.raises(KeyboardInterrupt):
            tratador(signal.SIGTERM, None)
    finally:
        signal.signal(signal.SIGTERM, antes)


def test_relogio_solta_a_trava_quando_o_docker_para(monkeypatch):
    """Simula o "docker compose stop" no meio do giro: a trava sai do Redis e o sinal fica "parado"."""
    from app.jobs import batimento, runner, trava as trava_mod
    cliente = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(runner, "cliente_redis_sincrono", lambda: cliente)
    monkeypatch.setattr(runner, "rodar_ciclo", lambda *a, **k: {})

    def docker_para(*_a, **_k):
        raise KeyboardInterrupt          # o que o SIGTERM vira

    monkeypatch.setattr(runner.time, "sleep", docker_para)
    monkeypatch.setattr(runner, "_parar_com_sigterm", lambda: None)
    assert runner.main(["--sem-remarketing", "--sem-pos-venda", "--sem-reativacao"]) == 0
    assert not cliente.exists(trava_mod.CHAVE)
    assert batimento.ler(cliente)["estado"] == batimento.PARADO
