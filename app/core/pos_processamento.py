"""
Pós-processamento da resposta do Léo, numa lista ÚNICA e ordenada (Maratona 3, N4 / revisão #9).

Depois que a IA responde, o texto passa por estes passos, NESTA ordem (cada um é uma função com nome):

     1. texto_interno           [..], "Motivo...:", "---", repetição do motivo/resumo do chamado
     2. preco_inventado         valor em R$ sem origem em ferramenta -> mensagem segura + chamado
     3. frases_proibidas        "já estou acompanhando" etc.
     4. regra_de_entrada        entrada afirmada como regra -> "depende da análise"
     5. risco_e_politica        pix, reserva, entrega...; política sem base
     6. promessa_de_foto        disse que mandou foto, mas nenhuma saiu
     7. elogio_da_foto          elogio ao estado do carro da foto do cliente
     8. estado_sem_ficha        estado/qualidade do carro só se veio da ficha
     9. agendamento             "agendei" só se a agenda gravou; test-drive lembra a CNH
    10. chamado_pelo_codigo     troca, laudo/leilão/IPVA, contato prometido sem chamado
    11. pos_venda_e_urgencia    cliente irritado ou problema de quem comprou
    12. aviso_de_chamado        chamado do código e a resposta não avisa o cliente
    13. falso_dono              número fora da equipe dizendo ser da loja
    14. emoji                   limite de emoji
    15. repeticoes              contato/horário/frase repetidos; pergunta solta
    16. frase_de_oferta         a guarda tirou a pergunta e não sobrou nenhuma nem ação gravada

Mudar a ordem muda o comportamento: um passo novo entra AQUI, com nome, no lugar certo.
Os passos buscam as guardas pelo módulo app.core.turno (os testes trocam funções por lá).
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field


def _t():
    """O módulo do turno, na hora (sem import circular e respeitando o que os testes trocam)."""
    return sys.modules["app.core.turno"]


@dataclass
class Contexto:
    loja_id: int
    canal: str
    lead_id: str
    texto: str                 # o que o cliente escreveu
    do_turno: list             # mensagens deste turno (IA e ferramentas)
    mensagens: list            # todas as mensagens do grafo (para a guarda de preço)
    rotulo: str
    resposta: str
    midias: list
    handoff: bool
    ferramentas: list
    foto_carro: bool = False
    resposta_inicial: str = ""
    abriu_pelo_codigo: bool = False
    guarda_mexeu: bool = False
    log: list = field(default_factory=list)

    def avisar(self, mensagem: str) -> None:
        print(f"{self.rotulo} {mensagem}")


def texto_interno(c: Contexto) -> None:
    t = _t()
    c.resposta, interno = t.tirar_texto_interno(c.resposta, t.internos_do_turno(c.do_turno))
    if interno:
        c.avisar("GUARDA: texto interno ([...], Resumo:, ferramenta) tirado da resposta.")
    c.resposta_inicial = c.resposta                      # L12: para saber se alguma guarda mexeu


def preco_inventado(c: Contexto) -> None:
    t = _t()
    if not t.resposta_tem_preco_inventado(c.resposta, c.mensagens):
        return
    c.avisar("GUARDA: preço inventado detectado. Acionando handoff.")
    c.avisar(f"Resposta barrada: {t.texto_no_console(c.resposta, c.canal)}")
    t.acionar_handoff.func(motivo="Guarda de política: valor em R$ sem origem em tool.",
                           resumo=f"Resposta barrada do Léo: {c.resposta}", lead_id=c.lead_id, loja_id=c.loja_id)
    c.resposta, c.midias, c.handoff = t.MENSAGEM_SEGURA, [], True
    c.ferramentas.append("guarda_preco")


def frases_proibidas(c: Contexto) -> None:
    c.resposta, trocou = _t().trocar_frases_proibidas(c.resposta)
    if trocou:
        c.avisar("GUARDA: frase proibida trocada.")
        c.ferramentas.append("guarda_frase")


def regra_de_entrada(c: Contexto) -> None:
    c.resposta, trocou = _t().corrigir_regra_de_entrada(c.resposta)
    if trocou:
        c.avisar("GUARDA: regra de entrada trocada por 'depende da análise'.")
        c.ferramentas.append("guarda_entrada")


def risco_e_politica(c: Contexto) -> None:
    t = _t()
    c.resposta, riscos = t.trocar_frases_de_risco(c.resposta)      # L8: pix, reserva, entrega, preço...
    c.resposta, politicas = t.trocar_politica_sem_base(c.resposta)  # L11: "não trabalhamos com..." sem base
    riscos += [f"politica_{p}" for p in politicas]
    if riscos:
        c.avisar(f"GUARDA: frase de risco trocada ({', '.join(riscos)}).")
        c.ferramentas.append("guarda_risco")


def promessa_de_foto(c: Contexto) -> None:
    if c.midias:                         # L7: só quando nenhuma foto saiu
        return
    c.resposta, trocou = _t().tirar_promessa_de_foto(c.resposta)
    if trocou:
        c.avisar("GUARDA: promessa de foto sem foto enviada trocada.")
        c.ferramentas.append("guarda_foto")


def elogio_da_foto(c: Contexto) -> None:
    if not c.foto_carro:
        return
    c.resposta, trocou = _t().tirar_elogio_do_estado(c.resposta)
    if trocou:
        c.avisar("GUARDA: elogio ao estado do carro da foto retirado.")
        c.ferramentas.append("guarda_elogio")


def estado_sem_ficha(c: Contexto) -> None:
    t = _t()
    c.resposta, trocou = t.cortar_estado_inventado(c.resposta, t._fichas_do_turno(c.do_turno),
                                                   substituir=not t._comprou_na_loja(c.loja_id, c.lead_id))
    if trocou:
        c.avisar("GUARDA: estado do carro sem ficha cortado.")
        c.ferramentas.append("guarda_estado")


def agendamento(c: Contexto) -> None:
    t = _t()
    agenda = t._agenda_do_turno(c.do_turno)
    if agenda is None:
        c.resposta, trocou = t.tirar_agendamento_falso(c.resposta)
        if trocou:
            c.avisar("GUARDA: agendamento dito sem a ferramenta gravar; vira pedido à equipe.")
            c.ferramentas.append("guarda_agenda")
    elif "test-drive" in agenda.lower() and "cnh" not in c.resposta.lower():
        c.resposta = f"{c.resposta} {t.FRASE_CNH}"


def chamado_pelo_codigo(c: Contexto) -> None:
    t = _t()
    motivo_guarda = t.motivo_do_chamado_pelo_codigo(c.texto, c.resposta, t._aceita_troca(c.loja_id))
    if not (motivo_guarda and not c.handoff and t.estado_do_handoff(c.lead_id, c.loja_id) == "ativo"):
        return
    motivo, nome_guarda = motivo_guarda
    c.avisar(f"GUARDA: {motivo} Abrindo chamado.")
    t.acionar_handoff.func(motivo=f'{motivo} Pergunta do cliente: "{t.pergunta_curta(c.texto)}"',
                           resumo=f"Resposta do Léo: {c.resposta}", lead_id=c.lead_id, loja_id=c.loja_id)
    c.handoff = True
    c.ferramentas.append(nome_guarda)
    c.abriu_pelo_codigo = True


def pos_venda_e_urgencia(c: Contexto) -> None:
    if _t().marcar_pos_venda_e_urgencia(c.loja_id, c.lead_id, c.texto):
        c.handoff = True
        c.ferramentas.append("guarda_pos_venda")
        c.abriu_pelo_codigo = True


def aviso_de_chamado(c: Contexto) -> None:
    t = _t()
    if c.abriu_pelo_codigo and not t._avisa_contato(c.resposta):
        c.resposta = f"{c.resposta} {t.FRASE_CONTATO}"
        c.ferramentas.append("guarda_aviso_chamado")


def falso_dono(c: Contexto) -> None:
    if _t().marcar_falso_dono(c.loja_id, c.lead_id, c.texto):
        c.handoff = True
        c.ferramentas.append("guarda_falso_dono")


def emoji(c: Contexto) -> None:
    t = _t()
    c.resposta, tirados = t.limitar_emojis(c.resposta, t.limite_de_emojis(c.loja_id, c.lead_id, c.texto, c.handoff))
    if tirados:
        c.ferramentas.append("guarda_emoji")


def repeticoes(c: Contexto) -> None:
    c.guarda_mexeu = c.resposta != c.resposta_inicial
    c.resposta = _t().limpar_repeticoes(c.resposta, guarda_mexeu=c.guarda_mexeu, pergunta=c.texto)


def frase_de_oferta(c: Contexto) -> None:
    t = _t()
    if t.precisa_da_frase_de_oferta(c.guarda_mexeu, c.resposta_inicial, c.resposta, c.handoff,
                                    c.ferramentas, c.texto):
        c.resposta = f"{c.resposta} {t.FRASE_OFERTA}"


PASSOS = (
    texto_interno,
    preco_inventado,
    frases_proibidas,
    regra_de_entrada,
    risco_e_politica,
    promessa_de_foto,
    elogio_da_foto,
    estado_sem_ficha,
    agendamento,
    chamado_pelo_codigo,
    pos_venda_e_urgencia,
    aviso_de_chamado,
    falso_dono,
    emoji,
    repeticoes,
    frase_de_oferta,
)


def pos_processar(c: Contexto) -> Contexto:
    """Roda os passos na ordem de PASSOS. Devolve o mesmo contexto, com resposta/mídias/chamado finais."""
    for passo in PASSOS:
        passo(c)
    return c
