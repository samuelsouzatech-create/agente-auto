# SG1: consultar_estoque, detalhes_veiculo e registrar_troca são do ramo de veículos
# (pacote do ramo, segmentos/<ramo>/). O motor não conhece carro.
from tools.enviar_fotos import enviar_fotos
from tools.simular_financiamento import simular_financiamento
from tools.agendar_visita import agendar_visita
from tools.registrar_lead import registrar_lead
from tools.acionar_handoff import acionar_handoff
from tools.buscar_conhecimento import buscar_conhecimento
from tools.registrar_interesse import registrar_interesse
from tools.utils import formatar_brl

__all__ = [
    "enviar_fotos",
    "simular_financiamento",
    "agendar_visita", "registrar_lead",
    "acionar_handoff", "buscar_conhecimento", "registrar_interesse",
    "formatar_brl",
]
