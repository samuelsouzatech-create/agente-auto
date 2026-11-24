"""
Catraca de RAMO (SG1, Maratona 4), no estilo da catraca de loja (tests/test_catraca_loja.py).

O motor (app/ e tools/) serve para qualquer ramo. Então:
1. o motor nunca importa um ramo pelo nome (segmentos.veiculos, nem por texto);
2. o motor não tem palavras de carro (lista PALAVRAS_DE_CARRO abaixo).

Código ANTIGO que ainda tem palavra de carro fica na lista LEGADO, (arquivo, palavra), cada um com
o porquê. A lista SÓ PODE DIMINUIR: quando a palavra sai do arquivo, o segundo teste pede para
apagar a linha daqui. Arquivo novo com palavra de carro reprova (vai para segmentos/veiculos/).

O que esta catraca NÃO olha (anotado no docs/maratona4.md): as palavras "carro" e "veículo"
(aparecem em ~40 arquivos do motor, em textos ao cliente e nomes como `veiculo_id` das tabelas
que o contrato da API mantém) e os nomes de ferramentas de ramo citados em texto.
"""
import ast
import re
import unicodedata
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PASTAS_DO_MOTOR = ("app", "tools")

# Palavras de carro (comparadas sem acento e em minúsculas, palavra inteira).
PALAVRAS_DE_CARRO = ("km", "kms", "quilometragem", "quilometro", "quilometros", "rodagem", "cambio",
                     "suv", "suvs", "seda", "sedas", "sedan", "sedans", "hatch", "hatchs", "hatchback",
                     "picape", "picapes", "pickup", "placa", "placas")
_PALAVRA = re.compile(r"\b(" + "|".join(PALAVRAS_DE_CARRO) + r")\b")

# (arquivo, palavra): o porquê de cada um está no comentário. Só pode DIMINUIR.
LEGADO = {
    # Contrato da API v1 e tabela estoque NÃO mudam (regra do SG2 e do CLAUDE.md): o painel lê e
    # grava km e câmbio do carro por estas rotas. Sai quando o estoque virar "catálogo" do ramo
    # também na API (contrato v2, decisão do analista).
    ("app/api_painel/carros.py", "cambio"), ("app/api_painel/carros.py", "km"),
    ("app/api_painel/rotas_estoque.py", "cambio"), ("app/api_painel/rotas_estoque.py", "km"),
    ("app/api_painel/rotas_estoque.py", "quilometragem"),
    ("app/painel_leitura.py", "km"),                # ficha da troca na conversa (contrato da API)
    # A tabela estoque (com km e câmbio) e quem a lê direto: o operador e o painel usam estas
    # funções. No SG2 o pacote de veículos implementa o catálogo POR CIMA delas.
    ("app/estoque.py", "cambio"), ("app/estoque.py", "km"),
    ("app/estoque_conhecimento.py", "cambio"), ("app/estoque_conhecimento.py", "km"),
    # A loja de demonstração é uma loja de carros (estoque fictício). Destino: segmentos/<ramo>/demo.
    ("app/demo.py", "cambio"), ("app/demo.py", "km"), ("app/demo.py", "placa"),
    ("app/demo.py", "quilometragem"),
    # Campo de configuração do pós-venda (revisão a cada X km), com padrão e validação em
    # app/lojas.py. Destino: segmentos/<ramo>/configuracao.py (previsto no contrato, não feito).
    ("app/config_tela.py", "km"),
    # Câmbio do DÓLAR (custo da IA), não de carro. Fica para sempre.
    ("app/custos.py", "cambio"), ("app/precos.py", "cambio"),
    # Guarda de preço (trava de não inventar, motor): distância não é dinheiro ("90 mil km",
    # "rodou 42 mil"); vale para qualquer ramo ("a 2 km da praia"). "placa 1234" e "quilômetros"
    # idem. Fica no motor de propósito.
    ("app/guarda_politica.py", "km"), ("app/guarda_politica.py", "kms"),
    ("app/guarda_politica.py", "quilometragem"), ("app/guarda_politica.py", "quilometros"),
    ("app/guarda_politica.py", "rodagem"),
    # Pedido de entrega (L8): "entregar a picape/o SUV" abre chamado. A guarda não recebe a loja;
    # o vocabulário do item deveria vir do ramo (pendência do SG1).
    ("app/guarda_politica.py", "picape"), ("app/guarda_politica.py", "suv"),
    # Leitura da foto do cliente: o prompt de leitura é de loja de carros (tipo CARRO); "km" e
    # "placa" são números que não são documento nem dinheiro. Destino: o ramo entregar o prompt
    # da leitura (quando houver um 2º ramo real que leia fotos).
    ("app/imagens.py", "km"), ("app/imagens.py", "placa"),
}


def _sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn").lower()


def _arquivos():
    for pasta in PASTAS_DO_MOTOR:
        yield from sorted((RAIZ / pasta).rglob("*.py"))


def _relativo(caminho: Path) -> str:
    return caminho.relative_to(RAIZ).as_posix()


def palavras_achadas() -> set:
    achadas = set()
    for caminho in _arquivos():
        texto = _sem_acento(caminho.read_text(encoding="utf-8"))
        for m in _PALAVRA.finditer(texto):
            achadas.add((_relativo(caminho), m.group(1)))
    return achadas


def test_motor_nao_importa_ramo_pelo_nome():
    ruins = []
    for caminho in _arquivos():
        fonte = caminho.read_text(encoding="utf-8")
        if "segmentos.veiculos" in fonte or "segmentos/veiculos" in fonte:
            ruins.append(f"{_relativo(caminho)}: cita segmentos.veiculos")
        for no in ast.walk(ast.parse(fonte)):
            if isinstance(no, ast.Import):
                ruins += [f"{_relativo(caminho)}: import {a.name}" for a in no.names
                          if a.name.startswith("segmentos.")]
            elif isinstance(no, ast.ImportFrom) and no.module:
                if no.module.startswith("segmentos.") or (
                        no.module == "segmentos" and any(a.name != "*" for a in no.names)):
                    ruins.append(f"{_relativo(caminho)}: from {no.module} import ...")
    assert not ruins, "O motor não pode importar um ramo pelo nome:\n" + "\n".join(ruins)


def test_nenhuma_palavra_de_carro_nova_no_motor():
    novas = sorted(palavras_achadas() - LEGADO)
    assert not novas, (
        "Palavra de carro no motor (app/, tools/). Leve o código para segmentos/veiculos/ "
        "(contrato: docs/pacote_de_ramo.md).\n" + "\n".join(f"    {n}," for n in novas))


def test_legado_so_diminui():
    saiu = sorted(LEGADO - palavras_achadas())
    assert not saiu, ("Estas palavras já saíram do motor (ótimo!). Apague-as do LEGADO:\n"
                      + "\n".join(f"    {n}," for n in saiu))


def test_a_catraca_pega_o_que_deve():
    assert _PALAVRA.search(_sem_acento("tem SUV com câmbio automático e 30 mil km?"))
    assert _PALAVRA.search(_sem_acento("Sedã ou hatch?"))
    assert not _PALAVRA.search(_sem_acento("quilombo, cambiante, placar, kmz"))
