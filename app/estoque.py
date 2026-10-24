"""
CRUD de estoque (Fase 3 - Bloco 5).

Funções de leitura e escrita na tabela 'estoque'. Usadas pelo painel do
vendedor (painel_estoque.py). Mantém a lógica de banco separada da tela,
igual app/handoff.py e app/mensagens.py.

Observação: no documento (seção 7), este CRUD é a "fonte da verdade" só no
cenário C (loja sem CRM/API). Quando a loja tem sistema, o estoque vem de lá.
"""
from banco import conectar


# Opções fixas de câmbio e status, pra o painel usar em selects.
OPCOES_CAMBIO = ["Automático", "Manual"]
OPCOES_STATUS = ["disponivel", "reservado", "vendido"]


def listar_estoque(loja_id=1, incluir_vendidos=True):
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


def buscar_carro(carro_id, loja_id=1):
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
                    status="disponivel", fotos="", loja_id=1):
    """Cadastra um carro novo. Retorna o id gerado."""
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
                    status, fotos="", loja_id=1):
    """Atualiza todos os campos editáveis de um carro existente."""
    conexao = conectar()
    cursor = conexao.cursor()
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
    conexao.close()
    return "Carro atualizado."


def marcar_status(carro_id, status, loja_id=1):
    """Atalho pra mudar só o status (ex.: marcar como 'vendido').
    Tira o carro da oferta na hora, como manda a seção 7 do documento."""
    conexao = conectar()
    cursor = conexao.cursor()
    cursor.execute(
        "UPDATE estoque SET status = ? WHERE id = ? AND loja_id = ?",
        (status, carro_id, loja_id),
    )
    conexao.commit()
    conexao.close()
    return f"Status alterado para '{status}'."
