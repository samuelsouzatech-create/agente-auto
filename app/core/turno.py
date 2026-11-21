"""
O turno do Léo, IGUAL para todos os canais (Etapa 1, Bloco 4 - item 1.6).

Cada canal cuida apenas da "porta": receber, juntar a rajada (debounce),
pegar a vez (lock), chamar executar_turno() e enviar.

Ordem do turno:
  0. P7: loja em teste? Só número de teste e simulador passam. Os outros:
     silêncio, nada gravado, evento no Registro (porta_fechada)
     L3/L4: quem escreve é da equipe cadastrada desta loja? Não vira lead.
     Dono ou gestor: MODO EQUIPE (só anota recados). Vendedor: resposta fixa.
  1. separa o que aconteceu enquanto o Léo estava fora (vendedor no comando)
  2. grava a mensagem do cliente
  3. vendedor assumiu? -> Léo em silêncio
  4. Léo da loja (grafo) responde. Se a equipe conversou com o cliente, ele
     recebe esse trecho como contexto e não contradiz o que foi combinado
  5. limpa Markdown e junta as mídias do turno
  6. guarda de preço (barra valor inventado e chama o vendedor)
     L2: disse que a equipe vai confirmar/falar com o cliente sem chamado aberto?
     abre o chamado no mesmo turno (a resposta não muda)
  7. alerta de naturalidade (frase com cara de robô aparece no terminal)
  8. grava a resposta
  9. custo do turno (Bloco 6): uma linha em uso_custos + uma no log

Bloco 7A: não existe opt-out por comando. Quem escreve é atendido (exceto
loja em teste, P7). O que o cliente pede ("agora não", "não me procure") o
Léo anota com a ferramenta registrar_interesse, e isso só vale para
contatos que a LOJA iniciaria (remarketing e pós-venda, Etapa 2).
"""
from __future__ import annotations

import asyncio
import re
import time
import traceback
from dataclasses import dataclass, field

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.chaves import exigir_loja, thread_id
from app.console import id_no_console, texto_no_console   # N1: privacidade no console
from app.core.pos_processamento import Contexto, pos_processar   # N4: ordem das guardas
from app.custos import ferramentas_usadas, registrar_uso, uso_das_mensagens
from app.estado_loja import pode_responder
from app.formatacao import limpar_markdown
from app.guarda_politica import (MENSAGEM_SEGURA, PREFIXO_FALSO_DONO, assunto_da_equipe,
                                 cliente_ameacou, motivo_com_marcas, relatou_problema_da_compra,
                                 assunto_serio, limitar_emojis, tem_emoji,
                                 corrigir_regra_de_entrada, diz_ser_da_equipe,
                                 pediu_valor_da_troca, pergunta_curta, pergunta_se_aceita_troca,
                                 promete_contato_da_equipe, resposta_tem_preco_inventado,
                                 tirar_elogio_da_descricao, tirar_elogio_do_estado,
                                 tirar_promessa_de_foto, pedido_da_equipe, trocar_frases_de_risco,
                                 trocar_politica_sem_base, cortar_estado_inventado,
                                 tirar_agendamento_falso, limpar_repeticoes, FRASE_CNH, FRASE_CONTATO,
                                 tirar_palavra_de_tempo, corrigir_reabertura, tirar_fragmentos,
                                 FRASE_OFERTA, tirar_texto_interno,
                                 trocar_frases_proibidas)
from banco import conectar
from app.handoff import estado_do_handoff
from app.humanizador import dividir_em_bolhas
from app.mensagens import salvar_mensagem, mensagens_desde_a_ultima_resposta_do_leo
from app.memoria_banco import com_historico_do_banco, historico_se_esqueceu
from app.naturalidade import parece_robotica
from app.pedido_parada import registrar_se_pediu_parada
from app import sombra
from app.sombra import em_sombra
from app.recados import (MENSAGEM_SO_DONO, MENSAGEM_SO_RECADOS, membro_da_equipe,
                         pode_deixar_recado)
from app.redis_debounce import acumular_e_esperar
from app.redis_lock import adquirir_lock_esperando
from app.utils import extrair_texto, mensagens_do_turno
from tools import acionar_handoff
from app.log import logger as _logger   # N3: registro técnico (logs/leo.log)

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

# P7: quem aparece no Registro quando a loja em teste recusa uma mensagem.
EVENTO_RECUSADA = "mensagem_recusada_loja_em_teste"
NOME_SISTEMA = "Sistema"
ORIGEM_SISTEMA = "webhook"


@dataclass
class ResultadoTurno:
    texto: str | None = None
    midias: list = field(default_factory=list)
    handoff_aberto: bool = False      # este turno abriu/atualizou um handoff
    silenciado: bool = False          # vendedor no comando: nada a enviar
    # Custo em R$ (None = preço ainda não cadastrado). Fora da comparação (==).
    custo: float | None = field(default=None, compare=False)
    execucao_id: str | None = field(default=None, compare=False)
    # L5: tokens da leitura da foto (a bancada soma no custo). Fora da comparação (==).
    uso_imagem: object = field(default=None, compare=False)
    # L5b: {"tipo", "descricao"} da foto lida (a bancada mostra no relatório).
    leitura_imagem: dict | None = field(default=None, compare=False)

    @property
    def respostas(self) -> list[str]:
        """A resposta já dividida em bolhas (no máximo 3)."""
        return dividir_em_bolhas(self.texto or "")


