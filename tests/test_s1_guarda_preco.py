"""
Bloco S1 (segurança do agente): guarda de preço e filtro do remarketing.
Furos 1, 2, 3 e 15, dos dois lados: o que tem que ser barrado e o que NÃO
pode ser barrado (barrar demais deixa o Léo mudo ou robótico).
Tudo offline, banco temporário do conftest. Sem Gemini.
"""
import pytest
from langchain_core.messages import HumanMessage, ToolMessage

from banco import conectar
from app.filtro_remarketing import precos_da_conversa, precos_do_estoque
from app.guarda_politica import numeros_do_cliente, resposta_tem_preco_inventado, valores_em_reais
from app.jobs.remarketing import _limpar_texto, _texto_reserva

# ------------------------------------------------ furo 1: enxergar dinheiro sem R$

VALORES = [
    ("O Civic sai por uns 75 mil.", {7500000}),
    ("Consigo por 75 mil reais.", {7500000}),
    ("Fica 75k à vista.", {7500000}),
    ("Fica 48x de 1.800 no financiamento.", {180000}),
    ("Parcelas de 1.800 e entrada de 15.000.", {180000, 1500000}),
    ("A entrada fica 1.500 reais.", {150000}),
    ("Sai por 75.000 à vista.", {7500000}),
    ("R$ 98.000,00 à vista.", {9800000}),
    ("Fica 1,5 mil de entrada.", {150000}),
    ("Ano 2020 por 98 mil.", {9800000}),
]


@pytest.mark.parametrize("texto, esperado", VALORES)
def test_guarda_enxerga_dinheiro_com_e_sem_cifrao(texto, esperado):
    assert valores_em_reais(texto) == esperado


NAO_E_PRECO = [
    "O Civic é 2020 e está impecável.",
    "Tem 90 mil km, revisado.",
    "Está com 90.000 km rodados.",
    "São 90 mil quilômetros.",
    "Já rodou 42 mil, todas na concessionária.",
    "Dá pra fazer em 48x.",
    "Me chama no 81 99999-0000.",
    "Te espero às 14h30 na loja.",
    "A loja fica na Av. Boa Viagem, 1.500.",
    "Modelo 2020, câmbio automático, 4 portas.",
]


@pytest.mark.parametrize("texto", NAO_E_PRECO)
def test_ano_km_telefone_horario_endereco_nao_sao_preco(texto):
    assert valores_em_reais(texto) == set()


# ------------------------------------------------ furo 2: km do cliente não libera preço

@pytest.mark.parametrize("fala", ["tem 90 mil km", "ele está com 90.000 km rodados",
                                  "já rodou 90 mil", "uns 90 mil quilômetros", "90km", "km 90.000"])
def test_km_do_cliente_nao_libera_preco(fala):
    assert 9000000 not in numeros_do_cliente(fala)


@pytest.mark.parametrize("fala, valor", [
    ("tenho 20 mil de entrada", 2000000),
    ("meu orçamento é 80.000", 8000000),
    ("consigo pagar 1.500 por mês", 150000),
    ("tem 90 mil km, quero dar 20 mil de entrada", 2000000),
])
def test_dinheiro_do_cliente_continua_liberado(fala, valor):
    assert valor in numeros_do_cliente(fala)


def test_mesma_frase_km_nao_e_dinheiro_sim():
    numeros = numeros_do_cliente("tem 90 mil km, quero dar 20 mil de entrada")
    assert 2000000 in numeros and 9000000 not in numeros


GUARDA = [
    ([HumanMessage("meu carro tem 90 mil km")], "Esse sai por 90 mil.", True),
    ([HumanMessage("tenho 20 mil de entrada")], "Com 20 mil de entrada a gente simula.", False),
    ([ToolMessage(content="Onix 2020 - R$ 72.900,00 - 42.000 km", tool_call_id="t1")],
     "Sai por uns 72,9 mil, com 42 mil km.", False),
    ([], "O Onix sai por uns 70 mil.", True),
    ([], "O Onix 2020 tem 42 mil km e câmbio automático.", False),
]


@pytest.mark.parametrize("mensagens, resposta, inventado", GUARDA)
def test_guarda_completa(mensagens, resposta, inventado):
    assert resposta_tem_preco_inventado(resposta, mensagens) is inventado


# ------------------------------------------------ furo 15: ação inventada no remarketing

