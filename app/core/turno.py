"""
O turno do Léo, IGUAL para todos os canais (Etapa 1, Bloco 4 - item 1.6).

Cada canal cuida apenas da "porta": receber, juntar a rajada (debounce),
pegar a vez (lock), chamar executar_turno() e enviar.

Ordem do turno:
  1. separa o que aconteceu enquanto o Léo estava fora (vendedor no comando)
  2. grava a mensagem do cliente
  3. vendedor assumiu? -> Léo em silêncio
  4. Léo da loja (grafo) responde. Se a equipe conversou com o cliente, ele
     recebe esse trecho como contexto e não contradiz o que foi combinado
  5. limpa Markdown e junta as mídias do turno
  6. guarda de preço (barra valor inventado e chama o vendedor)
  7. alerta de naturalidade (frase com cara de robô aparece no terminal)
  8. grava a resposta
  9. custo do turno (Bloco 6): uma linha em uso_custos + uma no log

Bloco 7A: não existe opt-out por comando. Quem escreve SEMPRE é atendido.
O que o cliente pede ("agora não", "não me procure") o Léo anota com a
ferramenta registrar_interesse, e isso só vale para contatos que a LOJA
iniciaria (remarketing e pós-venda, Etapa 2).
"""
from __future__ import annotations

import asyncio
import time
import traceback
from dataclasses import dataclass, field

from langchain_core.messages import HumanMessage, ToolMessage

from app.chaves import thread_id
from app.custos import ferramentas_usadas, registrar_uso, uso_das_mensagens
from app.formatacao import limpar_markdown
from app.guarda_politica import resposta_tem_preco_inventado, MENSAGEM_SEGURA
from app.handoff import estado_do_handoff
from app.humanizador import dividir_em_bolhas
from app.mensagens import salvar_mensagem, mensagens_desde_a_ultima_resposta_do_leo
from app.naturalidade import parece_robotica
from app.redis_debounce import acumular_e_esperar
from app.redis_lock import adquirir_lock_esperando
from app.utils import extrair_texto, mensagens_do_turno
from tools import acionar_handoff

NOMES_CANAIS = {"whatsapp": "WhatsApp", "telegram": "Telegram",
                "instagram": "Instagram", "simulador": "Simulador"}

MENSAGEM_MIDIA_NAO_SUPORTADA = ("Por enquanto só consigo ler texto e áudio por aqui. "
                                "Pode me escrever ou mandar um áudio?")
MENSAGEM_AUDIO_FALHOU = "Não consegui entender o áudio. Pode mandar de novo ou escrever?"
MENSAGEM_ERRO = ("Tive um problema para responder agora. "
                 "Pode mandar sua mensagem de novo daqui a pouco?")

DESCRICAO_MIDIA = {
    "image": "imagem", "sticker": "figurinha", "video": "vídeo", "animation": "gif",
    "document": "documento", "location": "localização", "contacts": "contato",
}

# Canais em que cada mensagem enviada pode ser cobrada pela Meta.
CANAIS_COBRADOS = {"whatsapp"}

CONTEXTO_INICIO = ("[Contexto interno, não repita nem comente com o cliente: enquanto você "
                   "estava fora, a conversa continuou assim com a equipe da loja. Siga o que "
                   "foi combinado e não contradiga o vendedor.]")
CONTEXTO_FIM = "[Mensagem atual do cliente:]"


@dataclass
class ResultadoTurno:
    texto: str | None = None
    midias: list = field(default_factory=list)
    handoff_aberto: bool = False      # este turno abriu/atualizou um handoff
    silenciado: bool = False          # vendedor no comando: nada a enviar
    # Custo em R$ (None = preço ainda não cadastrado). Fora da comparação (==).
    custo: float | None = field(default=None, compare=False)
    execucao_id: str | None = field(default=None, compare=False)

    @property
    def respostas(self) -> list[str]:
        """A resposta já dividida em bolhas (no máximo 3)."""
        return dividir_em_bolhas(self.texto or "")


def _rotulo(canal: str, loja_id: int) -> str:
    return f"[{NOMES_CANAIS.get(canal, canal)}][loja {loja_id}]"


