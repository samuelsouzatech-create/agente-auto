"""
Atraso adaptativo por lead (humanização — seção 4.6 do PDF).

Imita o ritmo de um vendedor humano:
- Cliente ATIVO (mandou mensagem há pouco): resposta rápida (1-3 s).
- Cliente que SUMIU e voltou (minutos de silêncio): o Léo "demora pra ver"
  a mensagem e segura um pouco (10-30 s), como uma pessoa faria.

Para saber isso, guardamos no Redis o carimbo de tempo da última vez que o
lead falou (chave visto:{lead_id}). Comparamos com "agora" para decidir o
atraso, e então atualizamos o carimbo.
"""
import time
import random

from app.redis_cliente import redis_cliente

# Se o cliente falou há MENOS que isto, ele está "ativo" -> resposta rápida.
LIMITE_ATIVO_S = 120          # 2 minutos

# Faixas de atraso (segundos). Valor sorteado dentro da faixa, pra não robotizar.
ATRASO_ATIVO = (1, 3)         # cliente grudado no celular
ATRASO_AUSENTE = (10, 30)     # cliente que sumiu e voltou

# Quanto tempo o carimbo sobrevive no Redis (6 horas; depois disso tratamos
# como conversa nova).
TTL_VISTO = 6 * 60 * 60


async def calcular_atraso(lead_id: str) -> float:
    """Decide quantos segundos esperar antes de responder a este lead,
    com base em quanto tempo passou desde a última mensagem dele.
    Também atualiza o carimbo de 'última vez visto' para agora."""
    chave_visto = f"visto:{lead_id}"
    agora = time.time()

    visto_antes = await redis_cliente.get(chave_visto)

    # Atualiza o carimbo para agora (sempre), para a próxima comparação.
    await redis_cliente.set(chave_visto, agora, ex=TTL_VISTO)

    # Primeira mensagem de sempre: trata como ativo (resposta rápida).
    if visto_antes is None:
        return random.uniform(*ATRASO_ATIVO)

    tempo_em_silencio = agora - float(visto_antes)

    if tempo_em_silencio <= LIMITE_ATIVO_S:
        # Cliente ativo: respondeu há pouco.
        return random.uniform(*ATRASO_ATIVO)
    else:
        # Cliente sumiu e voltou: segura um pouco, como um humano.
        return random.uniform(*ATRASO_AUSENTE)
