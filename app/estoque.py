"""
CRUD de estoque (Fase 3 - Bloco 5; caminho único de venda no P2 do Plano Mestre).

Funções de leitura e escrita na tabela 'estoque'. Mantém a lógica de banco
separada da tela, igual app/handoff.py e app/mensagens.py.

Regra do P2: nenhuma função deste arquivo coloca um carro como 'vendido'.
A venda só acontece por app/vendas.py:registrar_venda, que grava a venda,
o resultado, a baixa no estoque e o pós-venda. Um carro já vendido também
não volta para a oferta por aqui.

Observação: no documento (seção 7), este CRUD é a "fonte da verdade" só no
cenário C (loja sem CRM/API). Quando a loja tem sistema, o estoque vem de lá.
"""
from banco import conectar


# Opções fixas de câmbio e situação, pra o painel usar em selects.
OPCOES_CAMBIO = ["Automático", "Manual"]
# 'vendido' não entra aqui de propósito: só registrar_venda grava 'vendido'.
OPCOES_STATUS = ["disponivel", "reservado", "indisponivel"]
VENDIDO = "vendido"

MENSAGEM_USE_VENDA = ("Para vender um carro, use \"Registrar venda\" na conversa do cliente. "
                      "Assim a venda, o resultado e o pós-venda ficam registrados juntos.")
MENSAGEM_JA_VENDIDO = "Este carro já foi vendido. A situação dele não muda por aqui."
MENSAGEM_STATUS_INVALIDO = "Situação inválida. Escolha Disponível, Reservado ou Indisponível."


class StatusInvalido(ValueError):
    """Situação que o estoque não aceita (ex.: 'vendido' fora do Registrar venda)."""


def _validar_status(status):
    if status == VENDIDO:
        raise StatusInvalido(MENSAGEM_USE_VENDA)
    if status not in OPCOES_STATUS:
        raise StatusInvalido(MENSAGEM_STATUS_INVALIDO)


def _status_atual(cursor, carro_id, loja_id):
    cursor.execute("SELECT status FROM estoque WHERE id = ? AND loja_id = ?", (carro_id, loja_id))
    linha = cursor.fetchone()
    return linha["status"] if linha else None


def listar_estoque(loja_id, incluir_vendidos=True):
    """Lista os carros do estoque. Por padrão traz todos; se
    incluir_vendidos=False, traz só os que não estão vendidos."""
    conexao = conectar()
    cursor = conexao.cursor()
    if incluir_vendidos:
        cursor.execute(
            "SELECT * FROM estoque WHERE loja_id = ? ORDER BY id ASC",
            (loja_id,),
        )
    else:
        cursor.execute(
            "SELECT * FROM estoque WHERE loja_id = ? AND status != 'vendido' "
            "ORDER BY id ASC",
            (loja_id,),
        )
    linhas = cursor.fetchall()
    conexao.close()
    return [dict(linha) for linha in linhas]


def buscar_carro(carro_id, loja_id):
    """Retorna um carro pelo id, ou None se não existir."""
    conexao = conectar()
    cursor = conexao.cursor()
    cursor.execute(
        "SELECT * FROM estoque WHERE id = ? AND loja_id = ?",
        (carro_id, loja_id),
    )
    linha = cursor.fetchone()
    conexao.close()
    return dict(linha) if linha else None


def adicionar_carro(marca, modelo, ano, km, cor, cambio, preco,
                    status="disponivel", fotos="", *, loja_id):
    """Cadastra um carro novo. Retorna o id gerado.
    Carro novo nunca nasce 'vendido' (regra do P2)."""
    _validar_status(status)
    conexao = conectar()
    cursor = conexao.cursor()
    cursor.execute(
        """
        INSERT INTO estoque
            (loja_id, marca, modelo, ano, km, cor, cambio, preco, status, fotos)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (loja_id, marca, modelo, ano, km, cor, cambio, preco, status, fotos),
    )
    novo_id = cursor.lastrowid
    conexao.commit()
    conexao.close()
    return novo_id


def atualizar_carro(carro_id, marca, modelo, ano, km, cor, cambio, preco,
                    status, fotos="", *, loja_id):
    """Atualiza os campos editáveis de um carro existente.
    Carro já vendido: os dados (preço, fotos...) podem ser corrigidos, mas a
    situação continua 'vendido'. Nenhum carro vira 'vendido' por aqui."""
    conexao = conectar()
    try:
        cursor = conexao.cursor()
        atual = _status_atual(cursor, carro_id, loja_id)
        if atual is None:
            return "Carro não encontrado nesta loja."
        if atual == VENDIDO:
            if status != VENDIDO:
                raise StatusInvalido(MENSAGEM_JA_VENDIDO)
        else:
            _validar_status(status)
        cursor.execute(
            """
            UPDATE estoque
            SET marca = ?, modelo = ?, ano = ?, km = ?, cor = ?,
                cambio = ?, preco = ?, status = ?, fotos = ?
            WHERE id = ? AND loja_id = ?
            """,
            (marca, modelo, ano, km, cor, cambio, preco, status, fotos,
             carro_id, loja_id),
        )
        conexao.commit()
    finally:
        conexao.close()
    return "Carro atualizado."


def marcar_status(carro_id, status, loja_id):
    """Muda só a situação: disponivel, reservado ou indisponivel.
    Qualquer situação diferente de 'disponivel' tira o carro da oferta do Léo
    na hora (as ferramentas só oferecem 'disponivel').
    'vendido' é recusado: use registrar_venda (app/vendas.py)."""
    _validar_status(status)
    conexao = conectar()
    try:
        cursor = conexao.cursor()
        atual = _status_atual(cursor, carro_id, loja_id)
        if atual is None:
            return "Carro não encontrado nesta loja."
        if atual == VENDIDO:
            raise StatusInvalido(MENSAGEM_JA_VENDIDO)
        cursor.execute(
            "UPDATE estoque SET status = ? WHERE id = ? AND loja_id = ?",
            (status, carro_id, loja_id),
        )
        conexao.commit()
    finally:
        conexao.close()
    return f"Status alterado para '{status}'."
