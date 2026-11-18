"""
L5 (Fase Cérebro): foto que o cliente manda.

Uma chamada de IA (visão) lê a imagem e devolve só um TIPO e uma DESCRIÇÃO curta.
O arquivo da imagem nunca é guardado; o resto do turno trabalha só com o texto.

- carro:     modelo aparente, cor e estado visível (nunca valor)
- anuncio:   marca, modelo e ano do anúncio (preço só o da ferramenta de estoque)
- documento: CNH, RG, documento do carro, comprovante, boleto: descrição VAZIA,
             nenhum dado transcrito nem guardado
- outro:     o que aparece, sem descrever pessoas

O código limpa a descrição de novo (valor em R$, "mil", telefone, sequência de
números de documento): o que a IA deixar passar não chega ao Léo nem ao banco.
Este arquivo é o único que conhece o SDK de visão (como app/api/receber_audio.py).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from app.custos import Uso

MAX_DESCRICAO = 200
CARRO, ANUNCIO, DOCUMENTO, OUTRO = "carro", "anuncio", "documento", "outro"
TIPOS = (CARRO, ANUNCIO, DOCUMENTO, OUTRO)

PROMPT_LEITURA = """Você recebe uma imagem que um cliente mandou para uma loja de carros.
Responda SÓ com JSON: {"tipo": "carro" | "anuncio" | "documento" | "outro", "descricao": "...", "tem_pessoa": true | false}
- carro: foto de um carro. descricao: modelo aparente, cor e estado visível (riscos, amassados, pneus). Não estime valor.
- anuncio: print ou foto de anúncio de carro. descricao: marca, modelo e ano escritos no anúncio. Não copie preço, telefone nem nome.
- documento: CNH, RG, CPF, documento do carro (CRLV), comprovante, boleto, contrato, cartão. descricao: "" (vazia). Não transcreva nenhum dado.
- outro: qualquer outra coisa. descricao curta do que aparece.
Nunca descreva pessoas (rosto, roupa, aparência). tem_pessoa: true se aparece alguém.
Descrição com no máximo 200 letras, em português do Brasil."""


@dataclass
class LeituraImagem:
    ok: bool
    tipo: str = OUTRO
    descricao: str = ""
    tem_pessoa: bool = False
    uso: Uso = field(default_factory=Uso)


# Sequência com cara de número de documento (CPF, RG, CNH, placa de boleto...).
_NUMERO_DE_DOCUMENTO = re.compile(r"\d{3}[.\s]?\d{3}[.\s]?\d{3}[-\s]?\d{2}|\d[\d.\-/\s]{6,}\d")
_DINHEIRO = re.compile(r"r\$\s*[\d.,]+(\s*mil)?|\b\d+([.,]\d+)?\s*(mil|k)\b", re.IGNORECASE)
_TELEFONE = re.compile(r"\(?\d{2}\)?\s*9?\d{4}[-\s]?\d{4}")


def limpar_descricao(texto: str) -> str:
    """Tira valor, telefone e número de documento; corta em 200 letras."""
    texto = " ".join(str(texto or "").split())
    texto = _DINHEIRO.sub("", texto)
    texto = _TELEFONE.sub("", texto)
    texto = _NUMERO_DE_DOCUMENTO.sub("", texto)
    texto = " ".join(texto.split()).strip(" ,;-")
    return texto[:MAX_DESCRICAO].rstrip()


def interpretar(resposta_ia: str, uso: Uso | None = None) -> LeituraImagem:
    """JSON da IA -> LeituraImagem já limpa. Resposta que não dá para ler = falha."""
    uso = uso or Uso()
    try:
        texto = str(resposta_ia or "").strip()
        texto = texto[texto.index("{"): texto.rindex("}") + 1]
        dados = json.loads(texto)
        tipo = str(dados.get("tipo") or "").strip().lower()
    except (ValueError, AttributeError, TypeError):
        return LeituraImagem(ok=False, uso=uso)
    if tipo not in TIPOS:
        return LeituraImagem(ok=False, uso=uso)
    bruta = str(dados.get("descricao") or "")
    if tipo != DOCUMENTO and _NUMERO_DE_DOCUMENTO.search(bruta) and tipo != ANUNCIO:
        tipo = DOCUMENTO          # descrição com número de documento: trata como documento
    descricao = "" if tipo == DOCUMENTO else limpar_descricao(bruta)
    return LeituraImagem(ok=True, tipo=tipo, descricao=descricao,
                         tem_pessoa=bool(dados.get("tem_pessoa")), uso=uso)


def ler_imagem(imagem: bytes, mime: str = "image/jpeg") -> LeituraImagem:
    """Lê a imagem com a IA. Nunca lança exceção: falhou = LeituraImagem(ok=False)."""
    try:
        from google import genai

        from app.api.receber_audio import uso_da_resposta
        from app.config import GOOGLE_API_KEY, MODELO_LLM

        cliente = genai.Client(api_key=GOOGLE_API_KEY)
        resposta = cliente.models.generate_content(
            model=MODELO_LLM,
            contents=[PROMPT_LEITURA, genai.types.Part.from_bytes(data=imagem, mime_type=mime)],
            config=genai.types.GenerateContentConfig(response_mime_type="application/json"),
        )
        return interpretar(resposta.text, uso_da_resposta(resposta))
    except Exception as erro:
        print(f"[Imagem] Erro ao ler a imagem na IA: {type(erro).__name__}")
        return LeituraImagem(ok=False)


def texto_para_o_leo(leitura: LeituraImagem, legenda: str = "") -> str:
    """O que o Léo recebe (e o que fica gravado) no lugar da foto."""
    if leitura.tipo == CARRO:
        texto = f"[Foto do cliente: carro. O que aparece: {leitura.descricao or 'sem detalhes'}]"
    elif leitura.tipo == ANUNCIO:
        texto = f"[Foto do cliente: print de anúncio. Carro do anúncio: {leitura.descricao or 'não deu para ler'}]"
    else:
        texto = f"[Foto do cliente: {leitura.descricao or 'imagem sem detalhes'}]"
    if leitura.tem_pessoa:
        texto += " [Tem pessoa na foto: não comente.]"
    legenda = " ".join(str(legenda or "").split())
    return f"{texto}\n{legenda}" if legenda else f"{texto}\n[Sem legenda]"
