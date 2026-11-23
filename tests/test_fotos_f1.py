"""
Maratona Fotos, F1: depósito único das fotos do ESTOQUE. Tudo offline (nuvem e links são falsos),
banco e depósito temporários (conftest), duas lojas.
"""
import asyncio
import io

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import deposito, fotos
from app.ator import como
from banco import conectar


# ------------------------------------------------------------ ajudantes

def _imagem(formato="JPEG", tamanho=(800, 600), cor=(200, 50, 50), exif=None, modo="RGB") -> bytes:
    saida = io.BytesIO()
    img = Image.new(modo, tamanho, cor if modo == "RGB" else cor + (128,))
    argumentos = {"exif": exif} if exif is not None else {}
    img.save(saida, format=formato, **argumentos)
    return saida.getvalue()


def _exif_com_gps_e_rotacao():
    exif = Image.Exif()
    exif[0x0112] = 6                                   # rotação: 90 graus
    exif[0x010F] = "Fabricante Falso"
    gps = exif.get_ifd(0x8825)
    gps[1], gps[2] = "S", (8.0, 3.0, 0.0)              # latitude de Recife
    gps[3], gps[4] = "W", (34.0, 52.0, 0.0)
    return exif


def _sql(sql, parametros=()):
    conexao = conectar()
    try:
        conexao.execute(sql, parametros)
        conexao.commit()
    finally:
        conexao.close()


def _um(sql, parametros=()):
    conexao = conectar()
    try:
        linha = conexao.execute(sql, parametros).fetchone()
        return linha[0] if linha else None
    finally:
        conexao.close()


@pytest.fixture
def duas_lojas():
    _sql("INSERT OR IGNORE INTO lojas (id, nome, segmento, config) VALUES (2, 'Loja B', 'veiculos', '{}')")


# ------------------------------------------------------------ preparo

def test_preparo_tira_exif_e_gps_e_corrige_a_rotacao():
    original = _imagem(tamanho=(800, 600), exif=_exif_com_gps_e_rotacao())
    assert Image.open(io.BytesIO(original)).getexif().get(0x0112) == 6
    pronta = fotos.preparar(original)
    img = Image.open(io.BytesIO(pronta))
    assert img.format == "JPEG"
    assert img.size == (600, 800)                      # girou de pé
    assert len(img.getexif()) == 0 and "exif" not in img.info
    assert b"Fabricante Falso" not in pronta and b"GPS" not in pronta


def test_preparo_reduz_para_1600_e_fica_abaixo_de_1_mb():
    import os
    # Foto de celular grande: 4000x3000 com muito detalhe (ruído), em JPEG de alta qualidade.
    grande = Image.frombytes("RGB", (4000, 3000), os.urandom(4000 * 3000 * 3))
    saida = io.BytesIO()
    grande.save(saida, format="JPEG", quality=80)
    assert len(saida.getvalue()) > 5_000_000
    pronta = fotos.preparar(saida.getvalue())
    img = Image.open(io.BytesIO(pronta))
    assert max(img.size) <= fotos.LADO_MAXIMO
    assert len(pronta) <= fotos.ALVO_BYTES


@pytest.mark.parametrize("formato", ["PNG", "WEBP"])
def test_preparo_aceita_png_e_webp(formato):
    img = Image.open(io.BytesIO(fotos.preparar(_imagem(formato=formato))))
    assert img.format == "JPEG"


def test_preparo_aceita_png_transparente():
    img = Image.open(io.BytesIO(fotos.preparar(_imagem(formato="PNG", modo="RGBA"))))
    assert img.mode == "RGB"


def test_preparo_aceita_heic_do_iphone():
    pillow_heif = pytest.importorskip("pillow_heif")
    saida = io.BytesIO()
    try:
        pillow_heif.from_pillow(Image.new("RGB", (300, 200), (10, 200, 10))).save(saida, format="HEIF")
    except Exception as erro:                          # sem codificador HEIC nesta máquina
        pytest.skip(f"sem codificador HEIC: {erro}")
    img = Image.open(io.BytesIO(fotos.preparar(saida.getvalue())))
    assert img.format == "JPEG" and img.size == (300, 200)