# N2: ferramentas que gravam algo (depois delas a frase de oferta fixa não entra).
FERRAMENTAS_QUE_GRAVAM = frozenset({"agendar_visita", "registrar_interesse", "registrar_lead", "registrar_recado",
                                    "registrar_troca", "acionar_handoff"})


def reabertura_agora(loja_id: int):
    """N5b: None com a loja aberta; senão a próxima abertura (app/relogio.py, a fonte única de horário)."""
    from app.lojas import carregar_loja
    from app.relogio import agora_utc, reabertura
    try:
        return reabertura(carregar_loja(loja_id), agora_utc())
    except Exception:
        _logger("turno").exception("Não consegui calcular a reabertura da loja.")
        return None


def precisa_da_frase_de_oferta(guarda_mexeu: bool, resposta_inicial: str, resposta: str, handoff: bool,
                               ferramentas, texto_do_cliente: str) -> bool:
    """M1/N2: a guarda cortou a pergunta final e a resposta ficou sem NENHUMA pergunta e sem nenhuma
    ação gravada (ex.: test-drive agendado): termina com a oferta simples. Nunca em assunto sério."""
    acao_gravada = bool(set(ferramentas or ()) & FERRAMENTAS_QUE_GRAVAM)
    return bool(guarda_mexeu and resposta_inicial.rstrip().endswith("?") and "?" not in resposta
                and not handoff and not acao_gravada and not assunto_serio("", texto_do_cliente))


def internos_do_turno(do_turno) -> list[str]:
    """N2: motivo e resumo passados ao acionar_handoff neste turno (o cliente nunca vê esses textos)."""
    saida = []
    for m in do_turno or []:
        for chamada in getattr(m, "tool_calls", None) or []:
            if chamada.get("name") == "acionar_handoff":
                argumentos = chamada.get("args") or {}
                saida += [str(argumentos[c]) for c in ("motivo", "resumo") if argumentos.get(c)]
    return saida


def _rotulo(canal: str, loja_id: int) -> str:
    return f"[{NOMES_CANAIS.get(canal, canal)}][loja {loja_id}]"


def _ms_desde(inicio: float) -> int:
    return int((time.perf_counter() - inicio) * 1000)


def _custo(registro) -> float | None:
    return registro["custo_total"] if registro and registro["completo"] else None


def _id(registro) -> str | None:
    return registro["execucao_id"] if registro else None


def _texto_custo(r: dict) -> str:
    valor = (f"R$ {r['custo_total']:.6f}" if r["completo"]
             else "preço não cadastrado (cadastre na tela Custos)")
    return (f"{r['tokens_entrada'] + r['tokens_audio']} tokens de entrada, "
            f"{r['tokens_saida']} de saída, {r['latencia_ms']} ms, {valor}")


def _anotar_recusa(loja_id: int, canal: str, lead_id: str) -> None:
    """P7: a recusa vai para o Registro da loja. Nunca derruba quem chamou."""
    try:
        from app.ator import como_sistema      # aqui dentro: evita import circular
        from app.registro import registrar
        with como_sistema(NOME_SISTEMA, ORIGEM_SISTEMA):
            registrar(EVENTO_RECUSADA, loja_id, None, {"canal": canal},
                      alvo=f"{canal}:{lead_id}")
    except Exception as erro:
        print(f"[Turno][loja {loja_id}] Não consegui gravar no Registro: {erro!r}")


def porta_fechada(loja_id, canal: str, lead_id) -> bool:
    """P7: True = loja em teste e quem escreveu não é número de teste.
    Nada é gravado (nem mensagem, nem custo); só o evento no Registro.
    Erro ao ler o estado = porta fechada (nunca libera por engano)."""
    loja_id = exigir_loja(loja_id)
    try:
        if pode_responder(loja_id, canal, lead_id):
            return False
    except Exception as erro:
        print(f"[Turno][loja {loja_id}] Não consegui ler o estado da loja ({erro!r}). Porta fechada.")
    print(f"{_rotulo(canal, loja_id)} Loja em teste: {id_no_console(lead_id, canal)} não é número de teste. "
          f"Mensagem ignorada, nada gravado.")
    _anotar_recusa(loja_id, canal, str(lead_id))
    return True


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
        print(f"[Turno][loja {loja_id}] Lead {id_no_console(lead_id)}: lock ocupado tempo demais. Desistindo.")
        return None, None
    return texto_juntado, token


