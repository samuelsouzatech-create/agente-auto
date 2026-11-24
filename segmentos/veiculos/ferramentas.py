"""Ferramentas do ramo de veículos (Etapa 2, Bloco 1; SG1 da Maratona 4).

Etapa 2: saíram do app/core/montagem.py (o motor não conhece carro).
SG1: as três que só servem para carro (estoque, ficha do carro e troca) saíram de tools/ e moram
neste pacote. As outras (fotos, financiamento, agenda) continuam no motor (tools/): todo ramo
pode ter fotos, simulação e visita.
"""
from tools import agendar_visita, enviar_fotos, simular_financiamento
from segmentos.veiculos.consultar_estoque import consultar_estoque
from segmentos.veiculos.detalhes_veiculo import detalhes_veiculo
from segmentos.veiculos.registrar_troca import registrar_troca

# Sempre ligadas numa loja de veículos.
FERRAMENTAS = [consultar_estoque, detalhes_veiculo, simular_financiamento, registrar_troca]

# Ligadas só quando o módulo da loja está ligado.
FERRAMENTAS_DE_MODULO = {
    "agendamento": [agendar_visita],
    "fotos": [enviar_fotos],
}

# Guia curto de cada ferramenta DESTE ramo no prompt (camada 4). As do motor ficam no motor.
DESCRICOES = {
    "consultar_estoque": "o cliente pergunta sobre carros, modelos, categorias (SUV, sedã, hatch, picape), preços ou disponibilidade.",
    "detalhes_veiculo": "o cliente quer saber mais de um carro específico que já apareceu na conversa.",
    "registrar_troca": "o cliente diz que tem um carro para dar na troca.",
}

# O agente injeta o cliente (lead_id) nestas, nunca o modelo.
FERRAMENTAS_COM_LEAD_ID = {"registrar_troca"}

# Gravam algo: em modo sombra não executam; depois delas a frase de oferta fixa não entra.
FERRAMENTAS_QUE_GRAVAM = {"registrar_troca"}

# O que estas devolvem é a "ficha" do carro (a guarda do estado do carro só aceita o que veio daqui).
FERRAMENTAS_DE_FICHA = ("consultar_estoque", "detalhes_veiculo")