@pytest.mark.parametrize("dados", [b"", b"isto nao e uma foto", b"%PDF-1.4 falso", _imagem(formato="GIF")])
def test_preparo_recusa_o_que_nao_e_foto_pelo_conteudo(dados):
    with pytest.raises(fotos.FotoRecusada) as erro:
        fotos.preparar(dados)
    assert erro.value.args[0] == fotos.MSG_NAO_E_IMAGEM


def test_preparo_recusa_acima_de_15_mb():
    with pytest.raises(fotos.FotoRecusada) as erro:
        fotos.preparar(b"\xff\xd8\xff" + b"0" * (fotos.MAX_BYTES + 1))
    assert erro.value.args[0] == fotos.MSG_GRANDE


# ------------------------------------------------------------ depósito local, por loja

def test_guardar_da_nome_aleatorio_por_loja_e_le_de_volta(duas_lojas):
    a, b = fotos.guardar(1, _imagem()), fotos.guardar(1, _imagem())
    assert a != b and a.startswith("deposito:loja-1/") and a.endswith(".jpg")
    assert len(fotos.nome_da_ref(a)) >= 30
    assert fotos.ler(1, a)[:3] == bytes([0xFF, 0xD8, 0xFF])


def test_uma_loja_nunca_le_nem_apaga_foto_de_outra(duas_lojas):
    ref = fotos.guardar(1, _imagem())
    with pytest.raises(deposito.FotoNaoEncontrada):
        fotos.ler(2, ref)
    assert fotos.apagar(2, ref) is False
    assert fotos.existe(1, ref)
    # e a loja 2 não "adota" a foto da 1 pelo nome
    with pytest.raises(deposito.FotoNaoEncontrada):
        fotos.ler(2, fotos.ref_de(2, fotos.nome_da_ref(ref)))


@pytest.mark.parametrize("chave", ["../x.jpg", "loja-1/../../banco.py", "loja-1/a.jpg", "loja-0/" + "a" * 30 + ".jpg",
                                   "loja-1/" + "a" * 30 + ".png", "/etc/passwd", "loja-1\\" + "a" * 30 + ".jpg"])
def test_deposito_local_recusa_chave_fora_do_padrao(chave, tmp_path):
    d = deposito.DepositoLocal(tmp_path)
    with pytest.raises(deposito.FotoNaoEncontrada):
        d.guardar(chave, b"x")


def test_apagar_tira_do_deposito(duas_lojas):
    ref = fotos.guardar(1, _imagem())
    assert fotos.apagar(1, ref) and not fotos.existe(1, ref)


# ------------------------------------------------------------ depósito nuvem (falso, offline)

def _nuvem(pedidos, status=200, conteudo=b"bytes"):
    def responder(pedido: httpx.Request):
        pedidos.append(pedido)
        return httpx.Response(status, content=conteudo if pedido.method == "GET" else b"")
    return deposito.DepositoNuvem("https://conta.r2.exemplo.example", "fotos", "CHAVEID", "segredo-falso",
                                  "https://fotos.loja.example", transporte=httpx.MockTransport(responder))


def test_nuvem_assina_e_guarda_le_apaga():
    pedidos = []
    d = _nuvem(pedidos)
    chave = "loja-1/" + "a" * 32 + ".jpg"
    d.guardar(chave, b"jpeg")
    assert d.ler(chave) == b"bytes"
    d.apagar(chave)
    assert [p.method for p in pedidos] == ["PUT", "GET", "DELETE"]
    put = pedidos[0]
    assert str(put.url) == f"https://conta.r2.exemplo.example/fotos/{chave}"
    assert put.headers["authorization"].startswith("AWS4-HMAC-SHA256 Credential=CHAVEID/")
    assert "segredo-falso" not in put.headers["authorization"]
    assert put.headers["content-type"] == "image/jpeg" and put.headers["x-amz-content-sha256"]
    assert d.endereco(chave) == f"https://fotos.loja.example/{chave}"


def test_nuvem_que_recusa_vira_falha():
    d = _nuvem([], status=403)
    with pytest.raises(deposito.FalhaNoDeposito):
        d.guardar("loja-1/" + "a" * 32 + ".jpg", b"x")


