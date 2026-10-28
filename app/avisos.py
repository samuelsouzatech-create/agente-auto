"""
Bot único de avisos no Telegram (Etapa 1, Bloco 7B - item 1.10).

Fala só com a equipe (vendedor, gestor) e com o operador, nunca com lead.
Cada aviso tem uma etiqueta (tipo + referência + destino) na tabela avisos:
o mesmo aviso nunca chega duas vezes para a mesma pessoa. Se o envio falhar,
tenta de novo nos próximos ciclos, até MAX_TENTATIVAS.
"""
from __future__ import annotations

import httpx

from app import config
from banco import conectar

MAX_TENTATIVAS = 3
LIMITE_TEXTO = 4000
SEM_DESTINO = "-"


def chat_do_operador() -> str:
    return (config.TELEGRAM_AVISOS_OPERADOR_CHAT_ID or "").strip()


def _enviar(chat_id: str, texto: str) -> tuple[bool, str | None]:
    """Manda uma mensagem pelo bot de avisos. Devolve (deu_certo, erro).
    O erro NUNCA leva a URL: ela contém o token."""
    token = (config.TELEGRAM_AVISOS_TOKEN or "").strip()
    if not token:
        return False, "TELEGRAM_AVISOS_TOKEN vazio no .env"
    try:
        resposta = httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": texto[:LIMITE_TEXTO],
                  "disable_web_page_preview": True},
            timeout=10,
        )
        dados = resposta.json()
    except Exception as erro:
        return False, f"falha de rede ({type(erro).__name__})"
    if dados.get("ok"):
        return True, None
    return False, f"{dados.get('error_code')} {dados.get('description')}"


def avisar_uma_vez(loja_id: int | None, tipo: str, referencia: str,
                   destinos, texto: str) -> dict:
    """Manda o aviso para cada destino que ainda não recebeu.

    Devolve {"enviados", "falhas", "pulados", "concluido"}. concluido=False
    quando algum destino falhou e ainda tem tentativa sobrando (o relógio
    chama de novo no próximo ciclo)."""
    resultado = {"enviados": 0, "falhas": 0, "pulados": 0, "concluido": True}
    chats = list(dict.fromkeys(
        str(d).strip() for d in (destinos or []) if str(d or "").strip()))

    conexao = conectar()
    try:
        if not chats:
            cursor = conexao.execute(
                "INSERT OR IGNORE INTO avisos (loja_id, tipo, referencia, destino, texto, status, erro) "
                "VALUES (?, ?, ?, ?, ?, 'sem_destino', 'ninguém com Telegram cadastrado')",
                (loja_id, tipo, referencia, SEM_DESTINO, texto),
            )
            conexao.commit()
            if cursor.rowcount:
                print(f"[Avisos] Loja {loja_id}: ninguém para receber '{tipo}' ({referencia}). "
                      "Cadastre o Telegram na tela Usuários.")
            return resultado

        for chat in chats:
            linha = conexao.execute(
                "SELECT status, tentativas FROM avisos WHERE tipo = ? AND referencia = ? AND destino = ?",
                (tipo, referencia, chat),
            ).fetchone()
            if linha and (linha["status"] == "enviado" or linha["tentativas"] >= MAX_TENTATIVAS):
                resultado["pulados"] += 1
                continue

            ok, erro = _enviar(chat, texto)
            conexao.execute(
                """INSERT INTO avisos (loja_id, tipo, referencia, destino, texto, status, tentativas, erro)
                   VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                   ON CONFLICT (tipo, referencia, destino) DO UPDATE SET
                       status = excluded.status, erro = excluded.erro,
                       tentativas = avisos.tentativas + 1,
                       atualizado_em = CURRENT_TIMESTAMP""",
                (loja_id, tipo, referencia, chat, texto, "enviado" if ok else "falhou", erro),
            )
            conexao.commit()

            if ok:
                resultado["enviados"] += 1
                continue
            resultado["falhas"] += 1
            tentativas = (linha["tentativas"] if linha else 0) + 1
            if tentativas < MAX_TENTATIVAS:
                resultado["concluido"] = False
            print(f"[Avisos] Falha ao avisar {chat} ({tipo}, tentativa "
                  f"{tentativas}/{MAX_TENTATIVAS}): {erro}")
    finally:
        conexao.close()
    return resultado
