import sqlite3
import unicodedata

CAMINHO_BANCO = "loja.db"


def _sem_acento(texto):
    """Remove acentos de um texto, para buscas que ignoram acentuação.
    Ex.: 'Doblò' -> 'Doblo', 'Civíc' -> 'Civic'. Usada dentro do SQLite."""
    if texto is None:
        return None
    normalizado = unicodedata.normalize("NFD", str(texto))
    return "".join(c for c in normalizado if unicodedata.category(c) != "Mn")


def conectar():
    """Abre uma conexão com o banco. row_factory deixa a gente
    acessar as colunas pelo nome (ex: carro['modelo']) em vez de por número.
    Também registra a função sem_acento para buscas que ignoram acentuação."""
    conexao = sqlite3.connect(CAMINHO_BANCO)
    conexao.row_factory = sqlite3.Row
    conexao.create_function("sem_acento", 1, _sem_acento)
    return conexao


def criar_tabelas():
    """Cria as tabelas originais (se não existirem) e aplica as migrações."""
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
            status TEXT NOT NULL DEFAULT 'disponivel',
            fotos TEXT DEFAULT ''
        )
    """)

    # Lead é único POR LOJA: o mesmo telefone pode ser lead de duas lojas.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id TEXT NOT NULL,
            loja_id INTEGER NOT NULL DEFAULT 1,
            nome TEXT,
            interesse TEXT,
            forma_pagamento TEXT,
            tem_troca TEXT,
            prazo TEXT,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (loja_id, lead_id)
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
            vendedor TEXT,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            avisado_em TIMESTAMP,
            assumido_em TIMESTAMP,
            encerrado_em TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS mensagens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id TEXT NOT NULL,
            loja_id INTEGER NOT NULL DEFAULT 1,
            canal TEXT,
            direcao TEXT NOT NULL,
            tipo TEXT DEFAULT 'texto',
            conteudo TEXT,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS resultados (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id TEXT NOT NULL,
            loja_id INTEGER NOT NULL DEFAULT 1,
            resultado TEXT NOT NULL,
            motivo TEXT,
            vendedor TEXT,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conexao.commit()
    conexao.close()
    migrar()
    print(f"Tabelas criadas/migradas (schema v{VERSAO_SCHEMA}).")


# =====================================================================
# MIGRAÇÕES VERSIONADAS (Arquitetura 4.0, item 1.1)
# O "PRAGMA user_version" guarda a versão do schema dentro do próprio .db.
# Cada migração roda UMA vez, inteira ou nada.
# Regra: nunca editar uma migração já usada; criar a próxima (2, 3...).
# =====================================================================

_MIGRACAO_1 = """
CREATE TABLE IF NOT EXISTS lojas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    segmento TEXT NOT NULL DEFAULT 'veiculos',
    config TEXT NOT NULL DEFAULT '{}',
    versao_config INTEGER NOT NULL DEFAULT 1,
    ativo INTEGER NOT NULL DEFAULT 1,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Liga uma conta externa (número, conta do Instagram, bot) a UMA loja.
CREATE TABLE IF NOT EXISTS canais (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loja_id INTEGER NOT NULL REFERENCES lojas(id),
    tipo TEXT NOT NULL CHECK (tipo IN ('whatsapp','instagram','telegram','simulador')),
    id_externo TEXT NOT NULL,
    token_ref TEXT,
    ativo INTEGER NOT NULL DEFAULT 1,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (tipo, id_externo)
);

-- loja_id vazio (NULL) = operador (você), que enxerga todas as lojas.
CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loja_id INTEGER REFERENCES lojas(id),
    nome TEXT NOT NULL,
    papel TEXT NOT NULL CHECK (papel IN ('vendedor','gestor','operador')),
    contato_telegram TEXT,
    contato_whatsapp TEXT,
    senha_hash TEXT,
    ativo INTEGER NOT NULL DEFAULT 1,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS optouts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loja_id INTEGER NOT NULL,
    lead_id TEXT NOT NULL,
    canal TEXT NOT NULL,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (loja_id, lead_id, canal)
);

