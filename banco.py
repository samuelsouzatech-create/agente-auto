import sqlite3

CAMINHO_BANCO = "loja.db"


def conectar():
    """Abre uma conexão com o banco. row_factory deixa a gente
    acessar as colunas pelo nome (ex: carro['modelo']) em vez de por número."""
    conexao = sqlite3.connect(CAMINHO_BANCO)
    conexao.row_factory = sqlite3.Row
    return conexao


def criar_tabelas():
    """Cria as tabelas se elas ainda não existirem."""
    conexao = conectar()
    cursor = conexao.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS estoque (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            loja_id INTEGER NOT NULL DEFAULT 1,
            marca TEXT NOT NULL,
            modelo TEXT NOT NULL,
            ano INTEGER NOT NULL,
            km INTEGER NOT NULL,
            cor TEXT NOT NULL,
            cambio TEXT NOT NULL,
            preco REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'disponivel'
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id TEXT UNIQUE,
            loja_id INTEGER NOT NULL DEFAULT 1,
            nome TEXT,
            interesse TEXT,
            forma_pagamento TEXT,
            tem_troca TEXT,
            prazo TEXT,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trocas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id TEXT,
            loja_id INTEGER NOT NULL DEFAULT 1,
            modelo TEXT, ano INTEGER, km INTEGER, estado TEXT,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS agendamentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id TEXT,
            loja_id INTEGER NOT NULL DEFAULT 1,
            nome_cliente TEXT, tipo TEXT, data_hora TEXT,
            status TEXT DEFAULT 'agendado',
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS handoffs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id TEXT,
            loja_id INTEGER NOT NULL DEFAULT 1,
            motivo TEXT, resumo TEXT,
            estado TEXT DEFAULT 'aguardando_humano',
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conexao.commit()
    conexao.close()
    print("Tabelas criadas (ou já existiam).")


def popular_estoque_exemplo():
    """Insere alguns carros de exemplo, só se a tabela estiver vazia."""
    conexao = conectar()
    cursor = conexao.cursor()

    cursor.execute("SELECT COUNT(*) FROM estoque")
    total = cursor.fetchone()[0]

    if total > 0:
        print(f"Estoque já tem {total} carros. Nada a inserir.")
        conexao.close()
        return

    carros = [
        ("Honda", "Civic", 2019, 48000, "Branco", "Automático", 98000.00, "disponivel"),
        ("Fiat", "Doblò", 2016, 110000, "Prata", "Manual", 52000.00, "disponivel"),
        ("Toyota", "Corolla", 2021, 32000, "Preto", "Automático", 135000.00, "disponivel"),
        ("Volkswagen", "Gol", 2018, 65000, "Branco", "Manual", 42000.00, "disponivel"),
        ("Chevrolet", "Onix", 2020, 40000, "Vermelho", "Automático", 68000.00, "disponivel"),
        ("Hyundai", "HB20", 2019, 55000, "Prata", "Manual", 54000.00, "disponivel"),
        ("Honda", "Civic", 2017, 72000, "Preto", "Automático", 82000.00, "vendido"),
    ]

    cursor.executemany("""
        INSERT INTO estoque (marca, modelo, ano, km, cor, cambio, preco, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, carros)

    conexao.commit()
    conexao.close()
    print(f"Inseridos {len(carros)} carros de exemplo.")


if __name__ == "__main__":
    criar_tabelas()
    popular_estoque_exemplo()

