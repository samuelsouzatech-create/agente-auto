"""Ferramentas do segmento de veículos (Etapa 2, Bloco 1).
Saíram do app/core/montagem.py: o motor não conhece carro."""
from tools import (
    consultar_estoque, detalhes_veiculo, simular_financiamento, registrar_troca,
    agendar_visita, enviar_fotos,
)

# Sempre ligadas numa loja de veículos.
FERRAMENTAS = [consultar_estoque, detalhes_veiculo, simular_financiamento, registrar_troca]

# Ligadas só quando o módulo da loja está ligado.
FERRAMENTAS_DE_MODULO = {
    "agendamento": [agendar_visita],
    "fotos": [enviar_fotos],
}