ACOES = [
    "Falei com o gerente e ele topou conversar com você.",
    "Conversei com o dono sobre o Renegade.",
    "Já levei sua proposta pro gerente.",
    "Consegui um desconto pra você no Onix.",
    "Consegui uma condição especial no Onix.",
    "Tenho um retorno sobre a sua proposta do Renegade.",
    "Reservamos o Onix pra você até sábado.",
    "O Onix está reservado pra você.",
    "Guardei o Corolla pra você ver no sábado.",
    "Reservei o Onix pra você.",
    "Separei o Corolla para você.",
]


@pytest.mark.parametrize("frase", ACOES)
def test_remarketing_barra_acao_inventada(frase):
    assert _limpar_texto(f"Oi, Paulo! {frase}") == ""


CONTINUAM = [
    "Oi, Paulo! Quer que eu fale com o gerente sobre a sua proposta?",
    "Oi, Paulo! Posso conversar com o gerente e te dou um retorno, combinado?",
    "Oi, Carla! O Onix continua disponível, quer marcar uma visita?",
    "Oi, Carla! Se quiser, consigo te mandar mais fotos do Onix.",
    "Oi, Carla! O Onix 2020 tem 42 mil km, quer ver de perto?",
    "Oi, Fernanda! Passando para saber se ainda posso te ajudar com o Corolla 2018.",
    "Oi! Ficou alguma dúvida sobre o Argo 2021?",
]


@pytest.mark.parametrize("texto", CONTINUAM)
def test_remarketing_nao_barra_oferta_normal(texto):
    assert _limpar_texto(texto) == texto


class _Loja:
    nome = "Seminovos Boa Viagem"

    def get(self, chave, padrao=None):
        return {"nome_agente": "Ricardo"}.get(chave, padrao)


@pytest.mark.parametrize("dados", [
    {"nome": "Carla Menezes", "carro": "Chevrolet Onix 2020", "carro_disponivel": True, "alternativa": ""},
    {"nome": "Rafael", "carro": "Honda Civic 2017", "carro_disponivel": False,
     "alternativa": "Toyota Corolla 2018"},
    {"nome": "", "carro": "", "carro_disponivel": False, "alternativa": ""},
])
def test_texto_reserva_passa_no_filtro(dados):
    texto = _texto_reserva(_Loja(), dados)
    assert _limpar_texto(texto) == texto


# ------------------------------------------------ furo 3: preço no remarketing

def test_remarketing_barra_preco_inventado():
    assert _limpar_texto("Oi, Carla! O Onix 2020 sai por R$ 65.000, quer ver?") == ""
    assert _limpar_texto("Oi, Carla! O Onix sai por uns 65 mil, bora?", {7290000}) == ""


def test_remarketing_aceita_preco_da_conversa_e_nao_o_km():
    historico = [
        {"direcao": "cliente", "conteudo": "Oi, vi o Onix 2020. Ainda tem?"},
        {"direcao": "leo", "conteudo": "Tem sim, por R$ 72.900. Quer ver fotos?"},
        {"direcao": "cliente", "conteudo": "meu carro tem 90 mil km, vou pensar"},
    ]
    permitidos = precos_da_conversa(historico)
    assert 7290000 in permitidos and 9000000 not in permitidos
    texto = "Oi, Carla! O Onix 2020 por R$ 72.900 continua disponível. Quer ver de perto?"
    assert _limpar_texto(texto, permitidos) == texto
    assert _limpar_texto("Oi, Carla! Pelo seu carro dou 90 mil, topa?", permitidos) == ""


def test_preco_do_estoque_so_da_propria_loja():
    conexao = conectar()
    try:
        sql = ("INSERT INTO estoque (loja_id, marca, modelo, ano, km, cor, cambio, preco) "
               "VALUES (?, ?, ?, ?, ?, ?, ?, ?)")
        meu = conexao.execute(sql, (1, "Chevrolet", "Onix", 2020, 42000, "Prata", "Automático",
                                    72900.0)).lastrowid
        outro = conexao.execute(sql, (42, "Fiat", "Argo", 2021, 30000, "Branco", "Manual",
                                      50000.0)).lastrowid
        conexao.commit()
    finally:
        conexao.close()
    assert precos_do_estoque(1, {"veiculo_id": meu, "alternativa_id": outro}) == {7290000}
    assert precos_do_estoque(1, {"veiculo_id": None, "alternativa_id": None}) == set()
