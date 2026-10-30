"""
Testes da Etapa 2, Bloco 6C: reativação de contatos antigos da base.
Só quem autorizou e está parado, uma mensagem por modelo aprovado, limite
compartilhado com o remarketing, reconferência antes de enviar, lojas separadas.
"""
import py_compile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import banco
from banco import conectar
from app import reativacao, templates
from app.elegibilidade import enviados_no_mes
from app.importacao import importar, ler_planilha
from app.interesse import registrar_situacao
from app.jobs.reativacao import rodar_reativacao
from app.lojas import criar_loja, salvar_config
from app.relogio import para_banco
from app.retomada import retomada_recente

RAIZ = Path(__file__).resolve().parent.parent
HOJE = date(2026, 10, 30)
AGORA = datetime(2026, 10, 30, 13, 0, tzinfo=timezone.utc)   # sexta, 10h no Recife
DOMINGO = datetime(2026, 11, 1, 13, 0, tzinfo=timezone.utc)
ANA, CARLOS = "5581999998888", "5581988887777"
CSV = (
    "nome;telefone;carro;data_compra;pagamento\n"
    "Ana Souza;(81) 99999-8888;Honda Civic 2019;10/01/2024;à vista\n"
    "Carlos Lima;(81) 98888-7777;;;\n"
)


class EnviadorFalso:
    def __init__(self, ok=True):
        self.ok = ok
        self.chamadas = []

    async def modelo(self, loja_id, lead_id, modelo, valores):
        self.chamadas.append((lead_id, modelo.nome, valores))
        return SimpleNamespace(ok=self.ok, detalhe="" if self.ok else "falha de teste")

    async def texto(self, *args):
        raise AssertionError("reativação nunca manda texto livre")


def _ligar(loja_id=1, limite=30):
    salvar_config(loja_id, {"modulos.remarketing": True, "remarketing.limite_mensal": limite}, "Samuel")


def _importar(texto=CSV, loja_id=1, consentimento=True):
    return importar(loja_id, ler_planilha(texto.encode("utf-8"), hoje=HOJE), usuario="Samuel",
                    consentimento=consentimento, arquivo="base.csv")


def _montar(loja_id=1, **kw):
    kw.setdefault("usuario", "Samuel")
    kw.setdefault("agora", AGORA)
    return reativacao.montar_fila(loja_id, **kw)


def _rodar(real=False, enviador=None, agora=AGORA, lojas=(1,)):
    return rodar_reativacao(agora, envio_real=real, enviador=enviador or EnviadorFalso(),
                            pausa_s=0, lojas=list(lojas))


def _linha(telefone, loja_id=1):
    c = conectar()
    try:
        l = c.execute("SELECT * FROM reativacao WHERE loja_id = ? AND telefone = ? ORDER BY id DESC LIMIT 1",
                      (loja_id, telefone)).fetchone()
    finally:
        c.close()
    return dict(l) if l else None


def _executar(sql, parametros=()):
    c = conectar()
    try:
        c.execute(sql, parametros)
        c.commit()
    finally:
        c.close()


def _msg_cliente(lead_id, quando):
    _executar("INSERT INTO mensagens (lead_id, loja_id, canal, direcao, tipo, conteudo, criado_em) "
              "VALUES (?, 1, 'whatsapp', 'cliente', 'texto', 'oi', ?)", (lead_id, para_banco(quando)))


def _aprovar():
    for nome in (reativacao.MODELO_CLIENTE, reativacao.MODELO_CONTATO):
        templates.registrar_status(1, nome, "aprovado")


# ------------------------------------------------------------ estrutura

def test_migracao_v7_cria_a_tabela():
    c = conectar()
    try:
        assert banco.versao_schema(c) == banco.VERSAO_SCHEMA >= 7
        tabelas = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        c.close()
    assert "reativacao" in tabelas


