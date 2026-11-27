"""
Nome do perfil do WhatsApp (RG1, Maratona 5).

A Meta manda, junto da mensagem, o nome que a pessoa pôs no perfil do WhatsApp
(contacts[].profile.name). Antes o Léo ignorava; a ficha do cliente ficava sem nome até ele dizer, e
o pós-venda e a retomada começavam com "Oi!" sem nome.
Agora: se a ficha do cliente NESTA loja está sem nome, o nome do perfil entra. NUNCA sobrescreve um
nome que já está lá (dito pelo cliente, anotado pelo Léo ou pelo vendedor). Nome de perfil que não
parece nome (só emoji, número, sinais) não entra.
"""
from __future__ import annotations

import re

from app.chaves import exigir_loja
from banco import conectar

MAX_NOME = 60
_LETRA = re.compile(r"[A-Za-zÀ-ÿ]")


def limpar_nome_do_perfil(nome) -> str:
    from app.guarda_politica import sem_emoji
    texto = " ".join(sem_emoji(str(nome or "")).replace("~", " ").split()).strip(" .-_|")
    if len(_LETRA.findall(texto)) < 2 or re.search(r"\d{4,}", texto):
        return ""
    return texto[:MAX_NOME].strip()


def gravar_nome_do_perfil(loja_id, lead_id: str, nome) -> bool:
    """Grava o nome do perfil na ficha SÓ se ela está sem nome. True se gravou."""
    limpo = limpar_nome_do_perfil(nome)
    if not limpo:
        return False
    loja_id = exigir_loja(loja_id)
    conexao = conectar()
    try:
        cursor = conexao.execute(
            "INSERT INTO leads (lead_id, loja_id, nome) VALUES (?, ?, ?) "
            "ON CONFLICT (loja_id, lead_id) DO UPDATE SET nome = EXCLUDED.nome, atualizado_em = agora_texto() "
            "WHERE COALESCE(TRIM(leads.nome), '') = ''", (str(lead_id), loja_id, limpo))
        conexao.commit()
        return bool(cursor.rowcount)
    finally:
        conexao.close()
