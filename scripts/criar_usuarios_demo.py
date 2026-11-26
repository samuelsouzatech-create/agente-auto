r"""
Cria as pessoas de TESTE (fictícias) para entrar no painel do cliente da loja de demonstração:
um dono, um gerente e um vendedor. Para quem testa a tela (leo-painel-web) com a API local.

    .venv-teste\Scripts\python scripts\criar_usuarios_demo.py
    .venv-teste\Scripts\python scripts\criar_usuarios_demo.py --loja 2   (outra loja fictícia)

- Sem --loja, usa a loja de demonstração ("Recife Seminovos Demo"; crie antes com
  scripts\criar_loja_demo.py). Com --loja, a loja precisa existir e NÃO pode ter canal real
  ligado (WhatsApp, Telegram ou Instagram): nesse caso nada é criado.
- A senha é gerada aqui e aparece SÓ neste terminal. Não é gravada em arquivo nenhum.
- Quem já existe (mesmo e-mail) é pulado: rodar de novo não troca a senha de ninguém.
  Para trocar, use scripts\login.py senha <número>.
- Quem age é o operador "Script criar_usuarios_demo" (fica no Registro).
"""
from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

# A regra mora em app/pessoas_de_teste.py (o painel do operador usa a mesma).
from app.pessoas_de_teste import (CANAIS_REAIS, PAPEIS, LojaComCanalReal, canais_reais_ligados,  # noqa: E402,F401
                                  criar_pessoas_de_teste, email_de, gerar_senha)

ATOR = "Script criar_usuarios_demo"


def criar_usuarios(loja_id: int) -> list[dict]:
    """Cria (ou pula) as três pessoas. Devolve [{papel, nome, email, senha | None}]."""
    return criar_pessoas_de_teste(loja_id, ATOR)


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
    try:
        feitos = criar_usuarios(loja_id)
    except LojaComCanalReal:
        print("Esta loja tem WhatsApp, Telegram ou Instagram ligado. Pessoas de teste só na loja de "
              "demonstração ou numa loja fictícia sem canal real. Nada foi criado.")
        return 1
    for p in feitos:
        situacao = f"senha: {p['senha']}" if p["senha"] else "já existia (senha não mudou)"
        print(f"  {p['nome']:<14} {p['email']:<32} {situacao}")
    print("Anote as senhas agora: elas não ficam gravadas em lugar nenhum.")
    return 0


if __name__ == "__main__":
    import banco as _banco                  # SE3: este programa vê todas as lojas (modo sistema)
    _banco.declarar_sistema("scripts/criar_usuarios_demo.py")
    raise SystemExit(main())
