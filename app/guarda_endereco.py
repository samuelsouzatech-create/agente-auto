"""
Guarda do endereço da loja (RG1, Maratona 5).

Achado na bancada da Maratona 5 (rodada_2026-11-27_162835, roteiro foto_meu_carro_parece_anuncio):
o Léo escreveu "Av. Domingos Ferreira, 1000, Boa Vista" e o cadastro diz "Av. Domingos Ferreira,
1000, Boa Viagem". Rua e número certos, bairro inventado.

Regra (código, não prompt): quando a resposta cita a RUA do cadastro, o trecho do endereço (rua,
número e os nomes que vêm logo depois, separados por vírgula ou traço) é conferido com o cadastro.
Se tem número diferente ou um nome de lugar que não está no cadastro (bairro, cidade), o trecho vira
o endereço do cadastro, exatamente como está. Endereço certo (mesmo escrito de outro jeito, ex.: "em
Boa Viagem", "nº 1000") não muda nada. Neutro ao segmento: só usa o endereço e a cidade da loja.
"""
from __future__ import annotations

import re
import unicodedata

_PREFIXO = r"(?:(?:Av\.?|Avenida|Rua|R\.|Travessa|Tv\.?|Estrada|Est\.?|Rodovia|Rod\.?|Alameda|Al\.|Praça|Pça\.?)\s+)?"
_NUMERO = r"(?:\s*,?\s*(?:n[º°o]\.?\s*|número\s+)?\d+[A-Za-z]?)?"
_NOME_DE_LUGAR = (r"(?:\s*(?:,|-|–)\s*(?:(?:em|no|na|bairro|cidade\s+de)\s+)?"
                  r"[A-ZÁÉÍÓÚÂÊÔÃÕÇ][\wÀ-ú']*(?:\s+(?:de|da|do|das|dos|e)?\s*[A-ZÁÉÍÓÚÂÊÔÃÕÇ][\wÀ-ú']*){0,3})")
_TIRAR_PREFIXO = re.compile(r"^" + _PREFIXO, re.I)
_PALAVRAS_DE_LIGACAO = re.compile(r"^(?:em|no|na|bairro|cidade\s+de)\s+", re.I)


def _sem_acento(texto: str) -> str:
    t = unicodedata.normalize("NFD", str(texto or "")).lower()
    return " ".join("".join(c for c in t if unicodedata.category(c) != "Mn").split())


_VARIANTES = {"a": "aáàâãä", "e": "eéèêë", "i": "iíìîï", "o": "oóòôõö", "u": "uúùûü", "c": "cç"}


def _padrao_flexivel(texto: str) -> str:
    """Regex do texto que aceita com ou sem acento e espaço repetido."""
    partes = []
    for c in texto:
        base = _sem_acento(c)
        if c.isspace():
            partes.append(r"\s+")
        elif base in _VARIANTES:
            v = _VARIANTES[base]
            partes.append(f"[{v}{v.upper()}]")
        else:
            partes.append(re.escape(c))
    return "".join(partes)


def _partes_do_cadastro(endereco: str) -> tuple[str, str | None, list[str]]:
    partes = [p.strip() for p in re.split(r"[,–-]", endereco) if p.strip()]
    rua = partes[0] if partes else ""
    numero = next((re.sub(r"\D", "", p) for p in partes[1:] if re.fullmatch(r"(?:n[º°o]\.?\s*)?\d+[A-Za-z]?", p, re.I)), None)
    lugares = [p for p in partes[1:] if not re.search(r"\d", p)]
    return rua, numero, lugares


def corrigir_endereco(resposta: str, endereco: str | None, cidade: str | None = None) -> tuple[str, bool]:
    """(resposta, trocou). Troca o trecho do endereço errado pelo endereço do cadastro."""
    endereco = " ".join(str(endereco or "").split())
    if not resposta or not endereco:
        return resposta, False
    rua, numero, lugares = _partes_do_cadastro(endereco)
    nucleo = _TIRAR_PREFIXO.sub("", rua).strip()
    if len(nucleo) < 4:
        return resposta, False
    permitidos = {_sem_acento(l) for l in lugares}
    if cidade:
        permitidos.add(_sem_acento(cidade))
    padrao = re.compile(_PREFIXO + _padrao_flexivel(nucleo) + _NUMERO + _NOME_DE_LUGAR + "{0,3}", re.I)
    trocou = False

    def _conferir(m: re.Match) -> str:
        nonlocal trocou
        trecho = m.group(0)
        depois_da_rua = trecho[len(re.match(_PREFIXO + _padrao_flexivel(nucleo), trecho, re.I).group(0)):]
        numeros = re.findall(r"\d+", depois_da_rua)
        errado = bool(numero and numeros and numeros[0] != numero)
        for pedaco in re.split(r"[,–-]", depois_da_rua):
            pedaco = _PALAVRAS_DE_LIGACAO.sub("", pedaco.strip())
            if not pedaco or re.search(r"\d", pedaco):
                continue
            if _sem_acento(pedaco) not in permitidos:
                errado = True
        if not errado:
            return trecho
        trocou = True
        return endereco

    novo = padrao.sub(_conferir, resposta)
    return novo, trocou
