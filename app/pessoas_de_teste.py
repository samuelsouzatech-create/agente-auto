"""
Pessoas de TESTE (fictícias) para entrar no painel do cliente: Dono Demo, Gerente Demo e
Vendedor Demo. Usado pelo script scripts/criar_usuarios_demo.py, pelo scripts/reiniciar_demo.py e
pelo botão "Reiniciar demo" do painel do operador (Maratona Fotos, F2).

- Só na loja de demonstração ou em loja fictícia SEM canal real ligado (WhatsApp, Telegram ou
  Instagram): senão, LojaComCanalReal e nada é criado.
- A senha é gerada aqui e devolvida UMA vez para quem chamou mostrar (terminal ou tela).
  Nunca é gravada em arquivo nem no log; o banco guarda só o hash.
- Quem já existe (mesmo e-mail) é pulado: rodar de novo não troca a senha de ninguém.
"""
from __future__ import annotations

import secrets

PAPEIS = (("dono", "Dono Demo"), ("gestor", "Gerente Demo"), ("vendedor", "Vendedor Demo"))
CANAIS_REAIS = ("whatsapp", "telegram", "instagram")


class LojaComCanalReal(ValueError):
    """Pessoas de teste só entram na demo ou em loja fictícia sem canal real ligado."""


def canais_reais_ligados(loja_id: int) -> list[str]:
    from app.canais import listar_canais
    return sorted({c["tipo"] for c in listar_canais(loja_id) if c["tipo"] in CANAIS_REAIS and c["ativo"]})


def gerar_senha() -> str:
    """Três pedaços aleatórios, fácil de digitar no celular, longe do mínimo de 10 letras."""
    return "-".join(secrets.token_urlsafe(6).replace("-", "x").replace("_", "y") for _ in range(3))


def email_de(papel: str, loja_id: int) -> str:
    return f"{papel}.loja{loja_id}@demo.exemplo"


def criar_pessoas_de_teste(loja_id: int, ator: str) -> list[dict]:
    """Cria (ou pula) as três pessoas. Devolve [{papel, nome, email, senha | None}].
    ator: o nome de quem age (fica no Registro como operador)."""
    from app.ator import como
    from app.autenticacao import criar_usuario_com_login
    from banco import conectar

    ligados = canais_reais_ligados(loja_id)
    if ligados:
        raise LojaComCanalReal(f"a loja {loja_id} tem canal real ligado ({', '.join(ligados)})")
    saida = []
    with como(ator, "operador", "painel"):
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
