import re
from langchain_core.messages import ToolMessage

# Mensagem neutra que o cliente recebe quando a guarda barra a resposta.
# Nada de preço, nada de promessa: só avisa que um vendedor vai continuar.
MENSAGEM_SEGURA = (
    "Deixa eu confirmar esse valor certinho com um vendedor pra não te passar "
    "nada errado. Já já alguém da equipe continua com você por aqui. 👍"
)

# Captura valores no padrão do formatar_brl: R$ 98.000,00 / R$ 1.234,56 / R$ 500,00
_PADRAO_REAIS = re.compile(r"R\$\s*([\d\.]+,\d{2})")


def _extrair_valores(texto: str) -> set:
    """Extrai todos os valores em R$ de um texto e devolve só os números,
    normalizados (sem pontos de milhar, sem vírgula), para comparar com segurança.
    Ex.: 'R$ 98.000,00' -> '9800000'."""
    if not texto:
        return set()
    achados = _PADRAO_REAIS.findall(texto)
    return {bruto.replace(".", "").replace(",", "") for bruto in achados}


def _valores_das_tools(mensagens) -> set:
    """Junta todos os valores em R$ que as ToolMessages deste turno devolveram.
    Esses são os valores 'legítimos' que o Léo pode repetir pro cliente."""
    permitidos = set()
    for m in mensagens:
        if isinstance(m, ToolMessage):
            permitidos |= _extrair_valores(str(m.content))
    return permitidos


def resposta_tem_preco_inventado(resposta: str, mensagens) -> bool:
    """True se a resposta do Léo cita algum valor em R$ que NENHUMA tool
    deste turno devolveu — ou seja, um preço inventado."""
    citados = _extrair_valores(resposta)
    if not citados:
        return False  # sem valor nenhum, nada a checar
    permitidos = _valores_das_tools(mensagens)
    # Sobrou algum valor citado que não veio de tool?
    return bool(citados - permitidos)