def test_modelos_de_reativacao_existem():
    for nome in (reativacao.MODELO_CLIENTE, reativacao.MODELO_CONTATO):
        m = templates.modelo_do_segmento("veiculos", nome)
        assert m.categoria == "marketing"
    m = templates.modelo_do_segmento("veiculos", reativacao.MODELO_CLIENTE)
    texto = templates.preencher(m, {"nome": "Ana", "agente": "Léo", "loja": "X", "carro": "Civic"})
    assert "Civic" in texto


# ------------------------------------------------------------ montar a fila

def test_modulo_desligado_recusa():
    _importar()
    with pytest.raises(reativacao.ReativacaoInvalida):
        _montar()


def test_monta_fila_com_quem_esta_parado():
    _ligar()
    _importar()
    r = _montar(meses=6)
    assert r["na_fila"] == 2
    assert _linha(ANA)["estado"] == "na_fila" and _linha(ANA)["meses_inativo"] == 6


def test_sem_autorizacao_nao_entra():
    _ligar()
    _importar(consentimento=False)
    r = _montar()
    assert r["na_fila"] == 0 and r["ignorados"] == {"sem_consentimento": 2}


def test_compra_recente_fica_de_fora():
    _ligar()
    _importar(CSV.replace("10/01/2024", "01/09/2026"))
    r = _montar(meses=6)
    assert r["na_fila"] == 1 and r["ignorados"] == {"comprou_recente": 1}


def test_conversa_recente_fica_de_fora():
    _ligar()
    _importar()
    _msg_cliente("558199998888", AGORA - timedelta(days=20))      # número sem o 9, como a Meta manda
    r = _montar(meses=6)
    assert r["na_fila"] == 1 and r["ignorados"] == {"conversou_recente": 1}


def test_publico_escolhido():
    _ligar()
    _importar()
    assert _montar(publico="nunca_compraram")["na_fila"] == 1
    assert _linha(CARLOS) and _linha(ANA) is None
    assert _montar(publico="ja_compraram")["na_fila"] == 1
    assert _linha(ANA)["estado"] == "na_fila"


def test_montar_de_novo_nao_duplica():
    _ligar()
    _importar()
    _montar()
    r = _montar()
    assert r["na_fila"] == 0 and r["ignorados"] == {"ja_na_fila": 2}


def test_quem_pediu_para_nao_ser_procurado_fica_de_fora():
    _ligar()
    _importar()
    registrar_situacao(1, ANA, "nao_contatar", "pediu", "whatsapp")
    r = _montar()
    assert r["na_fila"] == 1 and r["ignorados"] == {"nao_contatar": 1}


def test_lojas_separadas():
    loja_b = criar_loja("Loja B")
    _ligar()
    _ligar(loja_b)
    _importar()
    assert _montar(loja_b)["na_fila"] == 0
    assert _montar()["na_fila"] == 2
    assert _rodar(lojas=(loja_b,))["simulado"] == 0


# ------------------------------------------------------------ job

def test_simulacao_nao_envia_e_mostra_o_texto():
    _ligar()
    _importar()
    _montar()
    enviador = EnviadorFalso()
    t = _rodar(enviador=enviador)
    assert t["simulado"] == 2 and enviador.chamadas == []
    assert "Ana" in _linha(ANA)["texto"] and "Honda Civic 2019" in _linha(ANA)["texto"]
    assert _linha(CARLOS)["modelo"] == reativacao.MODELO_CONTATO
    assert _rodar()["simulado"] == 0                   # simulação não repete


def test_real_sem_modelo_aprovado_nao_envia():
    _ligar()
    _importar()
    _montar()
    enviador = EnviadorFalso()
    t = _rodar(real=True, enviador=enviador)
    assert t["bloqueado"] == 2 and enviador.chamadas == []
    assert _linha(ANA)["motivo"] == "modelo_nao_aprovado"


