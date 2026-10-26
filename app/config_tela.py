"""
Como cada variável da loja aparece na tela de Configuração (Etapa 1, item 1.8).

Separado do Streamlit para dar para testar a conversão
"valor da tela" <-> "valor da configuração" sem abrir o painel.
Regra: toda chave de EDITAVEIS (app/lojas.py) precisa de um Campo aqui
(um teste cobra isso).
"""
from __future__ import annotations

from dataclasses import dataclass

from app.lojas import MODULOS, PADROES, Loja, pendentes

DIAS = ("Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom")

GRUPOS = ("Identidade", "Atendimento", "Módulos", "Handoff", "Financiamento",
          "Remarketing", "Pós-venda", "Instagram", "Custos e dados")

NOTAS_GRUPO = {
    "Módulos": "Agendamento e fotos já ligam e desligam as ferramentas do agente. "
               "WhatsApp, Instagram, remarketing e pós-venda passam a valer na etapa de cada um.",
    "Remarketing": "Pode configurar desde já. Os envios começam na Etapa 2.",
    "Pós-venda": "Pode configurar desde já. O pós-venda começa na Etapa 2.",
    "Instagram": "Pode configurar desde já. O Instagram chega na Etapa 3.",
    "Custos e dados": "O custo começa a ser medido no Bloco 6.",
}

ROTULO_OPCAO = {
    "conversar": "Continua conversando",
    "esperar": "Manda uma mensagem de espera e fica quieto",
    "meio_termo": "Meio-termo: segue em assuntos simples, recusa preço e crédito",
}

_ROTULO_MODULO = {
    "whatsapp": "WhatsApp", "instagram": "Instagram",
    "agendamento": "Agendamento de visita e test-drive", "fotos": "Envio de fotos",
    "remarketing": "Remarketing", "pos_venda": "Pós-venda",
}


@dataclass(frozen=True)
class Campo:
    chave: str
    rotulo: str
    tipo: str       # texto, texto_longo, inteiro, decimal, percentual, sim_nao, horario, dias,
                    # opcao, lista_numeros, lista_palavras, todos_ou_lista,
                    # inteiro_opcional, decimal_opcional
    grupo: str
    ajuda: str = ""
    opcoes: tuple = ()


CAMPOS: tuple[Campo, ...] = (
    Campo("nome_agente", "Nome do agente", "texto", "Identidade"),
    Campo("cidade", "Cidade", "texto", "Identidade"),
    Campo("tom", "Tom de voz", "texto_longo", "Identidade",
          "Como o agente fala, ex.: 'simples, cordial e direto'."),
    Campo("fuso", "Fuso horário", "texto", "Identidade",
          'Ex.: "America/Recife", "America/Sao_Paulo".'),
    Campo("atendimento.horario_humano", "Horário do atendimento humano", "horario",
          "Atendimento", 'Formato "09:00-18:00".'),
    Campo("atendimento.dias_humano", "Dias do atendimento humano", "dias", "Atendimento"),
    Campo("atendimento.debounce_s", "Espera para juntar mensagens seguidas (segundos)",
          "decimal", "Atendimento",
          "Medição. Hoje o código ainda usa 8 s fixos; este valor passa a ser lido mais adiante."),
    Campo("atendimento.aguardando_vendedor", "O que o agente faz enquanto espera o vendedor",
          "opcao", "Atendimento", "Passa a valer no Bloco 7 (decisão 1.12).",
          ("conversar", "esperar", "meio_termo")),
    *(Campo(f"modulos.{m}", _ROTULO_MODULO[m], "sim_nao", "Módulos") for m in MODULOS),
    Campo("handoff.reaviso_min", "Minutos até o re-aviso ao vendedor", "inteiro", "Handoff",
          "Já define a cor amarela da fila. O re-aviso automático chega no Bloco 7."),
    Campo("handoff.gestor_min", "Minutos até avisar o gestor", "inteiro", "Handoff",
          "Já define a cor vermelha da fila."),
    Campo("financiamento.taxa_mensal", "Taxa da simulação", "percentual", "Financiamento",
          "Usada nas simulações do agente. Entre 0,1% e 6% ao mês."),
    Campo("remarketing.primeiro_toque_h", "Horas sem resposta até o 1º toque", "inteiro",
          "Remarketing", "Mínimo de 24 h (regra do produto)."),
    Campo("remarketing.intervalos_h", "Intervalos entre toques (horas)", "lista_numeros",
          "Remarketing", 'Separados por vírgula, ex.: "48, 120, 288". Cada um com no mínimo 24.'),
    Campo("remarketing.max_toques", "Máximo de toques por lead", "inteiro", "Remarketing",
          "No máximo 3 (regra do produto)."),
    Campo("remarketing.horario_envio", "Horário de envio", "horario", "Remarketing",
          "Entre 08:00 e 21:00."),
    Campo("remarketing.dias_envio", "Dias de envio", "dias", "Remarketing"),
    Campo("remarketing.limite_mensal", "Limite mensal de envios", "inteiro_opcional",
          "Remarketing", "Deixe vazio enquanto não estiver no contrato."),
    Campo("pos_venda.revisao_meses", "Revisão: a cada quantos meses", "inteiro", "Pós-venda"),
    Campo("pos_venda.revisao_km", "Revisão: a cada quantos km", "inteiro", "Pós-venda"),
    Campo("pos_venda.troca_avista_meses", "Reabordar troca (compra à vista) após quantos meses",
          "inteiro", "Pós-venda"),
    Campo("pos_venda.troca_financiado_meses_restantes",
          "Reabordar troca (financiada) quando faltarem quantos meses", "inteiro", "Pós-venda"),
    Campo("instagram.responder_comentarios", "Responder comentários com mensagem privada",
          "sim_nao", "Instagram"),
    Campo("instagram.palavras_comentario", "Palavras que disparam a resposta",
          "lista_palavras", "Instagram", "Separadas por vírgula."),
    Campo("instagram.posts_comentario", "Posts que valem", "todos_ou_lista", "Instagram",
          '"todos" ou os ids dos posts separados por vírgula.'),
    Campo("instagram.resposta_publica", "Responder também em público", "sim_nao", "Instagram"),
    Campo("instagram.limite_private_replies_h", "Limite de respostas privadas por hora",
          "inteiro", "Instagram"),
    Campo("instagram.texto_private_reply", "Texto da resposta privada", "texto_longo", "Instagram"),
    Campo("custos.teto_diario_llm", "Teto diário de gasto com IA (alerta, R$)",
          "decimal_opcional", "Custos e dados", "Vazio = sem teto. Definido depois de medir."),
    Campo("dados.retencao_dias", "Guardar conversas por quantos dias", "inteiro_opcional",
          "Custos e dados", "Vazio = a definir com o advogado."),
)

