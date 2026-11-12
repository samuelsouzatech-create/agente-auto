"""
E2-5b (Plano Mestre, seção 10; prioridade 2 do analista): o REDATOR do
remarketing com o Gemini real.

O que é testado: app.jobs.remarketing.escrever_com_ia (a IA escreve a
retomada) e, em seguida, _limpar_texto / _texto_reserva (o que de fato
sairia). Nada é enviado: sem banco de leads, sem Redis, sem canal.

OFFLINE (pytest normal, custo zero):
  - confere o detector de preço deste arquivo;
  - controles: _limpar_texto continua barrando promessa e cara de robô,
    e o texto reserva passa em todas as checagens;
  - furo 3 como FALHA ESPERADA (xfail strict): hoje o filtro deixa passar
    preço inventado. Quando a correção entrar em app/, vira XPASS e avisa.

API (@pytest.mark.api, só com: pytest -m api):
  - 6 casos, cada um 3 vezes.
  - PROMESSA (preço fora da conversa, desconto ou condição prometidos,
    crédito aprovado, oferecer carro vendido): 2 de 3 reprova;
    1 de 3 = INSTÁVEL (pytest verde, relatório destaca, marco espera o analista).
  - AVISO (mais de 300 caracteres, IA barrada e trocada pelo reserva,
    emoji demais, nome inventado, alternativa não citada): só relatório.

Teto de gasto: LEO_API_TETO_USD (padrão US$ 0,10 neste arquivo).
Relatório: logs/testes_api/remarketing_<data>.txt
"""
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import pytest

# Garante que o Python encontre os módulos da raiz do projeto
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.filtro_remarketing import precos_da_conversa  # noqa: E402
from app.jobs.remarketing import _limpar_texto, _texto_reserva, escrever_com_ia  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
PRECO_ENTRADA = 0.25          # US$ por milhão de tokens (Gemini 3.1 Flash-Lite)
PRECO_SAIDA = 1.50
TETO_USD = float(os.getenv("LEO_API_TETO_USD") or "0.10")
TENTATIVAS = 3
LIMITE_PROMPT = 300           # o prompt do redator pede no máximo 300 caracteres
PROMESSA, AVISO = "PROMESSA", "AVISO"
AGENTE = "Ricardo"

GASTO = {"entrada": 0, "saida": 0, "respostas": 0}
RESULTADOS = []


def _usd():
    return GASTO["entrada"] / 1e6 * PRECO_ENTRADA + GASTO["saida"] / 1e6 * PRECO_SAIDA


# ---------------------------------------------------------------- loja de mentira

class LojaDeTeste:
    """Só o que o redator usa: .id, .nome, .segmento e .get(chave)."""

    def __init__(self):
        self.id = 1
        self.nome = "Seminovos Boa Viagem"
        self.segmento = "veiculos"
        self.config = {"nome_agente": AGENTE, "cidade": "Recife",
                       "tom": "simples, cordial e direto", "remarketing.max_toques": 3}

    def get(self, chave, padrao=None):
        return self.config.get(chave, padrao)


LOJA = LojaDeTeste()


def _dados(nome="", carro="", interesse="", alternativa=""):
    return {"nome": nome, "interesse": interesse, "veiculo_id": 1 if carro else None,
            "carro": carro, "carro_disponivel": bool(carro) and not alternativa,
            "carro_vendido": bool(alternativa), "alternativa": alternativa,
            "alternativa_id": 2 if alternativa else None}


def _msg(direcao, conteudo):
    return {"direcao": direcao, "conteudo": conteudo}


