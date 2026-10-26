"""Monta o Léo de CADA loja: prompt em camadas e ferramentas por módulo.

Camadas do prompt (item 1.3 da Arquitetura 4.0):
  1. Identidade da loja (nome do agente, loja, tom, horário) - vem da config.
  2. prompts/base.md - regras duras, iguais para todas as lojas.
  3. segmentos/<segmento>/prompt.md - persona e objetivo do ramo.
  4. Guia das ferramentas LIGADAS nesta loja + avisos dos módulos desligados.
  5. Data e hora no fuso da loja.

Este módulo não cria o Gemini, então os testes podem importá-lo sem chave.
"""
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from app.leitura_config import valor_config
from tools import (
    consultar_estoque, detalhes_veiculo, enviar_fotos, simular_financiamento,
    registrar_troca, agendar_visita, registrar_lead, acionar_handoff,
    buscar_conhecimento,
)

RAIZ = Path(__file__).resolve().parents[2]
PASTA_PROMPTS = RAIZ / "prompts"
PASTA_SEGMENTOS = RAIZ / "segmentos"
FUSO_PADRAO = "America/Recife"

# --- Quais ferramentas cada loja recebe ---
FERRAMENTAS_DO_SEGMENTO = {
    "veiculos": [consultar_estoque, detalhes_veiculo, simular_financiamento, registrar_troca],
}
FERRAMENTAS_DE_MODULO = {
    "agendamento": [agendar_visita],
    "fotos": [enviar_fotos],
}
FERRAMENTAS_UNIVERSAIS = [registrar_lead, acionar_handoff, buscar_conhecimento]

TODAS_AS_FERRAMENTAS = [
    consultar_estoque, detalhes_veiculo, enviar_fotos, simular_financiamento,
    registrar_troca, agendar_visita, registrar_lead, acionar_handoff,
    buscar_conhecimento,
]

DESCRICOES = {
    "consultar_estoque": "o cliente pergunta sobre carros, modelos, preços ou disponibilidade.",
    "detalhes_veiculo": "o cliente quer saber mais de um carro específico que já apareceu na conversa.",
    "simular_financiamento": "o cliente pede simulação de parcelas (sempre com o aviso de estimativa).",
    "registrar_troca": "o cliente diz que tem um carro para dar na troca.",
    "agendar_visita": "o cliente quer visitar a loja, fazer test-drive ou receber uma ligação.",
    "enviar_fotos": ("o cliente pede fotos. Se ele não disser de qual carro "
                     "(ex.: 'manda o que tiver'), chame sem filtros: a ferramenta "
                     "diz quais carros têm fotos."),
    "registrar_lead": "quando já souber o interesse e algum dado do cliente.",
    "acionar_handoff": "OBRIGATÓRIO em qualquer caso vermelho (ver REGRA OBRIGATÓRIA DO HANDOFF).",
    "buscar_conhecimento": ("dúvidas sobre políticas da loja: financiamento, troca, "
                            "garantia, test-drive, horário de atendimento."),
}

AVISOS_MODULO_DESLIGADO = {
    "agendamento": ("Esta loja não agenda pelo chat. Se o cliente quiser visitar, "
                    "fazer test-drive ou receber ligação, registre o interesse com "
                    "registrar_lead e diga que um vendedor vai combinar o horário com ele."),
    "fotos": ("Esta loja não envia fotos pelo chat. Se o cliente pedir fotos, diga "
              "isso com naturalidade e ofereça a ficha do carro ou uma visita."),
}

NOMES_DIAS = ("segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo")
DIAS_SEMANA = ("segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
               "sexta-feira", "sábado", "domingo")


def modulo_ligado(loja, modulo: str) -> bool:
    return bool(valor_config(loja.config, f"modulos.{modulo}", False))


def segmento_da_loja(loja) -> str:
    return getattr(loja, "segmento", None) or "veiculos"


def ferramentas_da_loja(loja) -> list:
    """Segmento + módulos ligados + universais. O resto o Léo nem conhece."""
    lista = list(FERRAMENTAS_DO_SEGMENTO.get(segmento_da_loja(loja), []))
    for modulo, tools in FERRAMENTAS_DE_MODULO.items():
        if modulo_ligado(loja, modulo):
            lista.extend(tools)
    lista.extend(FERRAMENTAS_UNIVERSAIS)
    return lista


def fuso_da_loja(loja) -> ZoneInfo:
    try:
        return ZoneInfo(valor_config(loja.config, "fuso", FUSO_PADRAO))
    except Exception:
        return ZoneInfo(FUSO_PADRAO)


def descrever_dias(dias) -> str:
    try:
        dias = sorted({int(d) for d in dias if 0 <= int(d) <= 6})
    except (TypeError, ValueError):
        return ""
    if not dias:
        return ""
    if len(dias) > 2 and dias == list(range(dias[0], dias[-1] + 1)):
        return f"de {NOMES_DIAS[dias[0]]} a {NOMES_DIAS[dias[-1]]}"
    return ", ".join(NOMES_DIAS[d] for d in dias)


@lru_cache(maxsize=None)
def _ler_arquivo(caminho: str) -> str:
    # Lido uma vez por execução. Se editar um .md, reinicie o bot/servidor.
    return Path(caminho).read_text(encoding="utf-8").strip()


def _camada_da_loja(loja) -> str:
    cfg = loja.config
    nome_agente = valor_config(cfg, "nome_agente", "Léo")
    tom = valor_config(cfg, "tom", "simples, cordial e direto")
    cidade = valor_config(cfg, "cidade", "")
    linhas = [
        "IDENTIDADE (desta loja)",
        f"- Seu nome é {nome_agente}. Você é o assistente virtual da loja {loja.nome}"
        + (f", em {cidade}." if cidade else "."),
        f"- Tom de voz: {tom}.",
    ]
    horario = valor_config(cfg, "atendimento.horario_humano", "")
    dias = descrever_dias(valor_config(cfg, "atendimento.dias_humano", []))
    if horario and "-" in horario:
        inicio, fim = horario.split("-", 1)
        linhas.append(f"- Atendimento com vendedores: {dias}, das {inicio} às {fim}.".replace(": ,", ":"))
    return "\n".join(linhas)


def _guia_ferramentas(loja, ferramentas) -> str:
    linhas = ["QUANDO USAR CADA FERRAMENTA (só estas existem nesta loja)"]
    for f in ferramentas:
        linhas.append(f"- {f.name}: {DESCRICOES.get(f.name, f.description.strip().splitlines()[0])}")
    avisos = [texto for modulo, texto in AVISOS_MODULO_DESLIGADO.items()
              if not modulo_ligado(loja, modulo)]
    if avisos:
        linhas.append("")
        linhas.append("LIMITES DESTA LOJA")
        linhas.extend(f"- {a}" for a in avisos)
    return "\n".join(linhas)


def montar_prompt(loja, ferramentas, agora) -> str:
    base = _ler_arquivo(str(PASTA_PROMPTS / "base.md"))
    segmento = _ler_arquivo(str(PASTA_SEGMENTOS / segmento_da_loja(loja) / "prompt.md"))
    data = (f"DATA E HORA ATUAL: {agora.strftime('%d/%m/%Y %H:%M')} "
            f"({DIAS_SEMANA[agora.weekday()]}).")
    return "\n\n".join([
        _camada_da_loja(loja),
        base,
        segmento,
        _guia_ferramentas(loja, ferramentas),
        data,
    ])
