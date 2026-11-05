"""
S2 (Fase 3): Nova loja e Resumo com checklist.
- loja nova nasce em teste, com cidade e fuso confirmados, e vai ao Registro;
- item automático marca sozinho; item manual só pelo operador, com Registro;
- sem os obrigatórios não dá para colocar no ar, na camada app/ (não só no botão);
- colocar no ar pede o nome da loja e grava no Registro;
- duas lojas não se misturam; migração 13 sobe da 12 sem perder nada.
Tudo offline, banco temporário do conftest (ator "Teste", operador, painel).
"""
import pytest

import banco
from banco import conectar
from app import implantacao, lojas_admin
from app.ator import SemAtor, como, sem_ator
from app.canais import cadastrar_canal
from app.estado_loja import SoOperador, cadastrar_numero_de_teste, esta_no_ar
from app.estoque import adicionar_carro
from app.lojas import carregar_loja, pendentes, salvar_config
from app.registro import ACOES_RELEVANTES
from app.registro_leitura import ROTULOS
from app.usuarios import criar_usuario


def _um(sql, parametros=()):
    conexao = conectar()
    try:
        return conexao.execute(sql, parametros).fetchone()[0]
    finally:
        conexao.close()


def _nova(nome="Loja Nova"):
    return lojas_admin.criar_loja(nome, "Caruaru", "America/Recife", "veiculos")


def _item(loja, chave):
    return next(i for i in implantacao.checklist(loja) if i["chave"] == chave)


def _preparar(loja, monkeypatch, bot="123456"):
    """Deixa todos os obrigatórios prontos."""
    salvar_config(loja, {"nome_agente": "Léo", "tom": "simples, cordial e direto",
                         "atendimento.horario_humano": "09:00-18:00",
                         "atendimento.dias_humano": [0, 1, 2, 3, 4, 5]}, "Samuel")
    criar_usuario(loja, "Ana", "vendedor", contato_telegram="123456789")
    adicionar_carro("Hyundai", "HB20", 2020, 40000, "Prata", "Manual", 60000.0, loja_id=loja)
    variavel = f"TOKEN_S2_LOJA{loja}"
    monkeypatch.setenv(variavel, f"{bot}:ABC-falso")
    cadastrar_canal(loja, "telegram", bot, variavel)
    cadastrar_numero_de_teste(loja, "telegram", "555111", "Samuel")
    implantacao.marcar_item(loja, "teste_conversa")
    implantacao.marcar_item(loja, "plano_contrato")


# ------------------------------------------------------------ criar loja

def test_loja_nova_nasce_em_teste_e_vai_ao_registro():
    loja = _nova()
    assert not esta_no_ar(loja)
    l = carregar_loja(loja)
    assert (l.get("cidade"), l.get("fuso")) == ("Caruaru", "America/Recife")
    assert "cidade" not in pendentes(l) and "fuso" not in pendentes(l)
    assert _um("SELECT COUNT(*) FROM registro_acoes WHERE acao = 'criar_loja' "
               "AND loja_id = ?", (loja,)) == 1


@pytest.mark.parametrize("nome, cidade, fuso, segmento", [
    ("", "Caruaru", "America/Recife", "veiculos"),
    ("Loja", "", "America/Recife", "veiculos"),
    ("Loja", "Caruaru", "Marte/Base", "veiculos"),
    ("Loja", "Caruaru", "America/Recife", "naoexiste"),
])
def test_criar_loja_recusa_dado_ruim_e_nada_fica(nome, cidade, fuso, segmento):
    antes = _um("SELECT COUNT(*) FROM lojas")
    with pytest.raises(lojas_admin.LojaInvalida):
        lojas_admin.criar_loja(nome, cidade, fuso, segmento)
    assert _um("SELECT COUNT(*) FROM lojas") == antes


def test_so_o_operador_cria_loja():
    antes = _um("SELECT COUNT(*) FROM lojas")
    with como("Ana", "cliente", "painel", loja_id=1), pytest.raises(SoOperador):
        _nova()
    with sem_ator(), pytest.raises(SemAtor):
        _nova()
    assert _um("SELECT COUNT(*) FROM lojas") == antes


# ------------------------------------------------------------ checklist

def test_item_automatico_marca_sozinho():
    loja = _nova()
    assert _item(loja, "loja_criada")["feito"] is True
    assert _item(loja, "estoque")["feito"] is False
    adicionar_carro("Fiat", "Uno", 2015, 90000, "Branco", "Manual", 25000.0, loja_id=loja)
    assert _item(loja, "estoque")["feito"] is True


def test_canal_sem_chave_no_servidor_nao_conta(monkeypatch):
    loja = _nova()
    monkeypatch.delenv("TOKEN_S2_SEM", raising=False)
    cadastrar_canal(loja, "telegram", "777777", "TOKEN_S2_SEM")
    assert _item(loja, "canal")["feito"] is False