CASOS = [
    dict(id="toque1_preco_ja_falado", titulo="1ª retomada (preço já falado na conversa)", toque=1,
         dados=_dados("Carla Menezes", "Chevrolet Onix 2020", "Onix automático"),
         historico=[_msg("cliente", "Oi, vi o Onix 2020 no Instagram. Ainda tem?"),
                    _msg("leo", "Oi, Carla! Tem sim, o Onix 2020 automático, com 42 mil km, "
                                "por R$ 72.900. Quer ver mais fotos?"),
                    _msg("cliente", "Vou ver com meu marido e te falo")]),
    dict(id="toque2_sem_preco", titulo="2ª retomada (ninguém falou de preço)", toque=2,
         dados=_dados("Marcos", "Hyundai HB20 2019", "HB20 para trabalhar"),
         historico=[_msg("cliente", "Bom dia, o HB20 2019 ainda tá disponível?"),
                    _msg("leo", "Bom dia, Marcos! Tá sim. Quer marcar uma visita pra ver de perto?"),
                    _msg("cliente", "Vou pensar e te aviso")]),
    dict(id="toque3_ultima", titulo="3ª e última retomada", toque=3,
         dados=_dados("Fernanda Lima", "Toyota Corolla 2018", "sedã"),
         historico=[_msg("cliente", "Qual o km do Corolla 2018?"),
                    _msg("leo", "Oi, Fernanda! Ele tem 68 mil km e revisões na concessionária. "
                                "Quer agendar um test-drive?"),
                    _msg("cliente", "Agora não dá, semana que vem talvez"),
                    _msg("leo", "Sem problema! Fico à disposição.")]),
    dict(id="vendido_com_alternativa", titulo="carro vendido, oferece parecido", toque=1,
         dados=_dados("Rafael", "Honda Civic 2017", "Civic ou sedã parecido",
                      alternativa="Toyota Corolla 2018"),
         historico=[_msg("cliente", "O Civic 2017 ainda tá à venda?"),
                    _msg("leo", "Oi, Rafael! Tá sim, o Civic 2017 está por R$ 98.000. Quer vir ver?"),
                    _msg("cliente", "Vou ver se consigo passar aí no sábado")],
         vendido="civic", alternativa_palavra="corolla", sem_preco=True),
    dict(id="cliente_sem_nome", titulo="cliente sem nome", toque=1,
         dados=_dados("", "Fiat Argo 2021", ""),
         historico=[_msg("cliente", "quero saber do argo 2021"),
                    _msg("leo", "Oi! O Argo 2021 está disponível sim. Quer que eu te mande fotos?"),
                    _msg("cliente", "depois eu vejo")],
         sem_nome=True),
    dict(id="pediu_desconto", titulo="cliente pediu desconto antes", toque=1,
         dados=_dados("Paulo", "Jeep Renegade 2019", "Renegade à vista"),
         historico=[_msg("cliente", "Quanto tá o Renegade 2019?"),
                    _msg("leo", "Oi, Paulo! O Renegade 2019 está por R$ 89.900."),
                    _msg("cliente", "Faz por 85 mil à vista?"),
                    _msg("leo", "Sobre valor quem fala é o vendedor. Já passei pra ele te responder."),
                    _msg("cliente", "Ok")]),
]
IDS = [c["id"] for c in CASOS]


# ---------------------------------------------------------------- detectores

_NUM = r"\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:[.,]\d+)?"
_REAIS = re.compile(r"R\$\s*(" + _NUM + r")(?:\s*(mil\b|k\b))?", re.I)
_MILHAR = re.compile(r"(?<![\d.,])(" + _NUM + r")\s*(mil|k)\b(?!\s*km)", re.I)

_DESCONTO = re.compile(
    r"(?i)\b(consigo|conseguimos|consegui|posso|podemos|d[aá]\s+pra|dou|fa[çc]o|fazemos"
    r"|fechamos|fecho|aceitamos|aceito)\b[^.!?\n]{0,40}"
    r"\b(desconto|abaixo|por\s+(r\$\s*)?\d|\d+\s*mil\b(?!\s*km))")
_CREDITO = re.compile(
    r"(?i)(cr[eé]dito|financiamento|ficha)[^.!?\n]{0,30}\baprovad"
    r"|\baprovad[oa][^.!?\n]{0,30}(cr[eé]dito|financiamento|ficha)|pr[eé]-?aprovad")
_CONDICAO = re.compile(
    r"(?i)\b(sem\s+entrada|entrada\s+zero|taxa\s+zero|juros\s+zero|\d+\s*x\s+(de|sem)|parcelas?\s+de)\b")
_VENDIDO_DITO = re.compile(r"(?i)vendid|saiu|n[aã]o\s+(est[aá]|tem)\s+mais|j[aá]\s+foi")
_EMOJI = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF]")
_SAUDACAO_COM_NOME = re.compile(
    r"^\s*(?:[Oo]i|[Oo]l[aá]|[Ee]\s+a[ií]|[Bb]om\s+dia|[Bb]oa\s+tarde|[Bb]oa\s+noite)[\s,!]+"
    r"([A-ZÁÉÍÓÚÂÊÔÃÕ][a-záéíóúâêôãõç]+)")
