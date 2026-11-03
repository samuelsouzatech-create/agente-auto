"""Acessos (login) pelo terminal (P8c), até a tela do operador (S4b) e a API (C2).

Na raiz do projeto:
  python scripts/login.py listar
  python scripts/login.py criar 1 "Ana Souza" gestor ana@loja.com
  python scripts/login.py criar - "Samuel" operador samuel@exemplo.com
  python scripts/login.py email 3 ana@loja.com
  python scripts/login.py senha 3
  python scripts/login.py testar ana@loja.com

Papéis: vendedor, gestor (Gerente), dono, operador, suporte. Use "-" no lugar
da loja para operador e suporte. A senha é pedida escondida (não aparece na
tela nem fica no histórico do terminal). Quem age é o OPERADOR_NOME do .env.
"""
import getpass
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.ator import como
from app.autenticacao import (
    DadosInvalidos, autenticar, bloqueado_por_tentativas, criar_usuario_com_login,
    definir_email, definir_senha, listar_logins,
)
from app.identidade import SemNomeOperador, nome_do_operador


def _pedir_senha() -> str:
    primeira = getpass.getpass("Nova senha (não aparece enquanto digita): ")
    segunda = getpass.getpass("Repita a senha: ")
    if primeira != segunda:
        raise DadosInvalidos("As duas senhas não são iguais.")
    return primeira


def _listar() -> None:
    for u in listar_logins():
        loja = f"loja {u['loja_id']}" if u["loja_id"] else "todas as lojas"
        email = u["email"] or "sem e-mail"
        senha = "com senha" if u["tem_senha"] else "sem senha"
        ativo = "" if u["ativo"] else " (desativado)"
        ultimo = f", último acesso {u['ultimo_acesso']} (UTC)" if u["ultimo_acesso"] else ""
        print(f"usuário {u['id']}: {u['nome']} · {u['rotulo_papel']} · {loja} · "
              f"{email} · {senha}{ativo}{ultimo}")


def _testar(email: str) -> int:
    resultado = autenticar(email, getpass.getpass("Senha: "))
    if resultado:
        loja = f"loja {resultado['loja_id']}" if resultado["loja_id"] else "todas as lojas"
        print(f"Entrou: {resultado['nome']} ({resultado['rotulo_papel']}, {loja}).")
        return 0
    if bloqueado_por_tentativas(email):
        print("Recusado: muitas tentativas erradas. Espere 15 minutos.")
    else:
        print("Recusado: e-mail ou senha errados.")
    return 1


def _executar(argumentos) -> int:
    comando = argumentos[0] if argumentos else ""
    if comando == "criar" and len(argumentos) == 5:
        loja = None if argumentos[1] == "-" else int(argumentos[1])
        uid = criar_usuario_com_login(loja, argumentos[2], argumentos[3], argumentos[4],
                                      _pedir_senha())
        print(f"Acesso criado: usuário {uid}.")
        return 0
    if comando == "email" and len(argumentos) == 3:
        mudou = definir_email(int(argumentos[1]), argumentos[2])
        print("E-mail gravado." if mudou else "Esse já era o e-mail. Nada mudou.")
        return 0
    if comando == "senha" and len(argumentos) == 2:
        definir_senha(int(argumentos[1]), _pedir_senha())
        print("Senha gravada.")
        return 0
    print(__doc__)
    return 1


def main(argumentos) -> int:
    if argumentos == ["listar"]:
        _listar()
        return 0
    if len(argumentos) == 2 and argumentos[0] == "testar":
        return _testar(argumentos[1])
    try:
        operador = nome_do_operador()
    except SemNomeOperador as erro:
        print(erro)
        return 1
    try:
        with como(operador, "operador", "painel"):
            return _executar(argumentos)
    except Exception as erro:
        print(f"Erro: {erro}")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
