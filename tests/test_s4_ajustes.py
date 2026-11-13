"""
Bloco S4: ajustes do S1 e do S2 achados pelo analista, dos dois lados.
A) remarketing barra decisão inventada (gerente liberou, crédito aprovado);
B) guarda de preço lê número por extenso e espaço de milhar;
C) parada reconhece mais pedidos, sem pegar recusa de carro.
Tudo offline, sem Gemini.
"""
import pytest
from langchain_core.messages import HumanMessage

from app.filtro_remarketing import acao_inventada
from app.guarda_politica import numeros_do_cliente, resposta_tem_preco_inventado, valores_em_reais
from app.jobs.remarketing import _limpar_texto
from app.pedido_parada import pediu_para_parar

# ------------------------------------------------ A) remarketing

DECISAO_INVENTADA = [
    "O gerente liberou 5% pra você.",
    "O gerente aprovou sua proposta, vem fechar!",
    "Fechei com o gerente uma condição melhor.",
    "O gerente topou o valor que você propôs.",
    "Seu financiamento foi aprovado!",
    "Seu crédito aprovado está esperando.",
    "Seu crédito foi pré-aprovado.",
    "O banco aprovou seu crédito.",
    "O dono autorizou a troca pelo seu Gol.",
    "A proposta do Renegade foi aprovada.",
    "Já deixei o carro separado pra você.",
    "Segurei ele pra você.",
    "Consegui 10% de desconto.",
]


@pytest.mark.parametrize("frase", DECISAO_INVENTADA)
def test_remarketing_barra_decisao_inventada(frase):
    texto = f"Oi, Paulo! {frase}"
    assert acao_inventada(texto)
    assert _limpar_texto(texto) == ""


OFERTA_NORMAL = [
    "Oi, Paulo! Quer que eu veja com o gerente se ele aprova?",
    "Oi, Paulo! Posso levar sua proposta ao gerente?",
    "Oi, Paulo! Quer ver se seu crédito é aprovado? A simulação é rápida.",
    "Oi, Paulo! Posso segurar o carro até amanhã?",
    "Oi, Paulo! O Onix aceita troca, quer avaliar o seu?",
    "Oi, Paulo! Banco de couro e câmera de ré, quer ver?",
    "Oi, Paulo! O dono anterior fez todas as revisões.",
]


@pytest.mark.parametrize("texto", OFERTA_NORMAL)
def test_remarketing_nao_barra_oferta(texto):
    assert not acao_inventada(texto)


# ------------------------------------------------ B) guarda de preço

VALORES = [
    ("Sai por setenta mil.", {7000000}),
    ("Com dez mil de entrada a gente simula.", {1000000}),
    ("Fica um milhão.", {100000000}),
    ("Sai por setenta e cinco mil reais.", {7500000}),
    ("Fica 75 000 reais.", {7500000}),
    ("Sai por R$ 75 000.", {7500000}),
    ("Parcelas de quinhentos reais.", {50000}),
    ("Entrada de mil e quinhentos.", {150000}),
    ("Fica R$ 1,2 milhão.", {120000000}),
    ("Sai por cento e vinte mil.", {12000000}),
]


@pytest.mark.parametrize("texto, esperado", VALORES)
def test_guarda_le_extenso_e_espaco_de_milhar(texto, esperado):
    assert valores_em_reais(texto) == esperado


NAO_E_PRECO = [
    "Tem noventa mil km.",
    "Já rodou noventa mil.",
    "O Civic é dois mil e vinte.",
    "Mil desculpas pela demora!",
    "Revisado cem por cento.",
    "Desconto de dez por cento no seguro.",
    "Tenho dois filhos e um cachorro.",
    "Me chama no 81 99999-0000.",
    "Ano 2020, 90 000 km.",
]


@pytest.mark.parametrize("texto", NAO_E_PRECO)
def test_extenso_que_nao_e_preco(texto):
    assert valores_em_reais(texto) == set()


@pytest.mark.parametrize("fala, valor, liberado", [
    ("tenho dez mil de entrada", 1000000, True),
    ("dá pra fazer por 75 000?", 7500000, True),
    ("tem noventa mil km", 9000000, False),
])
def test_cliente_por_extenso(fala, valor, liberado):
    assert (valor in numeros_do_cliente(fala)) is liberado


@pytest.mark.parametrize("mensagens, resposta, inventado", [
    ([], "Sai por setenta mil.", True),
    ([HumanMessage("meu limite é setenta mil")], "Com setenta mil a gente fecha a simulação.", False),
    ([HumanMessage("tem setenta mil km")], "Sai por setenta mil.", True),
])
def test_guarda_completa_extenso(mensagens, resposta, inventado):
    assert resposta_tem_preco_inventado(resposta, mensagens) is inventado


# ------------------------------------------------ C) parada

PARADAS = [
    "para de mandar mensagem",
    "para de mandar msg",
    "pare de me mandar isso",
    "me bloqueia",
    "quero cancelar",
    "remove meu número",
    "apaga meu contato",
    "chega de spam",
    "isso é spam",
    "não quero ser contatado",
    "deixa eu em paz",
    "para de insistir",
    "parar",
    "não manda mais não",
    "apague meus dados",
    "pela LGPD quero que apaguem tudo",
    "pode parar de mandar mensagem?",
]


@pytest.mark.parametrize("fala", PARADAS)
def test_reconhece_mais_pedidos(fala):
    assert pediu_para_parar(fala), f"não reconheceu: {fala}"


AINDA_ATENDIMENTO = [
    "posso parar de mandar mensagem?",
    "devo parar de mandar mensagem por aqui?",
    "quero cancelar a visita de sábado",
    "apaga o meu cadastro do Gol",
    "isso não é spam, né?",
    "não quero ser chamado de senhor",
    "me bloqueia o Onix até sábado?",
    "quero sair hoje com o carro",
    "para de mandar foto do Civic, manda do Onix",
    "não manda mais fotos",
]


@pytest.mark.parametrize("fala", AINDA_ATENDIMENTO)
def test_nao_vira_parada(fala):
    assert pediu_para_parar(fala) is None, f"virou parada sem ser: {fala}"
