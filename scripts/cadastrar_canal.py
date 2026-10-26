"""Liga um canal a uma loja (tabela canais).

Exemplos (na raiz do projeto):
  python scripts/cadastrar_canal.py listar
  python scripts/cadastrar_canal.py telegram auto 2        # bot do .env -> loja 2
  python scripts/cadastrar_canal.py whatsapp auto 1        # número do .env -> loja 1
  python scripts/cadastrar_canal.py whatsapp 1234567890 2  # phone_number_id -> loja 2
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.config import TELEGRAM_TOKEN, WHATSAPP_PHONE_NUMBER_ID
from app.canais import cadastrar_canal, listar_canais, id_bot_telegram

AUTOMATICOS = {
    "telegram": (lambda: id_bot_telegram(TELEGRAM_TOKEN), "TELEGRAM_TOKEN"),
    "whatsapp": (lambda: WHATSAPP_PHONE_NUMBER_ID or "", "WHATSAPP_PHONE_NUMBER_ID"),
}


def main(argumentos):
    if argumentos == ["listar"]:
        canais = listar_canais()
        if not canais:
            print("Nenhum canal cadastrado (modo de transição: tudo vai para a loja 1).")
        for c in canais:
            status = "ativo" if c["ativo"] else "desativado"
            print(f"loja {c['loja_id']}: {c['tipo']} {c['id_externo']} ({status})")
        return

    if len(argumentos) != 3:
        print(__doc__)
        return

    tipo, id_externo, loja_id = argumentos[0], argumentos[1], int(argumentos[2])
    token_ref = ""
    if id_externo == "auto":
        if tipo not in AUTOMATICOS:
            print(f"'auto' só funciona para: {', '.join(AUTOMATICOS)}.")
            return
        obter, variavel = AUTOMATICOS[tipo]
        id_externo, token_ref = obter(), variavel
        if not id_externo:
            print(f"Não achei {variavel} no .env.")
            return

    cadastrar_canal(loja_id, tipo, id_externo, token_ref)
    print(f"Canal {tipo} {id_externo} ligado à loja {loja_id}.")


if __name__ == "__main__":
    main(sys.argv[1:])