def test_escolha_da_tomada_pelo_ambiente(monkeypatch):
    assert isinstance(deposito.deposito(), deposito.DepositoLocal)
    monkeypatch.setenv("FOTOS_DEPOSITO", "nuvem")
    for v in deposito.VARIAVEIS_NUVEM:
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("FOTOS_NUVEM_SEGREDO", "nao-pode-aparecer")
    with pytest.raises(deposito.DepositoMalConfigurado) as erro:
        deposito.deposito()
    assert "nao-pode-aparecer" not in str(erro.value)
    for v, valor in zip(deposito.VARIAVEIS_NUVEM, ("https://r2.example", "b", "id", "s", "https://pub.example")):
        monkeypatch.setenv(v, valor)
    nuvem = deposito.deposito()
    assert isinstance(nuvem, deposito.DepositoNuvem)
    # o endereço público só existe na nuvem; fora daqui ninguém sabe qual tomada está ligada
    assert fotos.endereco_publico(1, fotos.ref_de(1, "a" * 32 + ".jpg")).startswith("https://pub.example/loja-1/")


# ------------------------------------------------------------ link colado (baixador de verdade, rede falsa)

def _transporte(respostas):
    def responder(pedido):
        return respostas[str(pedido.url)]
    return httpx.MockTransport(responder)


def test_link_https_e_baixado_e_preparado(monkeypatch):
    monkeypatch.setattr(fotos, "_endereco_proibido", lambda host: False)
    t = _transporte({"https://fotos.loja.example/a.jpg": httpx.Response(200, content=_imagem())})
    dados = fotos._baixar_link("https://fotos.loja.example/a.jpg", transporte=t)
    assert Image.open(io.BytesIO(dados)).format == "JPEG"


@pytest.mark.parametrize("url", ["http://fotos.loja.example/a.jpg", "ftp://x/a.jpg", "https://usuario:senha@x.example/a.jpg",
                                 "https://127.0.0.1/a.jpg", "https://localhost/a.jpg", "https://10.0.0.5/a.jpg",
                                 "https://192.168.1.10/a.jpg", "https://169.254.169.254/latest/", "https://[::1]/a.jpg",
                                 "https://x.example:8443/a.jpg", "file:///C:/Windows/win.ini"])
def test_link_inseguro_e_recusado_sem_baixar(url):
    pedidos = []

    def responder(pedido):
        pedidos.append(pedido)
        return httpx.Response(200, content=_imagem())
    with pytest.raises(fotos.FotoRecusada):
        fotos._baixar_link(url, transporte=httpx.MockTransport(responder))
    assert pedidos == []


def test_redirecionamento_para_a_rede_interna_e_recusado(monkeypatch):
    monkeypatch.setattr(fotos, "_endereco_proibido", lambda host: host != "fotos.loja.example")
    t = _transporte({"https://fotos.loja.example/a.jpg":
                     httpx.Response(302, headers={"location": "https://interno.local/segredo.jpg"})})
    with pytest.raises(fotos.FotoRecusada):
        fotos._baixar_link("https://fotos.loja.example/a.jpg", transporte=t)


@pytest.mark.parametrize("resposta", [httpx.Response(404), httpx.Response(200, headers={"content-length": str(fotos.MAX_BYTES + 1)}),
                                      httpx.Response(200, content=b"0" * (fotos.MAX_BYTES + 10))])
def test_link_que_falha_ou_e_grande_demais(monkeypatch, resposta):
    monkeypatch.setattr(fotos, "_endereco_proibido", lambda host: False)
    with pytest.raises(fotos.FotoRecusada):
        fotos._baixar_link("https://fotos.loja.example/a.jpg",
                           transporte=_transporte({"https://fotos.loja.example/a.jpg": resposta}))


def test_endereco_interno_detectado_pelo_ip():
    for host in ("127.0.0.1", "10.1.2.3", "172.16.0.1", "192.168.0.1", "169.254.1.1", "0.0.0.0", "::1", "localhost"):
        assert fotos._endereco_proibido(host), host


# ------------------------------------------------------------ normalizar (o que a tela manda)

def test_normalizar_endereco_da_loja_link_e_ordem(duas_lojas):
    antiga = fotos.guardar(1, _imagem())
    endereco = fotos.endereco_para_painel(1, antiga)
    assert endereco.startswith("/api/v1/fotos/")
    refs, novas = fotos.normalizar(1, ["https://fotos.loja.example/nova.jpg", endereco])
    assert refs[1] == antiga and refs[0] == novas[0] and len(novas) == 1


