"""
Debounce por lead (Bloco 5).

Quando o cliente manda uma rajada de mensagens ("oi" / "vcs tem" / "Civic?"),
o debounce espera ele terminar antes de o Léo responder. As mensagens vão
sendo acumuladas num buffer no Redis; só processamos após alguns segundos
de silêncio, tudo de uma vez.

Fluxo:
- a cada mensagem que chega, acrescenta ao buffer do lead e marca a hora;
- espera DEBOUNCE_SEGUNDOS;
- se nenhuma mensagem nova chegou nesse intervalo, esta execução é a "dona"
  e devolve o texto juntado; senão, desiste (outra execução mais nova cuidará).
"""
import time
import asyncio

from app.redis_cliente import redis_cliente

# Quanto tempo de silêncio esperar antes de processar (PDF: 3 a 5 segundos).
DEBOUNCE_SEGUNDOS = 4
# Por quanto tempo o buffer sobrevive no Redis (segurança contra lixo).
TTL_BUFFER = 120


async def acumular_e_esperar(lead_id: str, texto: str) -> str | None:
    """Acumula a mensagem no buffer do lead e espera o silêncio.

    Retorna o texto juntado (todas as mensagens da rajada) se ESTA execução
    for a responsável por processar; retorna None se outra mensagem chegou
    depois (quem vier por último processa)."""
    chave_buffer = f"buffer:{lead_id}"
    chave_hora = f"ultima_hora:{lead_id}"

    # Marca o instante desta mensagem (identidade desta execução).
    hora_desta = time.time()

    # Acrescenta a mensagem ao buffer e registra a hora desta mensagem.
    await redis_cliente.rpush(chave_buffer, texto)
    await redis_cliente.expire(chave_buffer, TTL_BUFFER)
    await redis_cliente.set(chave_hora, hora_desta, ex=TTL_BUFFER)

    # Espera o tempo de silêncio.
    await asyncio.sleep(DEBOUNCE_SEGUNDOS)

    # Chegou mensagem nova depois desta? Se a hora registrada mudou, sim.
    hora_atual = await redis_cliente.get(chave_hora)
    if hora_atual is None or float(hora_atual) != hora_desta:
        # Outra mensagem chegou depois: ela cuidará da rajada. Desiste.
        return None

    # Esta execução é a dona: pega tudo do buffer e limpa.
    partes = await redis_cliente.lrange(chave_buffer, 0, -1)
    await redis_cliente.delete(chave_buffer)
    await redis_cliente.delete(chave_hora)

    return " ".join(partes)