def test_real_envia_grava_conversa_custo_e_nao_repete():
    _ligar()
    _importar()
    _aprovar()
    _montar()
    enviador = EnviadorFalso()
    t = _rodar(real=True, enviador=enviador)
    assert t["enviado"] == 2 and len(enviador.chamadas) == 2
    assert enviados_no_mes(1, AGORA) == 2
    c = conectar()
    try:
        assert c.execute("SELECT COUNT(*) FROM mensagens WHERE autor = 'reativacao'").fetchone()[0] == 2
        assert c.execute("SELECT COUNT(*) FROM uso_custos WHERE tipo = 'reativacao'").fetchone()[0] == 2
    finally:
        c.close()
    r = _montar(agora=AGORA + timedelta(days=1))
    assert r["na_fila"] == 0 and r["ignorados"] == {"reativado_recente": 2}


def test_limite_mensal_e_dividido_com_o_remarketing():
    _ligar(limite=2)
    _executar("INSERT INTO remarketing_envios (loja_id, lead_id, canal, toque, estado, enviado_em, criado_em) "
              "VALUES (1, 'outro', 'whatsapp', 1, 'enviado', ?, ?)",
              (para_banco(AGORA - timedelta(hours=1)), para_banco(AGORA - timedelta(hours=1))))
    _importar()
    _aprovar()
    _montar()
    t = _rodar(real=True)
    assert t["enviado"] == 1
    assert _linha(CARLOS)["estado"] == "na_fila"


def test_sem_nome_bloqueia():
    _ligar()
    _importar("telefone\n81988887777\n")
    _montar()
    t = _rodar()
    assert t["bloqueado"] == 1 and _linha(CARLOS)["motivo"] == "faltam_dados"


def test_falhou_tres_vezes_para_de_tentar():
    _ligar()
    _importar("nome;telefone\nCarlos Lima;81988887777\n")
    _aprovar()
    _montar()
    falha = EnviadorFalso(ok=False)
    assert _rodar(real=True, enviador=falha)["falhou"] == 1
    assert _rodar(real=True, enviador=falha, agora=AGORA + timedelta(hours=1))["falhou"] == 0   # espera 6 h
    assert _rodar(real=True, enviador=falha, agora=AGORA + timedelta(hours=7))["falhou"] == 1
    assert _rodar(real=True, enviador=falha, agora=AGORA + timedelta(days=1))["bloqueado"] == 1
    assert _linha(CARLOS)["motivo"] == "falhas_repetidas" and len(falha.chamadas) == 3


def test_cliente_que_falou_no_meio_tempo_e_cancelado():
    _ligar()
    _importar()
    _montar()
    _msg_cliente("558199998888", AGORA - timedelta(hours=1))
    t = _rodar()
    assert t["cancelado"] == 1 and t["simulado"] == 1
    assert _linha(ANA)["motivo"] == "conversou_recente"


def test_contato_apagado_e_cancelado():
    _ligar()
    _importar()
    _montar()
    _executar("DELETE FROM contatos WHERE loja_id = 1")
    t = _rodar()
    assert t["cancelado"] == 2 and _linha(ANA)["motivo"] == "sem_contato"


def test_cancelar_fila():
    _ligar()
    _importar()
    _montar()
    assert reativacao.cancelar_fila(1) == 2
    assert reativacao.resumo(1)["cancelado"] == 2
    assert _rodar()["simulado"] == 0


def test_fora_do_horario_nao_faz_nada():
    _ligar()
    _importar()
    _montar()
    t = _rodar(agora=DOMINGO)
    assert sum(t.values()) == 0 and _linha(ANA)["estado"] == "na_fila"


def test_assistente_sabe_da_reativacao_quando_o_cliente_responde():
    _ligar()
    _importar()
    _aprovar()
    _montar()
    _rodar(real=True)
    r = retomada_recente(1, "558199998888", "whatsapp", AGORA + timedelta(hours=1))
    assert r and "Faz um tempo" in r["texto"]
    assert retomada_recente(1, "558199998888", "telegram", AGORA + timedelta(hours=1)) is None


def test_tela_tem_a_reativacao_e_compila():
    fonte = (RAIZ / "paginas/importar_base.py").read_text(encoding="utf-8")
    assert "montar_fila" in fonte and "cancelar_fila" in fonte
    py_compile.compile(str(RAIZ / "paginas/importar_base.py"), doraise=True)