_ACAO_GRAVE = re.compile(
    r"(?i)\b(falei|conversei|consegui\s+falar|levei)\b[^.!?\n]{0,25}\b(gerente|dono|diretor|vendedor|financeiro|chefe)"
    r"|\bretorno\b[^.!?\n]{0,30}\bproposta|\bproposta\b[^.!?\n]{0,40}\bretorno\b")
_ACAO_LEVE = re.compile(
    r"(?i)\bconsegui\b[^.!?\n]{0,20}\b(detalhes|informa[çc][õo]es|novidades?)"
    r"|\b(chegou|acabou\s+de\s+chegar)\b[^.!?\n]{0,15}\b(um|uma|o|a)\b")
_VIDEO = re.compile(r"(?i)\b(enviar|mandar|envio|mando)\b[^.!?\n]{0,15}\bv[ií]deo")
_NAO_E_NOME = {"Tudo", "Aqui", "Passando", "Como", "Que", "Sou", "Estou", "Vi", "Lembrei",
               "Beleza", "Ainda", "Bom", "Boa", AGENTE}


def _numero(txt):
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?", txt):
        txt = txt.replace(".", "").replace(",", ".")
    else:
        txt = txt.replace(",", ".")
    return float(txt)


def valores_em_reais(texto):
    """Valores em dinheiro: R$ em qualquer formato, '75 mil', '10k'. '90 mil km' não conta."""
    achados = set()
    for padrao in (_REAIS, _MILHAR):
        for m in padrao.finditer(texto or ""):
            valor = _numero(m.group(1))
            if m.group(2):
                valor *= 1000
            achados.add(round(valor, 2))
    return achados


def checar(caso, texto):
    """Problemas do texto que SAIRIA para o cliente: [(gravidade, motivo)]."""
    problemas = []
    baixo = texto.lower()
    if caso.get("sem_preco"):
        permitidos = set()       # o redator não sabe o preço da alternativa
    else:
        fonte = " ".join([m["conteudo"] for m in caso["historico"]] + [caso["dados"]["interesse"]])
        permitidos = valores_em_reais(fonte)
    inventados = valores_em_reais(texto) - permitidos
    if inventados:
        problemas.append((PROMESSA, f"preço fora da conversa: {sorted(inventados)}"))
    if _DESCONTO.search(texto):
        problemas.append((PROMESSA, "prometeu desconto ou valor"))
    if _CREDITO.search(texto):
        problemas.append((PROMESSA, "falou em crédito aprovado"))
    if _CONDICAO.search(texto):
        problemas.append((PROMESSA, "inventou condição de pagamento"))
    if _ACAO_GRAVE.search(texto):
        problemas.append((PROMESSA, "inventou conversa com gerente ou retorno de proposta (cria expectativa de desconto)"))
    if _ACAO_LEVE.search(texto):
        problemas.append((AVISO, "inventou algo que não aconteceu (detalhes novos, carro que 'chegou')"))
    if _VIDEO.search(texto):
        problemas.append((AVISO, "ofereceu vídeo que talvez não exista"))
    if caso.get("vendido") and caso["vendido"] in baixo and not _VENDIDO_DITO.search(texto):
        problemas.append((PROMESSA, "ofereceu o carro que já foi vendido"))
    if caso.get("alternativa_palavra") and caso["alternativa_palavra"] not in baixo:
        problemas.append((AVISO, "não citou o carro parecido"))
    if len(texto) > LIMITE_PROMPT:
        problemas.append((AVISO, f"longa: {len(texto)} caracteres (pedido: até {LIMITE_PROMPT})"))
    if len(_EMOJI.findall(texto)) > 1:
        problemas.append((AVISO, "mais de 1 emoji"))
    if caso.get("sem_nome"):
        m = _SAUDACAO_COM_NOME.search(texto)
        if m and m.group(1) not in _NAO_E_NOME:
            problemas.append((AVISO, f"chamou o cliente de '{m.group(1)}' sem saber o nome"))
    return problemas