def test_normalizar_recusa_endereco_de_outra_loja(duas_lojas):
    da_b = fotos.guardar(2, _imagem())
    with pytest.raises(fotos.FotoRecusada):
        fotos.normalizar(1, [fotos.endereco_para_painel(2, da_b)])


def test_normalizar_desfaz_as_novas_se_uma_falhar(duas_lojas, tmp_path):
    with pytest.raises(fotos.FotoRecusada):
        fotos.normalizar(1, ["https://boa.example/1.jpg", "https://nao-abre.com.br/2.jpg"])
    import os, pathlib
    pasta = pathlib.Path(os.environ["FOTOS_PASTA"]) / "loja-1"
    assert not pasta.exists() or list(pasta.iterdir()) == []


def test_normalizar_limite_de_20(duas_lojas):
    with pytest.raises(fotos.FotoRecusada) as erro:
        fotos.normalizar(1, [f"https://x.example/{i}.jpg" for i in range(21)])
    assert erro.value.args[0] == fotos.MSG_DEMAIS


# ------------------------------------------------------------ gravação do estoque (caminho único)

def _carro(fotos_texto, loja=1):
    from app import estoque
    with como("Teste", "operador", "painel"):
        return estoque.adicionar_carro("Fiat", "Argo", 2022, 1000, "Branco", "Manual", 70000,
                                       fotos=fotos_texto, loja_id=loja)


def test_link_colado_no_estoque_vira_foto_do_deposito():
    carro = _carro("https://fotos.loja.example/argo.jpg")
    guardado = _um("SELECT fotos FROM estoque WHERE id = ?", (carro,))
    assert guardado.startswith("deposito:loja-1/") and "example" not in guardado


def test_link_que_nao_abre_nao_grava_nada():
    from app import estoque
    antes = _um("SELECT COUNT(*) FROM estoque")
    with pytest.raises(estoque.FotosInvalidas) as erro:
        _carro("https://nao-abre.com.br/a.jpg")
    assert "Não consegui baixar a foto" in str(erro.value)
    assert _um("SELECT COUNT(*) FROM estoque") == antes


def test_foto_que_sai_do_carro_sai_do_deposito():
    from app import estoque
    carro = _carro("https://a.example/1.jpg, https://a.example/2.jpg")
    refs = fotos.separar(_um("SELECT fotos FROM estoque WHERE id = ?", (carro,)))
    with como("Teste", "operador", "painel"):
        estoque.atualizar_carro(carro, "Fiat", "Argo", 2022, 1000, "Branco", "Manual", 70000, "disponivel",
                                fotos=refs[1], loja_id=1)
    assert not fotos.existe(1, refs[0]) and fotos.existe(1, refs[1])


# ------------------------------------------------------------ o Léo só manda foto do depósito

def test_ferramenta_ignora_link_de_terceiros():
    from tools.enviar_fotos import enviar_fotos
    _sql("INSERT INTO estoque (loja_id, marca, modelo, ano, km, cor, cambio, preco, status, fotos) "
         "VALUES (1, 'Fiat', 'Uno', 2015, 1, 'Branco', 'Manual', 1, 'disponivel', 'https://terceiro.example/uno.jpg')")
    texto, artefato = enviar_fotos.func(modelo="Uno", loja_id=1)
    assert artefato == [] and "não tem fotos" in texto
    carro = _carro("https://fotos.loja.example/argo.jpg")
    texto, artefato = enviar_fotos.func(modelo="Argo", loja_id=1)
    assert artefato["urls"] == fotos.separar(_um("SELECT fotos FROM estoque WHERE id = ?", (carro,)))


# ------------------------------------------------------------ trava da foto falhada

def test_corrigir_texto_tira_o_que_fala_de_foto_e_mantem_o_resto():
    texto = "Temos o Corolla 2021!\n\n- Automático\n- 48 mil km\n\nSeguem as fotos dele. Quer marcar uma visita?"
    corrigido = __import__("app.envio_fotos", fromlist=["x"]).corrigir_texto(texto)
    assert "fotos dele" not in corrigido and "Quer marcar uma visita?" in corrigido
    assert corrigido.startswith("Temos o Corolla 2021!\n\n- Automático\n- 48 mil km")
    assert corrigido.endswith("Vou pedir para a equipe te mandar as fotos.")