async def executar_turno(loja_id: int, canal: str, lead_id: str, texto: str, *,
                         grafo=None, tipo: str = "texto", foto_carro: bool = False) -> ResultadoTurno:
    """Roda UM turno do Léo. Não envia nada: quem envia é o canal."""
    inicio = time.perf_counter()
    # P7: antes de tudo (antes de gravar e de chamar a IA).
    if porta_fechada(loja_id, canal, lead_id):
        return ResultadoTurno(silenciado=True)
    if grafo is None:
        from app.core.agent import agente_grafo as grafo   # import tardio (cria a IA)
    membro = _quem_da_equipe(loja_id, canal, lead_id)
    if membro:
        return await _turno_da_equipe(loja_id, canal, lead_id, texto, membro, grafo, inicio)
    if em_sombra(loja_id):          # L9: gera a resposta, NÃO envia nem grava atendimento
        return await _turno_sombra(loja_id, canal, lead_id, texto, grafo, inicio)
    rotulo = _rotulo(canal, loja_id)
    print(f"\n{rotulo} Cliente {id_no_console(lead_id, canal)} disse: {texto_no_console(texto, canal)}")

    configuracao = {"configurable": {"thread_id": thread_id(loja_id, canal, lead_id)}}
    perdidas = _o_que_aconteceu_fora(loja_id, lead_id)
    # Bloco 4B: lido ANTES de gravar a mensagem atual (para ela não entrar duas vezes).
    historico = historico_se_esqueceu(grafo, configuracao, loja_id, lead_id, canal)
    salvar_mensagem(lead_id, "cliente", texto, canal=canal, tipo=tipo, loja_id=loja_id)

    # Rede de segurança: pedido claro de parada é gravado pelo CÓDIGO,
    # antes de tudo (vale até com o vendedor no comando).
    registrar_se_pediu_parada(loja_id, lead_id, texto, canal)

    if estado_do_handoff(lead_id, loja_id) == "humano_assumiu":
        print(f"{rotulo} Lead {id_no_console(lead_id, canal)} está com um vendedor humano. Léo em silêncio.")
        return ResultadoTurno(silenciado=True)

    # L5b: número fora da equipe dizendo ser dono/gestor/da loja: resposta fixa, sem IA.
    # L5c: depois que disparou, toda fala do lead (24 h, ou até o vendedor assumir) também.
    if diz_ser_da_equipe(texto) or falso_dono_ativo(loja_id, lead_id):
        print(f"{rotulo} GUARDA: {id_no_console(lead_id, canal)} diz ser da equipe, mas não está cadastrado. Resposta fixa.")
        marcar_falso_dono(loja_id, lead_id, texto)
        fixa = _resposta_falso_dono(loja_id, lead_id)            # N2: a 2ª seguida não repete o texto
        salvar_mensagem(lead_id, "leo", fixa, canal=canal, loja_id=loja_id)
        return ResultadoTurno(texto=fixa, handoff_aberto=True)

    texto_para_leo = com_contexto_do_periodo_fora(texto, perdidas)
    if texto_para_leo != texto:
        print(f"{rotulo} Léo volta à conversa sabendo de {len(perdidas)} mensagem(ns) da equipe/cliente.")

    if historico:
        texto_para_leo = com_historico_do_banco(texto_para_leo, historico)
        print(f"{rotulo} Memória vazia (o bot reiniciou?): Léo recebe "
              f"{len(historico)} mensagem(ns) do histórico do banco.")

    try:
        resultado = await asyncio.to_thread(
            grafo.invoke,
            {
                "messages": [HumanMessage(content=texto_para_leo)],
                "lead_id": lead_id,
                "loja_id": loja_id,
                "canal": canal,
                "equipe": {},
                "sombra": False,
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
    resposta = resposta_do_turno(do_turno, resultado["messages"][-1])   # L11: texto antes da tool também
    midias = extrair_midias(do_turno)
    handoff = _chamou_handoff(do_turno)
    ferramentas = ferramentas_usadas(do_turno)

    # Ponto 9: o vendedor pode ter assumido enquanto a IA pensava. A IA já foi
    # paga (o custo é registrado), mas nada é enviado nem gravado como fala do Léo.
    if estado_do_handoff(lead_id, loja_id) == "humano_assumiu":
        print(f"{rotulo} Vendedor assumiu durante a resposta. Resposta descartada: {texto_no_console(resposta, canal)}")
        registro = registrar_uso(loja_id, lead_id, canal, uso_das_mensagens(do_turno),
                                 ferramentas=ferramentas, latencia_ms=_ms_desde(inicio))
        return ResultadoTurno(silenciado=True, execucao_id=_id(registro))

    # N4 (revisão #9): o pós-processamento é UMA lista ordenada, com um nome por passo
    # (app/core/pos_processamento.py). A ordem é a mesma de antes.
    contexto = pos_processar(Contexto(
        loja_id=loja_id, canal=canal, lead_id=lead_id, texto=texto, do_turno=do_turno,
        mensagens=resultado["messages"], rotulo=rotulo, resposta=resposta, midias=midias,
        handoff=handoff, ferramentas=ferramentas, foto_carro=foto_carro))
    resposta, midias = contexto.resposta, contexto.midias
    handoff, ferramentas = contexto.handoff, contexto.ferramentas

    robotico = parece_robotica(resposta)
    if robotico:
        print(f"{rotulo} ALERTA de naturalidade: a resposta tem \"{robotico}\". Revise o prompt.")

    print(f"{rotulo} Léo responde: {texto_no_console(resposta, canal)}")
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


def _ja_disse_ser_da_equipe(loja_id: int, lead_id: str) -> bool:
    conexao = conectar()
    try:
        linhas = conexao.execute("SELECT conteudo FROM mensagens WHERE loja_id = ? AND lead_id = ? "
                                 "AND direcao = 'cliente'", (loja_id, lead_id)).fetchall()
    finally:
        conexao.close()
    return any(diz_ser_da_equipe(l["conteudo"]) for l in linhas)


def _resposta_falso_dono(loja_id: int, lead_id: str) -> str:
    """N2 (revisão #12): se a última resposta do Léo a este cliente já foi a fixa, usa a outra."""
    conexao = conectar()
    try:
        linha = conexao.execute("SELECT conteudo FROM mensagens WHERE loja_id = ? AND lead_id = ? AND direcao = 'leo' "
                                "ORDER BY id DESC LIMIT 1", (loja_id, str(lead_id))).fetchone()
    finally:
        conexao.close()
    return MENSAGEM_FALSO_DONO_2 if linha and linha["conteudo"] == MENSAGEM_FALSO_DONO else MENSAGEM_FALSO_DONO


MENSAGEM_FALSO_DONO_2 = ("Por aqui eu sigo sem registrar pedidos para este número, porque ele não está na equipe "
                         "da loja. O pessoal da equipe já foi avisado e confere.")
MENSAGEM_FALSO_DONO = ("Esse número não está cadastrado na equipe da loja, então não registro pedidos "
                       "por aqui. O pessoal da equipe vai conferir.")
MOTIVO_ACEITA_TROCA = "Cliente perguntou se a loja aceita troca (não está no cadastro)."
JANELA_FALSO_DONO_HORAS = 24


def limite_de_emojis(loja_id: int, lead_id: str, texto: str, abriu_chamado: bool) -> int:
    """L10: quantos emojis a resposta pode ter. 0 por padrão; 1 se o cliente usou emoji
    nesta conversa (inclusive agora); 0 se o turno abriu chamado de assunto sério
    (reclamação, PÓS-VENDA, URGENTE, crédito/financiamento, documento) ou ele ameaçou."""
    try:
        motivo = ""
        if abriu_chamado:
            conexao = conectar()
            try:
                linha = conexao.execute("SELECT motivo FROM handoffs WHERE loja_id = ? AND lead_id = ? "
                                        "AND estado = 'aguardando_humano' ORDER BY id DESC LIMIT 1",
                                        (loja_id, lead_id)).fetchone()
            finally:
                conexao.close()
            motivo = (linha["motivo"] if linha else "") or ""
        if assunto_serio(motivo, texto):
            return 0
        if tem_emoji(texto):
            return 1
        conexao = conectar()
        try:
            linhas = conexao.execute("SELECT conteudo FROM mensagens WHERE loja_id = ? AND lead_id = ? "
                                     "AND direcao = 'cliente'", (loja_id, lead_id)).fetchall()
        finally:
            conexao.close()
        return 1 if any(tem_emoji(l["conteudo"]) for l in linhas) else 0
    except Exception as erro:
        print(f"[Turno][loja {loja_id}] Aviso: não li o histórico de emoji ({erro!r}). Sem emoji.")
        return 0


def _comprou_na_loja(loja_id: int, lead_id: str) -> bool:
    conexao = conectar()
    try:
        return conexao.execute("SELECT 1 FROM vendas WHERE loja_id = ? AND lead_id = ? LIMIT 1",
                               (loja_id, lead_id)).fetchone() is not None
    finally:
        conexao.close()


def marcar_pos_venda_e_urgencia(loja_id: int, lead_id: str, texto: str) -> bool:
    """L6 (código, não prompt):
    - cliente irritado ou ameaçando (Procon, advogado, Reclame Aqui...): chamado com URGENTE;
    - quem comprou na loja e relata problema (barulho, defeito, documento, transferência,
      pagamento): chamado com "PÓS-VENDA: " no começo (o job de pós-venda para os passos).
    Sem chamado aberto: abre. Com chamado aberto (até pela IA neste turno): marca o motivo.
    Devolve True se abriu chamado agora. Nunca derruba o turno."""
    try:
        urgente = cliente_ameacou(texto)
        comprou = _comprou_na_loja(loja_id, lead_id)
        pos_venda = comprou and (urgente or relatou_problema_da_compra(texto))
        if not (urgente or pos_venda):
            return False
        if estado_do_handoff(lead_id, loja_id) == "ativo":
            base = ("Cliente irritado ou ameaçando reclamar." if urgente
                    else "Cliente relatou problema com a compra.")
            acionar_handoff.func(
                motivo=motivo_com_marcas(f'{base} Pergunta do cliente: "{pergunta_curta(texto)}"',
                                         pos_venda=pos_venda, urgente=urgente),
                resumo=f"Mensagem do cliente: {texto}", lead_id=lead_id, loja_id=loja_id)
            return True
        conexao = conectar()
        try:
            linha = conexao.execute("SELECT id, motivo FROM handoffs WHERE loja_id = ? AND lead_id = ? "
                                    "AND estado = 'aguardando_humano' ORDER BY id DESC LIMIT 1",
                                    (loja_id, lead_id)).fetchone()
            if linha is not None:
                novo = motivo_com_marcas(linha["motivo"], pos_venda=pos_venda, urgente=urgente)
                if novo != (linha["motivo"] or ""):
                    conexao.execute("UPDATE handoffs SET motivo = ? WHERE id = ?", (novo, linha["id"]))
                    conexao.commit()
        finally:
            conexao.close()
        return False
    except Exception as erro:
        print(f"[Turno][loja {loja_id}] Aviso: não consegui marcar pós-venda/urgente ({erro!r}).")
        return False


def falso_dono_ativo(loja_id: int, lead_id: str) -> bool:
    """L5c: há chamado ABERTO deste lead, nesta loja, marcado como falso dono, das
    últimas 24 h? (Vendedor assumiu: o turno já fica em silêncio antes daqui.)"""
    try:
        from datetime import timedelta
        from app.relogio import agora_utc, para_banco
        desde = para_banco(agora_utc() - timedelta(hours=JANELA_FALSO_DONO_HORAS))
        conexao = conectar()
        try:
            linha = conexao.execute(
                "SELECT 1 FROM handoffs WHERE loja_id = ? AND lead_id = ? AND estado = 'aguardando_humano' "
                "AND motivo LIKE ? || '%' AND criado_em >= ? LIMIT 1",
                (loja_id, lead_id, PREFIXO_FALSO_DONO, desde)).fetchone()
        finally:
            conexao.close()
        return linha is not None
    except Exception as erro:
        print(f"[Turno][loja {loja_id}] Aviso: não li o falso dono ({erro!r}).")
        return False


def _aceita_troca(loja_id: int) -> str:
    try:
        from app.lojas import carregar_loja
        return str(carregar_loja(loja_id).get("aceita_troca") or "nao_informado")
    except Exception:
        _logger("turno").exception("Não consegui ler 'aceita troca' da loja.")
        return "nao_informado"
MOTIVO_VALOR_TROCA = "Cliente pediu valor da troca."
MOTIVO_PROMESSA = "Léo disse ao cliente que a equipe vai confirmar ou falar com ele."


def motivo_do_chamado_pelo_codigo(texto: str, resposta: str,
                                  aceita_troca: str = "sim") -> tuple[str, str] | None:
    """(motivo, nome da guarda) ou None. Ordem: valor da troca, assunto, promessa."""
    if aceita_troca == "nao_informado" and pergunta_se_aceita_troca(texto):
        return MOTIVO_ACEITA_TROCA, "guarda_aceita_troca"
    if pediu_valor_da_troca(texto):
        return MOTIVO_VALOR_TROCA, "guarda_troca"
    assunto = assunto_da_equipe(texto)
    if assunto:
        return f"Cliente perguntou sobre {assunto}.", "guarda_assunto"
    pedido = pedido_da_equipe(texto)                          # L8
    if pedido:
        return pedido, "guarda_pedido"
    if promete_contato_da_equipe(resposta):
        return MOTIVO_PROMESSA, "guarda_contato"
    return None


def marcar_falso_dono(loja_id: int, lead_id: str, texto: str) -> bool:
    """L3b: cliente que diz ser da equipe (número não cadastrado).
    Disse agora e não há chamado: abre um. Há chamado aberto e ele disse isso em
    algum momento da conversa: o motivo passa a começar com o aviso.
    Devolve True se abriu chamado neste turno. Nunca derruba o turno."""
    try:
        abriu = False
        if diz_ser_da_equipe(texto) and estado_do_handoff(lead_id, loja_id) == "ativo":
            acionar_handoff.func(motivo=f'{PREFIXO_FALSO_DONO}. Pergunta do cliente: "{pergunta_curta(texto)}"',
                                 resumo=f"Mensagem do cliente: {texto}",
                                 lead_id=lead_id, loja_id=loja_id)
            abriu = True
        if abriu or _ja_disse_ser_da_equipe(loja_id, lead_id):
            conexao = conectar()
            try:
                conexao.execute(
                    "UPDATE handoffs SET motivo = ? || ' — ' || COALESCE(motivo, '') "
                    "WHERE loja_id = ? AND lead_id = ? AND estado = 'aguardando_humano' "
                    "AND COALESCE(motivo, '') NOT LIKE ? || '%'",
                    (PREFIXO_FALSO_DONO, loja_id, lead_id, PREFIXO_FALSO_DONO))
                conexao.commit()
            finally:
                conexao.close()
        return abriu
    except Exception as erro:
        print(f"[Turno][loja {loja_id}] Aviso: não consegui marcar o falso dono ({erro!r}).")
        return False


async def _turno_sombra(loja_id: int, canal: str, lead_id: str, texto: str, grafo,
                        inicio: float) -> ResultadoTurno:
    """L9: o Léo gera a resposta, mas nada sai e nada de atendimento é gravado
    (sem mensagem na conversa, sem chamado, troca, visita ou lead). Só a sugestão fica.
    As guardas que só mexem no TEXTO valem, para a sugestão ser o que ele mandaria."""
    rotulo = _rotulo(canal, loja_id)
    print(f"\n{rotulo} [SOMBRA] Cliente {id_no_console(lead_id, canal)} disse: {texto_no_console(texto, canal)}")
    try:
        resultado = await asyncio.to_thread(
            grafo.invoke,
            {"messages": [HumanMessage(content=texto)], "lead_id": lead_id, "loja_id": loja_id,
             "canal": canal, "equipe": {}, "sombra": True},
            {"configurable": {"thread_id": thread_id(loja_id, canal, lead_id)}},
        )
    except Exception:
        traceback.print_exc()
        sombra.gravar(loja_id, lead_id, canal, texto, "(erro ao gerar a sugestão)", [])
        return ResultadoTurno(silenciado=True)
    do_turno = mensagens_do_turno(resultado)
    # As que o Léo PEDIU (em sombra, as que gravam nem rodam).
    ferramentas = sorted({c["name"] for m in do_turno for c in (getattr(m, "tool_calls", None) or [])}
                         | set(ferramentas_usadas(do_turno)))
    # N5: a sugestão passa pela MESMA lista do turno normal (app/core/pos_processamento.py);
    # o que grava algo (chamado, pós-venda, falso dono) não roda na sombra.
    fotos = extrair_midias(do_turno)
    contexto = pos_processar(Contexto(
        loja_id=loja_id, canal=canal, lead_id=lead_id, texto=texto, do_turno=do_turno,
        mensagens=resultado["messages"], rotulo=f"{rotulo} [SOMBRA]",
        resposta=resposta_do_turno(do_turno, resultado["messages"][-1]), midias=list(fotos),
        handoff=_chamou_handoff(do_turno), ferramentas=list(ferramentas_usadas(do_turno)), sombra=True))
    sugestao = contexto.resposta
    if fotos and contexto.midias:
        sugestao = f"{sugestao}\n[Fotos que o Léo mandaria: {', '.join(fotos)}]"
    sombra.gravar(loja_id, lead_id, canal, texto, sugestao, ferramentas)
    registrar_uso(loja_id, lead_id, canal, uso_das_mensagens(do_turno), tipo="sombra",
                  ferramentas=ferramentas, latencia_ms=_ms_desde(inicio))
    print(f"{rotulo} [SOMBRA] Sugestão guardada (nada enviado): {sugestao}")
    return ResultadoTurno(silenciado=True)


def _fichas_do_turno(do_turno) -> str:
    """L12: o que as ferramentas de estoque devolveram no turno (a 'ficha' do carro)."""
    return " ".join(str(m.content) for m in do_turno if isinstance(m, ToolMessage)
                    and m.name in ("consultar_estoque", "detalhes_veiculo"))


def _agenda_do_turno(do_turno) -> str | None:
    """L12: texto da agenda se a ferramenta GRAVOU neste turno; None se não gravou."""
    for m in do_turno:
        if isinstance(m, ToolMessage) and m.name == "agendar_visita" and str(m.content).startswith(
                ("Agendamento confirmado", "Agendamento atualizado")):
            return str(m.content)
    return None


def _avisa_contato(resposta: str) -> bool:
    import re as _re
    return promete_contato_da_equipe(resposta) or bool(
        _re.search(r"(?i)\b(equipe|vendedor\w*)\b", resposta))


def _frases_do_texto(texto: str) -> list[str]:
    import re as _re
    return [f for f in _re.split(r"(?<=[.!?])\s+", texto.strip()) if f.strip()]


_NARRA_FERRAMENTA = re.compile(r"(?i)\b(sistema|registr\w*|anot\w*|cadastr\w*|ferrament\w*|acion\w*)\b")


def resposta_do_turno(do_turno, ultima) -> str:
    """L11: tudo o que o Léo ESCREVEU no turno, na ordem. Quando ele escreve e chama uma
    ferramenta (ex.: acionar_handoff) no mesmo turno, o texto de antes da ferramenta também
    vai para o cliente (antes, só a última mensagem saía e a resposta ao assunto se perdia).
    Se a última parte já diz que a equipe vai falar com o cliente, as partes anteriores
    perdem as frases que diziam o mesmo (sem repetir a promessa)."""
    textos = []
    for m in do_turno:
        if isinstance(m, AIMessage):
            t = limpar_markdown(extrair_texto(m.content)).strip()
            if t:
                textos.append(t)
    if not textos:
        return limpar_markdown(extrair_texto(ultima.content))
    final = textos[-1]
    partes = []
    for t in textos[:-1]:
        # S6 continua valendo: o Léo narrando a ferramenta ("vou registrar aqui no sistema")
        # nunca vai para o cliente. Só a resposta ao assunto vai.
        frases = [f for f in _frases_do_texto(t) if not _NARRA_FERRAMENTA.search(f)]
        if promete_contato_da_equipe(final):
            frases = [f for f in frases if not promete_contato_da_equipe(f)]
        t = " ".join(frases).strip()
        if t and t != final and t not in partes:
            partes.append(t)
    return "\n\n".join(partes + [final])


def _quem_da_equipe(loja_id: int, canal: str, lead_id: str) -> dict | None:
    """Pessoa da equipe desta loja? Erro ao ler = trata como cliente (atende normal)."""
    try:
        return membro_da_equipe(loja_id, canal, lead_id)
    except Exception as erro:
        print(f"[Turno][loja {loja_id}] Não consegui ler a equipe ({erro!r}). Segue como cliente.")
        return None


_TEM_NUMERO = re.compile(r"\d")


async def _turno_da_equipe(loja_id: int, canal: str, lead_id: str, texto: str,
                           membro: dict, grafo, inicio: float) -> ResultadoTurno:
    """L3/L4: equipe escrevendo. Nada vira lead nem conversa de cliente.
    Dono ou gestor: o Léo só anota recados (registrar_recado). A resposta depois
    de gravar sai da ferramenta (repete recado e validade). Sem recado gravado e
    com número na resposta: resposta fixa (o Léo não inventa número do dia)."""
    rotulo = _rotulo(canal, loja_id)
    print(f"\n{rotulo} {membro['nome']} ({membro['papel']}, equipe) disse: {texto_no_console(texto, canal)}")
    if not pode_deixar_recado(membro):
        return ResultadoTurno(texto=MENSAGEM_SO_DONO)
    try:
        resultado = await asyncio.to_thread(
            grafo.invoke,
            {"messages": [HumanMessage(content=texto)], "lead_id": lead_id,
             "loja_id": loja_id, "canal": canal, "equipe": dict(membro), "sombra": False},
            {"configurable": {"thread_id": thread_id(loja_id, canal, lead_id)}},
        )
    except Exception:
        print(f"{rotulo} ERRO no modo equipe:")
        traceback.print_exc()
        registro = registrar_uso(loja_id, None, canal, tipo="erro", latencia_ms=_ms_desde(inicio))
        return ResultadoTurno(texto=MENSAGEM_ERRO, execucao_id=_id(registro))

    do_turno = mensagens_do_turno(resultado)
    gravados = [str(m.content) for m in do_turno
                if isinstance(m, ToolMessage) and m.name == "registrar_recado"
                and not str(m.content).startswith("Erro")]
    tentou = any(isinstance(m, ToolMessage) and m.name == "registrar_recado" for m in do_turno)
    if gravados:
        resposta = " ".join(gravados)
    else:
        resposta = limpar_markdown(extrair_texto(resultado["messages"][-1].content))
        if not resposta.strip() or (not tentou and _TEM_NUMERO.search(resposta)):
            resposta = MENSAGEM_SO_RECADOS
    print(f"{rotulo} Léo responde à equipe: {texto_no_console(resposta, canal)}")
    registro = registrar_uso(loja_id, None, canal, uso_das_mensagens(do_turno), tipo="equipe",
                             ferramentas=ferramentas_usadas(do_turno), latencia_ms=_ms_desde(inicio))
    return ResultadoTurno(texto=resposta, custo=_custo(registro), execucao_id=_id(registro))


def turno_resposta_fixa(loja_id: int, canal: str, lead_id: str, registro_cliente: str,
                        resposta: str, tipo: str = "texto") -> ResultadoTurno:
    """Turno sem Léo (resposta pronta, sem IA), respeitando o vendedor no comando."""
    if porta_fechada(loja_id, canal, lead_id):          # P7
        return ResultadoTurno(silenciado=True)
    if em_sombra(loja_id):                              # L9: só guarda a sugestão
        sombra.gravar(loja_id, lead_id, canal, registro_cliente, resposta, [])
        return ResultadoTurno(silenciado=True)
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


def turno_midia_grande(loja_id: int, canal: str, lead_id: str, tipo: str) -> ResultadoTurno:
    """N2 (revisão #4): áudio longo/grande ou foto grande: resposta fixa, sem IA, e a conversa registra."""
    from app.limites_midia import MENSAGEM_AUDIO_LONGO, MENSAGEM_FOTO_GRANDE
    if tipo == "audio":
        return turno_resposta_fixa(loja_id, canal, lead_id, "[áudio acima do limite]",
                                   MENSAGEM_AUDIO_LONGO, tipo="audio")
    return turno_resposta_fixa(loja_id, canal, lead_id, "[foto acima do limite]",
                               MENSAGEM_FOTO_GRANDE, tipo="imagem")


def turno_audio_falhou(loja_id: int, canal: str, lead_id: str) -> ResultadoTurno:
    return turno_resposta_fixa(loja_id, canal, lead_id, "[áudio não entendido]",
                               MENSAGEM_AUDIO_FALHOU, tipo="audio")


# ======================================================================
# L5: foto do cliente
# ======================================================================
MENSAGEM_DOCUMENTO = ("Recebi, mas por aqui eu não leio nem guardo documentos. Vou passar para o "
                      "pessoal da equipe, que cuida disso com segurança.")
MENSAGEM_IMAGEM_FALHOU = ("Não consegui ver a foto por aqui. Pode me contar por texto o que ela "
                          "mostra? Também passei para o pessoal da equipe dar uma olhada.")
MENSAGEM_EQUIPE_SO_TEXTO = "Por aqui eu só anoto recados por texto."
MOTIVO_DOCUMENTO = "Cliente mandou documento (nenhum dado foi lido nem guardado)."
MOTIVO_IMAGEM_FALHOU = "Cliente mandou uma foto que não consegui ver."
MOTIVO_AVALIACAO = "Avaliação: cliente mandou foto do carro."


def _chamado_da_foto(loja_id: int, lead_id: str, motivo: str, resumo: str) -> None:
    """Abre o chamado. Se já houver um aberto, acrescenta o motivo (não apaga o anterior)."""
    estado = estado_do_handoff(lead_id, loja_id)
    if estado == "ativo":
        acionar_handoff.func(motivo=motivo, resumo=resumo, lead_id=lead_id, loja_id=loja_id)
        return
    conexao = conectar()
    try:
        conexao.execute(
            "UPDATE handoffs SET motivo = COALESCE(motivo, '') || ' · ' || ? "
            "WHERE loja_id = ? AND lead_id = ? AND estado = 'aguardando_humano' "
            "AND instr(COALESCE(motivo, ''), ?) = 0", (motivo, loja_id, lead_id, motivo))
        conexao.commit()
    finally:
        conexao.close()


def _anotar_foto_na_troca(loja_id: int, lead_id: str, descricao: str) -> None:
    """Se o cliente já tem troca registrada, a última ganha 'foto recebida: ...'."""
    if not descricao:
        return
    conexao = conectar()
    try:
        linha = conexao.execute("SELECT id, estado FROM trocas WHERE loja_id = ? AND lead_id = ? "
                                "ORDER BY id DESC LIMIT 1", (loja_id, lead_id)).fetchone()
        if linha is None:
            return
        nota = f"foto recebida: {descricao}"
        estado = (linha["estado"] or "").strip()
        if nota not in estado:
            estado = f"{estado} | {nota}" if estado else nota
            conexao.execute("UPDATE trocas SET estado = ? WHERE id = ?", (estado, linha["id"]))
            conexao.commit()
    finally:
        conexao.close()


def _resposta_fixa_com_chamado(loja_id, canal, lead_id, registro, resposta, motivo, uso):
    resultado = turno_resposta_fixa(loja_id, canal, lead_id, registro, resposta, tipo="imagem")
    if not resultado.silenciado:
        _chamado_da_foto(loja_id, lead_id, motivo, "Resposta automática do Léo: " + resposta)
        resultado.handoff_aberto = True
    resultado.uso_imagem = uso
    return resultado


def _com_leitura(resultado: ResultadoTurno, leitura) -> ResultadoTurno:
    """L5b: o tipo lido e a descrição curta seguem no resultado (a bancada mostra)."""
    resultado.uso_imagem = leitura.uso
    resultado.leitura_imagem = {"tipo": leitura.tipo if leitura.ok else "não lida",
                                "descricao": leitura.descricao, "erro": leitura.erro,
                                "tentativas": leitura.tentativas}
    return resultado


EVENTO_FOTO_FALHOU = "leitura_foto_falhou"


def _anotar_falha_da_foto(loja_id: int, lead_id: str, canal: str, leitura) -> None:
    """L5c: o tipo do erro vai para o Registro (nenhum dado da imagem). Nunca derruba o turno."""
    try:
        from app.ator import como_sistema
        from app.registro import registrar
        with como_sistema(NOME_SISTEMA, ORIGEM_SISTEMA):
            registrar(EVENTO_FOTO_FALHOU, loja_id, None,
                      {"erro": leitura.erro or "outro", "tentativas": leitura.tentativas, "canal": canal},
                      alvo=f"{canal}:{lead_id}")
    except Exception as erro:
        print(f"[Turno][loja {loja_id}] Não consegui gravar a falha da foto no Registro: {erro!r}")


async def executar_turno_imagem(loja_id: int, canal: str, lead_id: str, imagem: bytes,
                                mime: str = "image/jpeg", legenda: str = "", *,
                                grafo=None, leitor=None) -> ResultadoTurno:
    """L5: um turno com a foto do cliente. A imagem é lida (uma chamada de IA) e
    nunca é guardada: só a descrição curta vira a mensagem do cliente.
    Documento e falha de leitura: resposta fixa + chamado, sem passar pelo Léo.
    Carro: chamado de avaliação antes do Léo responder; troca anotada depois."""
    from app import imagens            # aqui dentro: o SDK de visão só carrega se precisar
    if porta_fechada(loja_id, canal, lead_id):          # P7: nem lê a foto (custo)
        return ResultadoTurno(silenciado=True)
    membro = _quem_da_equipe(loja_id, canal, lead_id)
    if membro:
        return ResultadoTurno(texto=MENSAGEM_EQUIPE_SO_TEXTO if pode_deixar_recado(membro)
                              else MENSAGEM_SO_DONO)
    if em_sombra(loja_id):          # L9: não lê a foto (custo) nem guarda o arquivo
        sombra.gravar(loja_id, lead_id, canal, f"[foto] {legenda}".strip(),
                      "(foto não lida no modo sombra)", [])
        return ResultadoTurno(silenciado=True)
    if estado_do_handoff(lead_id, loja_id) == "humano_assumiu":
        salvar_mensagem(lead_id, "cliente", "[foto]", canal=canal, tipo="imagem", loja_id=loja_id)
        return ResultadoTurno(silenciado=True)

    rotulo = _rotulo(canal, loja_id)
    leitura = imagens.ajustar_pela_legenda((leitor or imagens.ler_imagem)(imagem, mime), legenda)
    registrar_uso(loja_id, lead_id, canal, leitura.uso, tipo="imagem", ferramentas=["leitura_imagem"])
    print(f"{rotulo} Cliente {id_no_console(lead_id, canal)} mandou foto: {leitura.tipo if leitura.ok else 'não lida'}")
    if not leitura.ok:
        _anotar_falha_da_foto(loja_id, lead_id, canal, leitura)
    if leitura.ok and leitura.tipo == imagens.CARRO:     # L5c: sem julgamento de estado
        leitura.descricao = tirar_elogio_da_descricao(leitura.descricao)

    if not leitura.ok:
        return _com_leitura(_resposta_fixa_com_chamado(loja_id, canal, lead_id, "[foto não lida]",
                                                       MENSAGEM_IMAGEM_FALHOU, MOTIVO_IMAGEM_FALHOU,
                                                       leitura.uso), leitura)
    if leitura.tipo == imagens.DOCUMENTO:
        return _com_leitura(_resposta_fixa_com_chamado(loja_id, canal, lead_id, "[documento]",
                                                       MENSAGEM_DOCUMENTO, MOTIVO_DOCUMENTO,
                                                       leitura.uso), leitura)
    if leitura.tipo == imagens.CARRO:
        motivo = MOTIVO_AVALIACAO + (f' Pergunta do cliente: "{pergunta_curta(legenda)}"' if legenda.strip() else "")
        _chamado_da_foto(loja_id, lead_id, motivo, f"Foto do carro: {leitura.descricao}")

    resultado = await executar_turno(loja_id, canal, lead_id, imagens.texto_para_o_leo(leitura, legenda),
                                     grafo=grafo, tipo="imagem", foto_carro=leitura.tipo == imagens.CARRO)
    if leitura.tipo == imagens.CARRO:
        _anotar_foto_na_troca(loja_id, lead_id, leitura.descricao)
        resultado.handoff_aberto = True
    return _com_leitura(resultado, leitura)