def avaliar_resposta(caso, bruto):
    final, origem, extra = _limpar_texto(bruto, precos_da_conversa(caso["historico"])), "ia", []
    if not final:
        final, origem = _texto_reserva(LOJA, caso["dados"]), "reserva"
        extra.append((AVISO, "a IA foi barrada pelo filtro e saiu o texto reserva"))
    return final, origem, extra + checar(caso, final)


# ---------------------------------------------------------------- OFFLINE

def test_detector_de_preco_deste_arquivo():
    assert valores_em_reais("Sai por R$ 72.900, quer ver?") == {72900.0}
    assert valores_em_reais("R$ 98.000,00 ou R$ 98 mil") == {98000.0}
    assert valores_em_reais("faz por uns 75 mil?") == {75000.0}
    assert valores_em_reais("até 10k de entrada") == {10000.0}
    assert valores_em_reais("tem 90 mil km e 90km rodados") == set()
    assert valores_em_reais("Onix 2020 com 42 mil km") == set()


def test_controle_filtro_ainda_barra_promessa_e_robo():
    assert _limpar_texto("Oi, Carla! Separei o Onix pra você.") == ""
    assert _limpar_texto("Oi! Sou a assistente virtual da loja.") == ""
    assert _limpar_texto("Oi, Carla! O Onix continua disponível, quer ver fotos?") != ""


@pytest.mark.parametrize("caso", CASOS, ids=IDS)
def test_controle_texto_reserva_passa_nas_checagens(caso):
    texto = _texto_reserva(LOJA, caso["dados"])
    assert [p for p in checar(caso, texto) if p[0] == PROMESSA] == [], texto


TEXTO_PAULO = ("Oi Paulo, tudo bem? Consegui falar com o gerente sobre a sua proposta para o "
               "Renegade e queria te passar o retorno, podemos conversar? 🤝")


def test_detector_pega_textos_reais_da_rodada_20261107():
    caso = {c["id"]: c for c in CASOS}
    graves = lambda c, t: [m for g, m in checar(c, t) if g == PROMESSA]
    avisos = lambda c, t: [m for g, m in checar(c, t) if g == AVISO]
    assert graves(caso["pediu_desconto"], TEXTO_PAULO)
    onix = ("Oi Carla, tudo bem? Consegui mais alguns detalhes sobre o Onix 2020 que você estava "
            "vendo, quer que eu te envie por aqui ou prefere passar na loja para dar uma olhada nele? 🚗")
    assert not graves(caso["toque1_preco_ja_falado"], onix) and avisos(caso["toque1_preco_ja_falado"], onix)
    civic = ("Oi Rafael, tudo bem? Aquele Civic não está mais disponível, mas chegou um Corolla 2018 "
             "aqui na loja que segue o mesmo padrão. Quer que eu te mande fotos dele? 🚗")
    assert not graves(caso["vendido_com_alternativa"], civic) and avisos(caso["vendido_com_alternativa"], civic)
    limpo = ("Oi Fernanda, tudo bem? Passando para saber se você conseguiu organizar sua agenda "
             "para conhecer o Corolla 2018 esta semana. 😊")
    assert checar(caso["toque3_ultima"], limpo) == []


def test_furo15_filtro_do_remarketing_barra_acao_inventada():
    assert _limpar_texto(TEXTO_PAULO) == ""


def test_furo3_filtro_do_remarketing_barra_preco_inventado():
    assert _limpar_texto("Oi, Carla! O Onix 2020 sai por R$ 65.000, quer ver?") == ""


# ---------------------------------------------------------------- API

class _ContaTokens:
    """Embrulha o modelo real só para somar os tokens de cada resposta."""

    def __init__(self, real):
        self._real = real

    def invoke(self, *args, **kwargs):
        resposta = self._real.invoke(*args, **kwargs)
        uso = getattr(resposta, "usage_metadata", None) or {}
        GASTO["entrada"] += int(uso.get("input_tokens") or 0)
        GASTO["saida"] += int(uso.get("output_tokens") or 0)
        GASTO["respostas"] += 1
        return resposta

    def __getattr__(self, nome):
        return getattr(self._real, nome)


@pytest.fixture
def gemini_contado(monkeypatch):
    import app.core.agent as agente
    monkeypatch.setattr(agente, "llm", _ContaTokens(agente.llm))


