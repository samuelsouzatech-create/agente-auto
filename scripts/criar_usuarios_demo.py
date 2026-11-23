r"""
Cria as pessoas de TESTE (fictícias) para entrar no painel do cliente da loja de demonstração:
um dono, um gerente e um vendedor. Para quem testa a tela (leo-painel-web) com a API local.

    .venv-teste\Scripts\python scripts\criar_usuarios_demo.py
    .venv-teste\Scripts\python scripts\criar_usuarios_demo.py --loja 2   (outra loja fictícia)

- Sem --loja, usa a loja de demonstração ("Recife Seminovos Demo"; crie antes com
  scripts\criar_loja_demo.py). Com --loja, a loja precisa existir.
- A senha é gerada aqui e aparece SÓ neste terminal. Não é gravada em arquivo nenhum.
- Quem já existe (mesmo e-mail) é pulado: rodar de novo não troca a senha de ninguém.
  Para trocar, use scripts\login.py senha <número>.
- Quem age é o operador "Script criar_usuarios_demo" (fica no Registro).
"""
from __future__ import annotations

import secrets
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

PAPEIS = (("dono", "Dono Demo"), ("gestor", "Gerente Demo"), ("vendedor", "Vendedor Demo"))
ATOR = "Script criar_usuarios_demo"


def gerar_senha() -> str:
    """Três pedaços aleatórios, fácil de digitar no celular, longe do mínimo de 10 letras."""
    return "-".join(secrets.token_urlsafe(6).replace("-", "x").replace("_", "y") for _ in range(3))


def email_de(papel: str, loja_id: int) -> str:
    return f"{papel}.loja{loja_id}@demo.exemplo"


def criar_usuarios(loja_id: int) -> list[dict]:
    """Cria (ou pula) as três pessoas. Devolve [{papel, nome, email, senha | None}]."""
    from app.ator import como
    from app.autenticacao import criar_usuario_com_login
    from banco import conectar

    saida = []
    with como(ATOR, "operador", "painel"):
        for papel, nome in PAPEIS:
            email = email_de(papel, loja_id)
            conexao = conectar()
            try:
                existe = conexao.execute("SELECT 1 FROM usuarios WHERE email = ?", (email,)).fetchone()
            finally:
                conexao.close()
            if existe:
                saida.append({"papel": papel, "nome": nome, "email": email, "senha": None})
                continue
            senha = gerar_senha()
            criar_usuario_com_login(loja_id, nome, papel, email, senha)
            saida.append({"papel": papel, "nome": nome, "email": email, "senha": senha})
    return saida


def main(argv=None) -> int:
    import argparse
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(description="Cria dono, gerente e vendedor de teste.")
    parser.add_argument("--loja", type=int, help="número da loja (padrão: a loja de demonstração)")
    args = parser.parse_args(argv)

    import banco
    from app.demo import id_da_loja_demo
    from app.lojas import carregar_loja
    banco.criar_tabelas()
    loja_id = args.loja if args.loja is not None else id_da_loja_demo()
    if loja_id is None:
        print("Não achei a loja de demonstração. Rode antes: scripts\\criar_loja_demo.py")
        return 1
    try:
        loja = carregar_loja(loja_id)
    except Exception:
        print(f"A loja {loja_id} não existe.")
        return 1
    print(f"Loja {loja_id}: {loja.nome}")
    for p in criar_usuarios(loja_id):
        situacao = f"senha: {p['senha']}" if p["senha"] else "já existia (senha não mudou)"
        print(f"  {p['nome']:<14} {p['email']:<32} {situacao}")
    print("Anote as senhas agora: elas não ficam gravadas em lugar nenhum.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