CREATE TABLE IF NOT EXISTS uso_custos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loja_id INTEGER NOT NULL,
    lead_id TEXT,
    canal TEXT,
    execucao_id TEXT NOT NULL,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    tokens_entrada INTEGER NOT NULL DEFAULT 0,
    tokens_saida INTEGER NOT NULL DEFAULT 0,
    tokens_audio INTEGER NOT NULL DEFAULT 0,
    msgs_servico INTEGER NOT NULL DEFAULT 0,
    msgs_utilidade INTEGER NOT NULL DEFAULT 0,
    msgs_marketing INTEGER NOT NULL DEFAULT 0,
    custo_llm REAL NOT NULL DEFAULT 0,
    custo_meta REAL NOT NULL DEFAULT 0,
    ferramentas TEXT,
    latencia_ms INTEGER
);

-- Preços com data de vigência, nunca no código. O Gemini cobra em dólar.
CREATE TABLE IF NOT EXISTS precos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item TEXT NOT NULL,
    valor REAL NOT NULL,
    moeda TEXT NOT NULL DEFAULT 'BRL',
    unidade TEXT,
    vigente_desde DATE NOT NULL,
    UNIQUE (item, vigente_desde)
);

CREATE TABLE IF NOT EXISTS conhecimento (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loja_id INTEGER NOT NULL,
    titulo TEXT NOT NULL,
    texto TEXT NOT NULL,
    atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS config_historico (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loja_id INTEGER NOT NULL,
    usuario TEXT NOT NULL,
    chave TEXT NOT NULL,
    valor_antigo TEXT,
    valor_novo TEXT,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- leads: no banco antigo, lead_id era único sozinho. O SQLite não altera
-- uma restrição existente, então a tabela é reconstruída com os dados.
CREATE TABLE leads_nova (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id TEXT NOT NULL,
    loja_id INTEGER NOT NULL DEFAULT 1,
    nome TEXT, interesse TEXT, forma_pagamento TEXT, tem_troca TEXT, prazo TEXT,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (loja_id, lead_id)
);
INSERT INTO leads_nova (id, lead_id, loja_id, nome, interesse, forma_pagamento,
                        tem_troca, prazo, criado_em, atualizado_em)
    SELECT id, lead_id, loja_id, nome, interesse, forma_pagamento,
           tem_troca, prazo, criado_em, atualizado_em
    FROM leads;
DROP TABLE leads;
ALTER TABLE leads_nova RENAME TO leads;

-- Índices: toda consulta passa a começar por loja_id.
CREATE INDEX IF NOT EXISTS idx_estoque_loja      ON estoque(loja_id, status);
CREATE INDEX IF NOT EXISTS idx_mensagens_loja    ON mensagens(loja_id, lead_id, id);
CREATE INDEX IF NOT EXISTS idx_handoffs_loja     ON handoffs(loja_id, lead_id, estado);
CREATE INDEX IF NOT EXISTS idx_agendamentos_loja ON agendamentos(loja_id, lead_id, tipo);
CREATE INDEX IF NOT EXISTS idx_trocas_loja       ON trocas(loja_id, lead_id);
CREATE INDEX IF NOT EXISTS idx_resultados_loja   ON resultados(loja_id, lead_id);
CREATE INDEX IF NOT EXISTS idx_custos_loja_data  ON uso_custos(loja_id, criado_em);

-- Semeia a loja 1 com os dados de hoje (config vazia = todos os padrões).
INSERT OR IGNORE INTO lojas (id, nome, segmento, config) VALUES (1, 'Loja 1', 'veiculos', '{}');
"""

_MIGRACAO_2 = """
-- Bloco 6: o que gerou o custo (turno, transcrição, erro), qual modelo de IA
-- respondeu, e se todos os preços necessários estavam cadastrados.
ALTER TABLE uso_custos ADD COLUMN tipo TEXT NOT NULL DEFAULT 'turno';
ALTER TABLE uso_custos ADD COLUMN modelo TEXT;
ALTER TABLE uso_custos ADD COLUMN custo_completo INTEGER NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS idx_custos_execucao ON uso_custos(execucao_id);
"""

_MIGRACAO_3 = """
-- Bloco 7A: o que o Léo percebeu na conversa (agora não, sem interesse,
-- não quer contato). Ninguém digita comando, o Léo entende pela conversa.
CREATE TABLE IF NOT EXISTS situacao_lead (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loja_id INTEGER NOT NULL,
    lead_id TEXT NOT NULL,
    situacao TEXT NOT NULL CHECK (situacao IN ('pediu_tempo','sem_interesse','nao_contatar')),
    motivo TEXT,
    retomar_em DATE,
    atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (loja_id, lead_id)
);
ALTER TABLE optouts ADD COLUMN motivo TEXT;
-- Mensagem escrita pelo vendedor no painel: direcao = 'vendedor', autor = nome.
ALTER TABLE mensagens ADD COLUMN autor TEXT;
-- origem: quem abriu o handoff (leo ou painel). Os dois carimbos são do Bloco 7B.
ALTER TABLE handoffs ADD COLUMN origem TEXT NOT NULL DEFAULT 'leo';
ALTER TABLE handoffs ADD COLUMN reavisado_em TIMESTAMP;
ALTER TABLE handoffs ADD COLUMN gestor_avisado_em TIMESTAMP;
"""
_MIGRACAO_4 = """
-- Bloco 7B: todo aviso mandado pelo bot de avisos. A etiqueta
-- (tipo, referencia, destino) garante que ninguém recebe o mesmo aviso duas vezes.
CREATE TABLE IF NOT EXISTS avisos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loja_id INTEGER,
    tipo TEXT NOT NULL,
    referencia TEXT NOT NULL,
    destino TEXT NOT NULL,
    texto TEXT,
    status TEXT NOT NULL CHECK (status IN ('enviado','falhou','sem_destino')),
    tentativas INTEGER NOT NULL DEFAULT 0,
    erro TEXT,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (tipo, referencia, destino)
);
CREATE INDEX IF NOT EXISTS idx_avisos_loja ON avisos(loja_id, criado_em);
-- Handoffs que já estavam abertos antes do 7B: dá como avisados, para o
-- relógio não disparar uma enxurrada de avisos antigos na primeira vez.
UPDATE handoffs
   SET avisado_em        = COALESCE(avisado_em, CURRENT_TIMESTAMP),
       reavisado_em      = COALESCE(reavisado_em, CURRENT_TIMESTAMP),
       gestor_avisado_em = COALESCE(gestor_avisado_em, CURRENT_TIMESTAMP)
 WHERE estado != 'encerrado';
"""


MIGRACOES = {1: _MIGRACAO_1, 2: _MIGRACAO_2, 3: _MIGRACAO_3, 4: _MIGRACAO_4}
VERSAO_SCHEMA = max(MIGRACOES)


def versao_schema(conexao) -> int:
    return conexao.execute("PRAGMA user_version").fetchone()[0]


def migrar() -> None:
    """Aplica, em ordem, as migrações que ainda não rodaram neste banco.
    Se uma falhar no meio, fechar sem COMMIT desfaz tudo dela."""
    conexao = conectar()
    try:
        atual = versao_schema(conexao)
        for versao in sorted(MIGRACOES):
            if versao <= atual:
                continue
            conexao.executescript(
                "BEGIN;\n" + MIGRACOES[versao]
                + f"\nPRAGMA user_version = {versao};\nCOMMIT;"
            )
    finally:
        conexao.close()


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