ROTULO = {c.chave: c.rotulo for c in CAMPOS}
_POR_CHAVE = {c.chave: c for c in CAMPOS}


def campo(chave: str) -> Campo:
    return _POR_CHAVE[chave]


def padrao(c: Campo):
    valor = PADROES
    for parte in c.chave.split("."):
        valor = valor[parte]
    return valor


def formatar(c: Campo, valor) -> str:
    """Texto amigável de um valor (usado para mostrar o padrão)."""
    if valor is None:
        return "vazio"
    if c.tipo == "sim_nao":
        return "ligado" if valor else "desligado"
    if c.tipo == "percentual":
        return f"{valor * 100:.2f}% ao mês".replace(".", ",")
    if c.tipo == "dias":
        return ", ".join(DIAS[d] for d in valor)
    if c.tipo in ("lista_numeros", "lista_palavras"):
        return ", ".join(str(v) for v in valor)
    if c.tipo == "todos_ou_lista":
        return valor if isinstance(valor, str) else ", ".join(valor)
    if c.tipo == "opcao":
        return ROTULO_OPCAO.get(valor, str(valor))
    return str(valor) if valor != "" else "vazio"


def para_tela(c: Campo, valor):
    """Valor da configuração -> valor que o widget mostra."""
    if c.tipo == "percentual":
        return round(float(valor) * 100, 4)
    if c.tipo == "dias":
        return [DIAS[d] for d in valor]
    if c.tipo in ("lista_numeros", "lista_palavras"):
        return ", ".join(str(v) for v in valor)
    if c.tipo == "todos_ou_lista":
        return valor if isinstance(valor, str) else ", ".join(valor)
    if c.tipo == "inteiro_opcional":
        return "" if valor is None else str(valor)
    if c.tipo == "decimal_opcional":
        return "" if valor is None else str(valor).replace(".", ",")
    return valor


def _separar(texto) -> list[str]:
    return [p.strip() for p in str(texto).split(",") if p.strip()]


def da_tela(c: Campo, valor):
    """Valor do widget -> valor da configuração. Erro de digitação vira ValueError."""
    t = c.tipo
    if t == "percentual":
        return round(float(valor) / 100, 6)
    if t == "dias":
        return [DIAS.index(d) for d in valor]
    if t == "lista_numeros":
        try:
            return [int(p) for p in _separar(valor)]
        except ValueError:
            raise ValueError('use números inteiros separados por vírgula, ex.: "48, 120, 288"')
    if t == "lista_palavras":
        return _separar(valor)
    if t == "todos_ou_lista":
        texto = str(valor).strip()
        return "todos" if texto.lower() == "todos" else _separar(texto)
    if t == "inteiro_opcional":
        texto = str(valor).strip()
        if not texto:
            return None
        try:
            return int(texto)
        except ValueError:
            raise ValueError("use um número inteiro ou deixe vazio")
    if t == "decimal_opcional":
        texto = str(valor).strip().replace(",", ".")
        if not texto:
            return None
        try:
            return float(texto)
        except ValueError:
            raise ValueError("use um número ou deixe vazio")
    if t == "inteiro":
        return int(valor)
    if t == "decimal":
        return float(valor)
    if t == "sim_nao":
        return bool(valor)
    if t in ("texto", "texto_longo", "horario"):
        return str(valor).strip()
    return valor


def mudancas_da_tela(loja: Loja, valores: dict, confirmar: bool = False) -> tuple[dict, list[str]]:
    """Compara o que está na tela com a configuração atual.
    Entra em 'mudancas' o que mudou, e também o que ainda estava 'a confirmar'
    quando o usuário marca que o cliente confirmou."""
    faltam = set(pendentes(loja))
    mudancas, erros = {}, []
    for chave, valor_tela in valores.items():
        c = _POR_CHAVE[chave]
        try:
            novo = da_tela(c, valor_tela)
        except (ValueError, TypeError) as erro:
            erros.append(f"{c.rotulo}: {erro}")
            continue
        if novo != loja.get(chave) or (confirmar and chave in faltam):
            mudancas[chave] = novo
    return mudancas, erros


def traduzir_erro(mensagem: str) -> str:
    """'remarketing.max_toques: ...' -> 'Máximo de toques por lead: ...'"""
    chave, separador, resto = mensagem.partition(":")
    if separador and chave in ROTULO:
        return f"{ROTULO[chave]}:{resto}"
    return mensagem
