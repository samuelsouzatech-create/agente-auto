"""
Bloco S2 (furo 7): pedidos de parada que a checagem fixa passa a reconhecer,
e frases de quem ainda quer atendimento (recusa um CARRO, pede foto, preço,
endereço) que NÃO podem virar parada. Tudo offline, sem Gemini.
"""
import pytest

from app.pedido_parada import pediu_para_parar

PARADAS = [
    "me esquece",
    "Me esquece, por favor",
    "esquece meu número",
    "me deixa em paz",
    "sai fora",
    "sai fora, já comprei",
    "bloqueia meu número",
    "vou te bloquear",
    "vou bloquear esse número",
    "n manda mais nada",
    "ñ manda mais nada",
    "não manda mais",
    "chega de mensagem",
    "não quero mais receber",
    "não quero mais receber nada",
    "me tira da lista",
    "descadastra",
    "pare",
    "Pare!",
    "PARE",
    "nao me chama mais",
    "para de me chamar",
    "não me escreva mais",
]


@pytest.mark.parametrize("fala", PARADAS)
def test_reconhece_pedido_de_parada(fala):
    assert pediu_para_parar(fala), f"não reconheceu: {fala}"


AINDA_QUER_ATENDIMENTO = [
    "pode me mandar as fotos",
    "não sei, me manda mais fotos",
    "o Civic sai por quanto",
    "manda o endereço",
    "não quero mais esse, tem outro?",
    "não me mande esse modelo, quero o preto",
    "o carro sai fora do meu orçamento",
    "esquece o Civic, quero ver o Onix",
    "me esqueci do horário, ainda dá?",
    "não me chama mais de senhor, rs",
    "pode bloquear o carro pra mim até sábado?",
    "para quando é a entrega?",
    "para mim serve",
    "tira da lista o Gol",
    "não quero mais o Gol, quero o Onix",
]


@pytest.mark.parametrize("fala", AINDA_QUER_ATENDIMENTO)
def test_recusa_de_carro_nao_e_parada(fala):
    assert pediu_para_parar(fala) is None, f"virou parada sem ser: {fala}"