def _ms_desde(inicio: float) -> int:
    return int((time.perf_counter() - inicio) * 1000)


def _custo(registro) -> float | None:
    return registro["custo_total"] if registro and registro["completo"] else None


def _id(registro) -> str | None:
    return registro["execucao_id"] if registro else None


def _texto_custo(r: dict) -> str:
    valor = f"R$ {r['custo_total']:.6f}" if r["completo"] else "preço não cadastrado"
    return (f"{r['tokens_entrada'] + r['tokens_audio']} tokens de entrada, "
            f"{r['tokens_saida']} de saída, {r['latencia_ms']} ms, {valor}")


def extrair_midias(mensagens) -> list[str]:
    """URLs das fotos que as ferramentas pediram para enviar neste turno."""
    urls = []
    for m in mensagens:
        artifact = getattr(m, "artifact", None)
        if isinstance(artifact, dict) and artifact.get("tipo") == "fotos":
            urls.extend(artifact.get("urls", []))
    return urls


def _chamou_handoff(mensagens) -> bool:
    return any(isinstance(m, ToolMessage) and m.name == "acionar_handoff"
               and not str(m.content).startswith("Erro") for m in mensagens)


def _o_que_aconteceu_fora(loja_id: int, lead_id: str) -> list:
    try:
        return mensagens_desde_a_ultima_resposta_do_leo(lead_id, loja_id)
    except Exception as erro:
        print(f"[Turno][loja {loja_id}] Aviso: não li o histórico recente ({erro!r}).")
        return []


def com_contexto_do_periodo_fora(texto: str, perdidas: list) -> str:
    """Se a equipe conversou com o cliente enquanto o Léo estava em silêncio,
    o Léo recebe esse trecho antes da mensagem atual. O banco guarda o texto puro."""
    linhas = []
    for m in perdidas:
        if m["direcao"] == "vendedor":
            linhas.append(f"{m.get('autor') or 'Vendedor'} (equipe da loja): {m['conteudo']}")
        elif m["direcao"] == "cliente":
            linhas.append(f"Cliente: {m['conteudo']}")
    if not linhas:
        return texto
    return f"{CONTEXTO_INICIO}\n" + "\n".join(linhas) + f"\n{CONTEXTO_FIM}\n\n{texto}"


async def aguardar_vez(loja_id: int, lead_id: str, texto: str):
    """Debounce + lock. Devolve (texto_juntado, token) ou (None, None).
    Quem receber um token TEM que liberar o lock no final (finally)."""
    texto_juntado = await acumular_e_esperar(lead_id, texto, loja_id=loja_id)
    if texto_juntado is None:
        return None, None
    token = await adquirir_lock_esperando(lead_id, loja_id=loja_id)
    if token is None:
        print(f"[Turno][loja {loja_id}] Lead {lead_id}: lock ocupado tempo demais. Desistindo.")
        return None, None
    return texto_juntado, token