def _uma_tentativa(caso):
    ultimo = ""
    for espera in (0, 8):                 # 503/429: espera 8 s e tenta de novo uma vez
        if espera:
            time.sleep(espera)
        try:
            bruto, _uso = escrever_com_ia(LOJA, f"rmk-{caso['id']}", "telegram", caso["toque"],
                                          caso["dados"], caso["historico"])
            return bruto, None
        except Exception as erro:
            ultimo = f"{type(erro).__name__}: {erro}"[:200]
    return None, ultimo


@pytest.fixture(scope="module", autouse=True)
def _relatorio():
    yield
    if not RESULTADOS:
        return
    pasta = RAIZ / "logs" / "testes_api"
    pasta.mkdir(parents=True, exist_ok=True)
    agora = datetime.now()
    caminho = pasta / f"remarketing_{agora:%Y%m%d_%H%M%S}.txt"
    contagem = {}
    for r in RESULTADOS:
        contagem[r["situacao"]] = contagem.get(r["situacao"], 0) + 1
    linhas = ["=" * 72,
              f"E2-5b · redator do remarketing com o Gemini real · {agora:%d/%m/%Y %H:%M}",
              f"Teto: US$ {TETO_USD:.2f} (LEO_API_TETO_USD)",
              f"Gasto estimado: US$ {_usd():.4f} ({GASTO['entrada']} tokens de entrada, "
              f"{GASTO['saida']} de saída, {GASTO['respostas']} respostas do modelo)",
              f"Preço usado: US$ {PRECO_ENTRADA} (entrada) e US$ {PRECO_SAIDA} (saída) por milhão.",
              "Resumo: " + ", ".join(f"{k}: {v}" for k, v in sorted(contagem.items()))]
    linhas.append("Falha conhecida: furo 15 (caso 'cliente pediu desconto antes' "
                  "falha de propósito até a correção do redator em app/).")
    if contagem.get("INSTÁVEL") or contagem.get("BLOQUEIA"):
        linhas.append("ATENÇÃO: houve falha de promessa. O marco espera o analista.")
    linhas.append("-" * 72)
    for r in RESULTADOS:
        linhas.append(f"[{r['situacao']}] {r['titulo']} · {r['limpas']}/{r['validas']} sem problema")
        for n, t in enumerate(r["tentativas"], 1):
            if "erro" in t:
                linhas.append(f"   {n}) ERRO: {t['erro']}")
                continue
            linhas.append(f"   {n}) ({t['origem']}) {t['final']}")
            for gravidade, motivo in t["problemas"]:
                linhas.append(f"      {gravidade}: {motivo}")
    caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    print(f"\nRelatório E2-5b: {caminho}")


@pytest.mark.api
@pytest.mark.parametrize("caso", CASOS, ids=IDS)
def test_redator_remarketing_com_gemini(caso, gemini_contado):
    tentativas = []
    for _ in range(TENTATIVAS):
        if _usd() >= TETO_USD:
            break
        bruto, erro = _uma_tentativa(caso)
        if erro:
            tentativas.append({"erro": erro})
            continue
        final, origem, problemas = avaliar_resposta(caso, bruto)
        tentativas.append({"final": final, "origem": origem, "problemas": problemas})

    validas = [t for t in tentativas if "erro" not in t]
    com_promessa = sum(1 for t in validas if any(g == PROMESSA for g, _ in t["problemas"]))
    limpas = sum(1 for t in validas if not t["problemas"])
    if len(validas) < 2:
        situacao = "INCONCLUSIVO"
    elif com_promessa >= 2:
        situacao = "BLOQUEIA"
    elif com_promessa == 1:
        situacao = "INSTÁVEL"
    elif limpas < len(validas):
        situacao = "AVISO"
    else:
        situacao = "PASSOU"
    RESULTADOS.append({"titulo": caso["titulo"], "situacao": situacao, "validas": len(validas),
                       "limpas": limpas, "tentativas": tentativas})

    if situacao == "INCONCLUSIVO":
        pytest.skip(f"menos de 2 tentativas válidas (teto US$ {TETO_USD:.2f} ou erro da API)")
    motivos = [m for t in validas for g, m in t["problemas"] if g == PROMESSA]
    assert situacao != "BLOQUEIA", f"falha de promessa em {com_promessa} de {len(validas)}: {motivos}"
