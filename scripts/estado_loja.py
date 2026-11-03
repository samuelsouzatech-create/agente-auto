"""Estado da loja e números de teste (P7b), até a tela do operador (S4b).

Na raiz do projeto:
  python scripts/estado_loja.py listar
  python scripts/estado_loja.py numero 2 telegram 123456789 Samuel
  python scripts/estado_loja.py numero 2 whatsapp 81999990000 Samuel
  python scripts/estado_loja.py desativar 2 5
  python scripts/estado_loja.py no-ar 2 --sim

Quem age é o OPERADOR_NOME do .env (aparece no Registro).
Colocar no ar não tem volta por aqui: por isso pede --sim no final.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.ator import como
from app.estado_loja import (
    cadastrar_numero_de_teste, colocar_no_ar, desativar_numero_de_teste,
    listar_numeros_de_teste, situacao_da_loja,
)
from app.identidade import SemNomeOperador, nome_do_operador
from app.lojas_admin import listar_lojas


def _listar() -> None:
    for loja in listar_lojas():
        s = situacao_da_loja(loja["id"])
        desde = f" desde {s['no_ar_em']} (UTC)" if s["no_ar_em"] else ""
        print(f"loja {loja['id']} ({loja['nome']}): {s['rotulo']}{desde}")
        for n in listar_numeros_de_teste(loja["id"]):
            print(f"    número de teste {n['id']}: {n['tipo_de_canal']} {n['id_externo']} "
                  f"{n['nome'] or ''}".rstrip())


def _executar(argumentos) -> int:
    comando = argumentos[0] if argumentos else ""
    if comando == "numero" and len(argumentos) >= 4:
        loja_id = int(argumentos[1])
        nome = " ".join(argumentos[4:])
        nid = cadastrar_numero_de_teste(loja_id, argumentos[2], argumentos[3], nome)
        print(f"Número de teste {nid} ativo na loja {loja_id}.")
        return 0
    if comando == "desativar" and len(argumentos) == 3:
        if desativar_numero_de_teste(int(argumentos[1]), int(argumentos[2])):
            print("Número de teste desativado.")
        else:
            print("Nada mudou: esse número não existe nesta loja ou já estava desativado.")
        return 0
    if comando == "no-ar" and len(argumentos) == 3 and argumentos[2] == "--sim":
        loja_id = int(argumentos[1])
        if colocar_no_ar(loja_id):
            print(f"Loja {loja_id} NO AR: agora atende qualquer cliente.")
        else:
            print(f"Loja {loja_id} já estava no ar. Nada mudou.")
        return 0
    if comando == "no-ar" and len(argumentos) == 2:
        print("Para colocar no ar, repita o comando com --sim no final.")
        return 1
    print(__doc__)
    return 1


def main(argumentos) -> int:
    if argumentos == ["listar"]:
        _listar()
        return 0
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
