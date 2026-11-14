"""
Bloco S5: detectores de AVISO dos relatórios das rodadas com IA real.
Offline, sem Gemini. Cada detector tem frases que ele PEGA e frases que
ele NÃO pode pegar.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from avisos_texto import (  # noqa: E402
    DECISAO, EQUIPE_TECNICA, FALHA_TECNICA, NOVIDADE, PRAZO, VIDEO_FOTO,
    avisos_de_texto, rotulos_de_texto,
)

PEGA = [
    (DECISAO, "O gerente liberou 5% pra você"),
    (DECISAO, "O gerente aprovou sua proposta, vem fechar!"),
    (DECISAO, "Fechei com o gerente uma condição melhor"),
    (DECISAO, "O gerente topou o valor que você propôs"),
    (DECISAO, "Consegui um desconto pra você"),
    (DECISAO, "Seu financiamento foi aprovado!"),
    (DECISAO, "Crédito aprovado, é só vir assinar."),
    (VIDEO_FOTO, "Posso te enviar um vídeo detalhado dele."),
    (VIDEO_FOTO, "Quer que eu te mande umas fotos?"),
    (VIDEO_FOTO, "Quer ver as fotos dele?"),
    (NOVIDADE, "Chegou um Corolla 2018 aqui na loja."),
    (NOVIDADE, "Aquele Civic não está mais disponível, mas chegou um Corolla 2018."),
    (NOVIDADE, "Está impecável!"),
    (NOVIDADE, "Consegui mais alguns detalhes sobre o Onix."),
    (FALHA_TECNICA, "Não consegui consultar as informações do Onix agora."),
    (FALHA_TECNICA, "Como não estou conseguindo consultar o estoque agora, vou chamar um vendedor."),
    (FALHA_TECNICA, "O sistema está fora do ar."),
    (PRAZO, "Já já um vendedor vai falar com você."),
    (PRAZO, "Eles já te chamam aqui."),
    (PRAZO, "Em instantes alguém te responde."),
    (PRAZO, "Daqui a pouco te retornam."),
    (EQUIPE_TECNICA, "Vou ver isso com o pessoal da nossa equipe técnica."),
    (EQUIPE_TECNICA, "Nossa oficina vai olhar."),
]

NAO_PEGA = [
    (DECISAO, "Quer que eu veja com o gerente se ele aprova?"),
    (DECISAO, "O gerente não aprovou ainda."),
    (DECISAO, "Não consigo aprovar crédito, quem vê isso é o vendedor."),
    (DECISAO, "A aprovação do crédito depende do banco."),
    (VIDEO_FOTO, "Obrigado, vi as fotos que você mandou."),
    (VIDEO_FOTO, "O carro tem câmera de ré."),
    (NOVIDADE, "O documento ainda não chegou?"),
    (NOVIDADE, "Você conseguiu organizar sua agenda?"),
    (FALHA_TECNICA, "Não encontrei esse carro no nosso estoque."),
    (FALHA_TECNICA, "No momento não temos SUVs no estoque."),
    (PRAZO, "Já chamei um vendedor, ele continua o atendimento por aqui."),
    (PRAZO, "Passando para saber se você conseguiu organizar sua agenda esta semana."),
    (EQUIPE_TECNICA, "Já chamei o pessoal do pós-venda."),
    (EQUIPE_TECNICA, "Vou passar para a nossa equipe de vendas."),
]


@pytest.mark.parametrize("rotulo, texto", PEGA)
def test_detector_pega(rotulo, texto):
    assert rotulo in rotulos_de_texto(texto), avisos_de_texto(texto)


@pytest.mark.parametrize("rotulo, texto", NAO_PEGA)
def test_detector_nao_pega(rotulo, texto):
    assert rotulo not in rotulos_de_texto(texto), avisos_de_texto(texto)


def test_textos_reais_da_rodada_de_13_11():
    assert VIDEO_FOTO in rotulos_de_texto(
        "Oi Marcos, tudo bem? Caso ainda tenha interesse no HB20, posso te enviar um vídeo "
        "detalhado dele ou agendar um horário para você dar uma volta no carro.")
    assert NOVIDADE in rotulos_de_texto(
        "Oi Rafael, tudo bem? Aquele Civic não está mais disponível, mas chegou um Corolla 2018 "
        "aqui na loja que segue a mesma linha e está impecável.")
    assert FALHA_TECNICA in rotulos_de_texto(
        "Não consegui consultar as informações do Onix agora, mas já chamei um dos nossos "
        "vendedores e ele vai falar com você.")
    r = rotulos_de_texto(
        "Sinto muito por isso, imagino como deve ser chato. Vou ver isso com o pessoal da nossa "
        "equipe técnica, eles já te chamam aqui para entender melhor.")
    assert EQUIPE_TECNICA in r and PRAZO in r
    assert rotulos_de_texto(
        "Oi Fernanda, tudo bem? Passando para saber se você conseguiu organizar sua agenda "
        "para conhecer o Corolla 2018 esta semana.") == set()
