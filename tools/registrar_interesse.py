from typing import Annotated

from langchain_core.tools import tool, InjectedToolArg

from app.interesse import SITUACOES, SituacaoInvalida, registrar_situacao

ORIENTACAO = {
    "pediu_tempo": ("Anotado. Responda com leveza, sem pressionar, deixando a porta aberta "
                    "(ex.: 'tranquilo, sem pressa, quando quiser é só me chamar aqui')."),
    "sem_interesse": "Anotado. Agradeça com educação e encerre bem, sem insistir nem fazer nova oferta.",
    "nao_contatar": ("Anotado. Peça desculpas pelo incômodo de forma breve e humana e não insista. "
                     "A loja não vai mais procurar esse cliente por conta própria."),
}
FINAL = " Não mencione registro, sistema, cadastro, lista ou comandos."


@tool
def registrar_interesse(situacao: str, motivo: str, retomar_em_dias: int = 0,
                        lead_id: Annotated[str, InjectedToolArg] = "",
                        loja_id: Annotated[int, InjectedToolArg] = 1,
                        canal: Annotated[str, InjectedToolArg] = "") -> str:
    """Anota como o cliente está em relação à compra, percebido pela conversa.
    Use SÓ quando o cliente deixar isso claro com as palavras dele:
    - "pediu_tempo": quer pensar, falar com alguém, ver depois, "agora não".
    - "sem_interesse": já comprou, desistiu, não quer mais o carro.
    - "nao_contatar": pediu claramente para não receber mais mensagens.
    Na dúvida, NÃO use: continue a conversa normalmente.

    Parâmetros:
    - situacao: "pediu_tempo", "sem_interesse" ou "nao_contatar"
    - motivo: o que o cliente disse, resumido
    - retomar_em_dias: só para "pediu_tempo", se o cliente disser quando (mês que vem = 30)
    """
    try:
        registrar_situacao(loja_id, lead_id, situacao, motivo=motivo,
                           canal=canal, dias=retomar_em_dias)
    except SituacaoInvalida as erro:
        return f"Erro: {erro}"
    return ORIENTACAO[str(situacao).strip().lower()] + FINAL