async def executar_turno(loja_id: int, canal: str, lead_id: str, texto: str, *,
                         grafo=None, tipo: str = "texto") -> ResultadoTurno:
    """Roda UM turno do Léo. Não envia nada: quem envia é o canal."""
    inicio = time.perf_counter()
    if grafo is None:
        from app.core.agent import agente_grafo as grafo   # import tardio (cria a IA)
    rotulo = _rotulo(canal, loja_id)
    print(f"\n{rotulo} Cliente {lead_id} disse: {texto}")

    perdidas = _o_que_aconteceu_fora(loja_id, lead_id)
    salvar_mensagem(lead_id, "cliente", texto, canal=canal, tipo=tipo, loja_id=loja_id)

    if estado_do_handoff(lead_id, loja_id) == "humano_assumiu":
        print(f"{rotulo} Lead {lead_id} está com um vendedor humano. Léo em silêncio.")
        return ResultadoTurno(silenciado=True)

    texto_para_leo = com_contexto_do_periodo_fora(texto, perdidas)
    if texto_para_leo != texto:
        print(f"{rotulo} Léo volta à conversa sabendo de {len(perdidas)} mensagem(ns) da equipe/cliente.")

    try:
        resultado = await asyncio.to_thread(
            grafo.invoke,
            {
                "messages": [HumanMessage(content=texto_para_leo)],
                "lead_id": lead_id,
                "loja_id": loja_id,
                "canal": canal,
            },
            {"configurable": {"thread_id": thread_id(loja_id, canal, lead_id)}},
        )
    except Exception:
        print(f"{rotulo} ERRO ao gerar a resposta do Léo:")
        traceback.print_exc()
        salvar_mensagem(lead_id, "leo", MENSAGEM_ERRO, canal=canal, loja_id=loja_id)
        registro = registrar_uso(loja_id, lead_id, canal, tipo="erro",
                                 latencia_ms=_ms_desde(inicio))
        return ResultadoTurno(texto=MENSAGEM_ERRO, execucao_id=_id(registro))

    do_turno = mensagens_do_turno(resultado)
    resposta = limpar_markdown(extrair_texto(resultado["messages"][-1].content))
    midias = extrair_midias(do_turno)
    handoff = _chamou_handoff(do_turno)
    ferramentas = ferramentas_usadas(do_turno)

    if resposta_tem_preco_inventado(resposta, resultado["messages"]):
        print(f"{rotulo} GUARDA: preço inventado detectado. Acionando handoff.")
        print(f"{rotulo} Resposta barrada: {resposta}")
        acionar_handoff.func(
            motivo="Guarda de política: valor em R$ sem origem em tool.",
            resumo=f"Resposta barrada do Léo: {resposta}",
            lead_id=lead_id,
            loja_id=loja_id,
        )
        resposta, midias, handoff = MENSAGEM_SEGURA, [], True
        ferramentas.append("guarda_preco")

    robotico = parece_robotica(resposta)
    if robotico:
        print(f"{rotulo} ALERTA de naturalidade: a resposta tem \"{robotico}\". Revise o prompt.")

    print(f"{rotulo} Léo responde: {resposta}")
    if midias:
        print(f"{rotulo} Enviando {len(midias)} foto(s).")

    salvar_mensagem(lead_id, "leo", resposta, canal=canal, loja_id=loja_id)

    msgs_servico = (len(dividir_em_bolhas(resposta)) + len(midias)
                    if canal in CANAIS_COBRADOS else 0)
    registro = registrar_uso(
        loja_id, lead_id, canal, uso_das_mensagens(do_turno),
        ferramentas=ferramentas, latencia_ms=_ms_desde(inicio), msgs_servico=msgs_servico,
    )
    if registro:
        print(f"{rotulo} Custo do turno: {_texto_custo(registro)}")
    print()
    return ResultadoTurno(texto=resposta, midias=midias, handoff_aberto=handoff,
                          custo=_custo(registro), execucao_id=_id(registro))


def turno_resposta_fixa(loja_id: int, canal: str, lead_id: str, registro_cliente: str,
                        resposta: str, tipo: str = "texto") -> ResultadoTurno:
    """Turno sem Léo (resposta pronta, sem IA), respeitando o vendedor no comando."""
    salvar_mensagem(lead_id, "cliente", registro_cliente, canal=canal, tipo=tipo, loja_id=loja_id)
    if estado_do_handoff(lead_id, loja_id) == "humano_assumiu":
        return ResultadoTurno(silenciado=True)
    salvar_mensagem(lead_id, "leo", resposta, canal=canal, loja_id=loja_id)
    return ResultadoTurno(texto=resposta)


def turno_midia_nao_suportada(loja_id: int, canal: str, lead_id: str,
                              tipo_original: str) -> ResultadoTurno:
    descricao = DESCRICAO_MIDIA.get(tipo_original, "mídia")
    return turno_resposta_fixa(loja_id, canal, lead_id, f"[{descricao}]",
                               MENSAGEM_MIDIA_NAO_SUPORTADA, tipo=tipo_original or "midia")


def turno_audio_falhou(loja_id: int, canal: str, lead_id: str) -> ResultadoTurno:
    return turno_resposta_fixa(loja_id, canal, lead_id, "[áudio não entendido]",
                               MENSAGEM_AUDIO_FALHOU, tipo="audio")
