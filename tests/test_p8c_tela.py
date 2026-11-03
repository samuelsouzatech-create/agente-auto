"""P8c: a tela mostra 'Gerente' no lugar de 'gestor' e aceita 'dono'."""
import py_compile
from pathlib import Path

from app.usuarios import PAPEIS, criar_usuario, rotulo_papel

RAIZ = Path(__file__).resolve().parent.parent


def test_rotulos_da_tela():
    assert PAPEIS == ("vendedor", "gestor", "dono")
    assert [rotulo_papel(p) for p in PAPEIS] == ["Vendedor", "Gerente", "Dono"]


def test_dono_pode_ser_cadastrado_na_loja():
    assert criar_usuario(1, "Seu Zé", "dono") > 0


def test_arquivos_compilam():
    for arquivo in ("paginas/usuarios.py", "scripts/login.py"):
        py_compile.compile(str(RAIZ / arquivo), doraise=True)