def test_item_manual_so_pelo_operador_e_so_uma_vez():
    loja = _nova()
    with pytest.raises(implantacao.ItemInvalido):
        implantacao.marcar_item(loja, "estoque")        # automático não se marca
    with como("Ana", "cliente", "painel", loja_id=loja), pytest.raises(SoOperador):
        implantacao.marcar_item(loja, "teste_conversa")
    assert implantacao.marcar_item(loja, "teste_conversa") is True
    assert implantacao.marcar_item(loja, "teste_conversa") is False
    assert _um("SELECT COUNT(*) FROM registro_acoes WHERE acao = 'marcar_item_implantacao'") == 1
    item = _item(loja, "teste_conversa")
    assert item["feito"] and item["marcado_por"] == "Teste"


# ------------------------------------------------------------ colocar no ar

def test_sem_obrigatorios_nao_vai_ao_ar_mesmo_chamando_direto():
    loja = _nova()
    with pytest.raises(implantacao.ChecklistIncompleto) as erro:
        implantacao.colocar_no_ar(loja, "Loja Nova")
    assert "Estoque" in erro.value.faltando
    assert not esta_no_ar(loja)


def test_nome_errado_nao_coloca_no_ar(monkeypatch):
    loja = _nova()
    _preparar(loja, monkeypatch)
    with pytest.raises(implantacao.ConfirmacaoErrada):
        implantacao.colocar_no_ar(loja, "Outra loja")
    assert not esta_no_ar(loja)


def test_recomendado_e_opcional_nao_bloqueiam(monkeypatch):
    loja = _nova()
    _preparar(loja, monkeypatch)
    assert _item(loja, "conhecimento")["feito"] is False
    assert implantacao.faltando_para_o_ar(loja) == []


def test_completo_vai_ao_ar_e_grava_no_registro(monkeypatch):
    loja = _nova()
    _preparar(loja, monkeypatch)
    assert implantacao.colocar_no_ar(loja, "  loja nova ") is True
    assert esta_no_ar(loja)
    assert implantacao.colocar_no_ar(loja, "Loja Nova") is False
    assert _um("SELECT COUNT(*) FROM registro_acoes WHERE acao = 'colocar_no_ar' "
               "AND loja_id = ?", (loja,)) == 1


def test_cliente_nao_coloca_no_ar(monkeypatch):
    loja = _nova()
    _preparar(loja, monkeypatch)
    with como("Ana", "cliente", "painel", loja_id=loja), pytest.raises(SoOperador):
        implantacao.colocar_no_ar(loja, "Loja Nova")
    assert not esta_no_ar(loja)


# ------------------------------------------------------------ duas lojas

def test_duas_lojas_nao_se_misturam(monkeypatch):
    a, b = _nova("Loja A"), _nova("Loja B")
    _preparar(a, monkeypatch, bot="111111")
    assert implantacao.pode_colocar_no_ar(a) is True
    assert implantacao.pode_colocar_no_ar(b) is False
    assert _item(b, "teste_conversa")["feito"] is False
    implantacao.colocar_no_ar(a, "Loja A")
    assert esta_no_ar(a) and not esta_no_ar(b)


# ------------------------------------------------------------ registro

def test_acoes_novas_estao_na_lista_e_tem_rotulo():
    for acao in ("criar_loja", "marcar_item_implantacao", "desmarcar_item_implantacao"):
        assert acao in ACOES_RELEVANTES and acao in ROTULOS


# ------------------------------------------------------------ migração 13

@pytest.fixture
def banco_v12(monkeypatch, tmp_path):
    monkeypatch.setattr(banco, "CAMINHO_BANCO", str(tmp_path / "v12.db"))
    completas = dict(banco.MIGRACOES)
    monkeypatch.setattr(banco, "MIGRACOES", {v: s for v, s in completas.items() if v <= 12})
    banco.criar_tabelas()
    conexao = conectar()
    try:
        conexao.execute("INSERT INTO lojas (nome) VALUES ('Loja Antiga')")
        conexao.commit()
        assert conexao.execute("PRAGMA user_version").fetchone()[0] == 12
    finally:
        conexao.close()
    monkeypatch.setattr(banco, "MIGRACOES", completas)


def test_sobe_da_v12_sem_perder_loja(banco_v12):
    banco.migrar()
    assert _um("PRAGMA user_version") == 13
    assert _um("SELECT COUNT(*) FROM lojas WHERE nome = 'Loja Antiga'") == 1
    assert _um("SELECT COUNT(*) FROM checklist_implantacao") == 0


def test_rodar_de_novo_nao_perde_item_marcado():
    loja = _nova()
    implantacao.marcar_item(loja, "teste_conversa")
    conexao = conectar()
    try:
        conexao.execute("PRAGMA user_version = 3")
        conexao.commit()
    finally:
        conexao.close()
    banco.migrar()
    assert _um("PRAGMA user_version") == banco.VERSAO_SCHEMA
    assert _um("SELECT COUNT(*) FROM checklist_implantacao") == 1