def _fala_do_leo(lead, texto, loja=1, canal="telegram"):
    _sql("INSERT INTO mensagens (lead_id, loja_id, canal, direcao, tipo, conteudo) VALUES (?, ?, ?, 'leo', 'texto', ?)",
         (lead, loja, canal, texto))


class BotFalso:
    def __init__(self, recusa=False):
        self.recusa, self.fotos, self.textos = recusa, [], []

    async def send_photo(self, chat_id, photo):
        if self.recusa:
            raise RuntimeError("Telegram recusou a foto")
        self.fotos.append(photo)

    async def send_message(self, chat_id, text):
        self.textos.append(text)

    async def send_chat_action(self, chat_id, action):
        pass


def _resultado(texto, refs):
    from app.core.turno import ResultadoTurno
    return ResultadoTurno(texto=texto, midias=refs)


def _telegram(bot):
    from app.channels.telegram import CanalTelegram
    canal = CanalTelegram(bot)
    canal.respiro_s = canal.pausa_entre_bolhas = 0
    return canal


def test_telegram_manda_os_bytes_do_deposito_e_o_texto_original():
    from app.channels.base import enviar_resultado
    ref = fotos.guardar(1, _imagem())
    bot = BotFalso()
    _fala_do_leo("777", "Aqui estão as fotos do Argo!")
    falhas = asyncio.run(enviar_resultado(_telegram(bot), "777", _resultado("Aqui estão as fotos do Argo!", [ref]), loja_id=1))
    assert falhas == [] and bot.fotos == [fotos.ler(1, ref)]
    assert bot.textos == ["Aqui estão as fotos do Argo!"]
    assert _um("SELECT COUNT(*) FROM handoffs") == 0


def test_telegram_que_recusa_a_foto_nao_diz_que_enviou_e_abre_chamado():
    from app.channels.base import enviar_resultado
    ref = fotos.guardar(1, _imagem())
    bot = BotFalso(recusa=True)
    _fala_do_leo("778", "Segue a foto do Argo! Ele está impecável.")
    falhas = asyncio.run(enviar_resultado(_telegram(bot), "778",
                                          _resultado("Segue a foto do Argo! Ele está impecável.", [ref]), loja_id=1))
    assert falhas == [ref]
    enviado = " ".join(bot.textos)
    assert "Segue a foto" not in enviado and "Vou pedir para a equipe te mandar as fotos." in enviado
    motivo = _um("SELECT motivo FROM handoffs WHERE lead_id = '778' AND estado = 'aguardando_humano'")
    assert motivo and "fotos do carro não chegaram" in motivo
    gravada = _um("SELECT conteudo FROM mensagens WHERE lead_id = '778' AND direcao = 'leo' ORDER BY id DESC LIMIT 1")
    assert "Segue a foto" not in gravada and gravada.endswith("te mandar as fotos.")


def _whatsapp(monkeypatch, aceita=True):
    from app.api import webhook as wh
    enviados = {"fotos": [], "textos": []}

    async def foto(numero, url, **kw):
        enviados["fotos"].append(url)
        return aceita

    async def texto(numero, t, atraso=0, **kw):
        enviados["textos"].append(t)
    monkeypatch.setattr(wh, "enviar_foto_whatsapp", foto)
    monkeypatch.setattr(wh, "enviar_resposta_humanizada", texto)
    return wh, enviados


def test_whatsapp_com_deposito_local_e_falha_honesta(monkeypatch):
    wh, enviados = _whatsapp(monkeypatch)
    ref = fotos.guardar(1, _imagem())
    _fala_do_leo("5581999", "Mandei as fotos do Argo!", canal="whatsapp")
    falhas = asyncio.run(wh._enviar_resultado("5581999", _resultado("Mandei as fotos do Argo!", [ref]), 0, 1))
    assert falhas == [ref] and enviados["fotos"] == []          # sem endereço público: nem tenta
    assert enviados["textos"] == ["Vou pedir para a equipe te mandar as fotos."]
    assert _um("SELECT COUNT(*) FROM handoffs WHERE lead_id = '5581999'") == 1


def test_whatsapp_na_nuvem_que_recusa_a_foto(monkeypatch):
    wh, enviados = _whatsapp(monkeypatch, aceita=False)
    monkeypatch.setattr(fotos, "endereco_publico", lambda loja, r: "https://pub.example/" + r.rsplit("/", 1)[-1])
    ref = fotos.guardar(1, _imagem())
    _fala_do_leo("5581888", "Olha as fotos!", canal="whatsapp")
    falhas = asyncio.run(wh._enviar_resultado("5581888", _resultado("Olha as fotos! Quer agendar?", [ref]), 0, 1))
    assert falhas == [ref] and len(enviados["fotos"]) == 1
    assert enviados["textos"] == ["Quer agendar?\n\nVou pedir para a equipe te mandar as fotos."]


def test_whatsapp_na_nuvem_que_aceita_manda_o_texto_original(monkeypatch):
    wh, enviados = _whatsapp(monkeypatch, aceita=True)
    monkeypatch.setattr(fotos, "endereco_publico", lambda loja, r: "https://pub.example/" + r.rsplit("/", 1)[-1])
    ref = fotos.guardar(1, _imagem())
    falhas = asyncio.run(wh._enviar_resultado("5581777", _resultado("Olha as fotos!", [ref]), 0, 1))
    assert falhas == [] and enviados["textos"] == ["Olha as fotos!"]
    assert enviados["fotos"][0].startswith("https://pub.example/")


def test_simulador_recusa_foto_de_outra_loja(duas_lojas):
    from app.channels.base import enviar_resultado
    from app.channels.simulador import CanalSimulador
    canal = CanalSimulador()
    canal.respiro_s = canal.pausa_entre_bolhas = 0
    da_b = fotos.guardar(2, _imagem())
    falhas = asyncio.run(enviar_resultado(canal, "sim-1", _resultado("Foto!", [da_b]), loja_id=1))
    assert falhas == [da_b] and ("midia", da_b) not in canal.enviadas


# ------------------------------------------------------------ migração das fotos atuais

def test_migracao_leva_arquivo_e_link_e_lista_as_falhas(tmp_path, capsys):
    from scripts import migrar_fotos
    arquivo = tmp_path / "demo.png"
    arquivo.write_bytes(_imagem(formato="PNG"))
    texto = f"{arquivo}, {arquivo.resolve().as_uri()}, https://fotos.loja.example/a.jpg, https://nao-abre.com.br/b.jpg, http://velho.example/c.jpg"
    _sql("INSERT INTO estoque (loja_id, marca, modelo, ano, km, cor, cambio, preco, status, fotos) "
         "VALUES (1, 'Fiat', 'Uno', 2015, 1, 'Branco', 'Manual', 1, 'disponivel', ?)", (texto,))
    assert migrar_fotos.main([]) == 0
    saida = capsys.readouterr().out
    assert "Fotos levadas para o depósito: 3" in saida and "nao-abre.com.br" in saida and "velho.example" in saida
    novo = fotos.separar(_um("SELECT fotos FROM estoque WHERE modelo = 'Uno'"))
    assert sum(1 for f in novo if f.startswith("deposito:loja-1/")) == 3
    assert "https://nao-abre.com.br/b.jpg" in novo and "http://velho.example/c.jpg" in novo   # nada apagado
    assert arquivo.exists()
    # rodar de novo não duplica
    migrar_fotos.main([])
    assert fotos.separar(_um("SELECT fotos FROM estoque WHERE modelo = 'Uno'")) == novo


# ------------------------------------------------------------ rota de fotos do painel

@pytest.fixture
def cliente():
    from app.api_painel.main import criar_app
    with TestClient(criar_app(), base_url="https://testserver") as c:
        yield c


def test_rota_entrega_so_foto_da_loja_da_sessao(cliente, duas_lojas):
    from tests.test_c2c_conversas import _entrar
    ref = fotos.guardar(1, _imagem())
    url = "/api/v1/fotos/" + fotos.nome_da_ref(ref)
    r = cliente.get(url, headers=_entrar(loja=1, papel="dono"))
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert cliente.get(url, headers=_entrar(loja=2, papel="dono")).status_code == 404
    assert cliente.get(url, headers=_entrar(loja=1, papel="vendedor")).status_code == 403
    for ruim in ("..%2F..%2Fbanco.py", "..%5Cbanco.py", "nao-existe.jpg", "a" * 30 + ".png"):
        assert cliente.get("/api/v1/fotos/" + ruim, headers=_entrar(loja=1, papel="dono")).status_code == 404
