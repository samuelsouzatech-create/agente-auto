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
_MIGRACAO_5 = """
-- Etapa 2, Bloco 1: remarketing, vendas, régua de pós-venda e status dos
-- modelos de mensagem. loja_id obrigatório e SEM valor padrão.

CREATE TABLE IF NOT EXISTS remarketing_envios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loja_id INTEGER NOT NULL,
    lead_id TEXT NOT NULL,
    canal TEXT NOT NULL,
    toque INTEGER NOT NULL CHECK (toque BETWEEN 1 AND 3),
    veiculo_id INTEGER,
    modelo TEXT,
    categoria TEXT CHECK (categoria IN ('marketing','utilidade','livre')),
    estado TEXT NOT NULL CHECK (estado IN ('enviado','falhou','simulado','bloqueado')),
    motivo_bloqueio TEXT,
    contexto TEXT,
    enviado_em TIMESTAMP,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    custo_meta REAL,
    execucao_id TEXT,
    UNIQUE (loja_id, lead_id, canal, toque)
);
CREATE INDEX IF NOT EXISTS idx_remarketing_loja ON remarketing_envios(loja_id, estado, criado_em);

-- Fonte de acontecimentos do segmento de veículos.
CREATE TABLE IF NOT EXISTS vendas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loja_id INTEGER NOT NULL,
    lead_id TEXT NOT NULL,
    veiculo_id INTEGER NOT NULL,
    data_venda DATE NOT NULL,
    forma_pagamento TEXT NOT NULL CHECK (forma_pagamento IN ('avista','financiado')),
    meses_financiamento INTEGER CHECK (meses_financiamento IS NULL OR meses_financiamento > 0),
    vendedor TEXT,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (loja_id, lead_id, veiculo_id)
);
CREATE INDEX IF NOT EXISTS idx_vendas_loja ON vendas(loja_id, lead_id);

-- Régua de pós-venda (neutra ao segmento).
CREATE TABLE IF NOT EXISTS reguas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loja_id INTEGER NOT NULL,
    tipo TEXT NOT NULL CHECK (tipo IN ('pos_venda')),
    modelo_origem TEXT,
    ativa INTEGER NOT NULL DEFAULT 1,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
-- Uma régua ATIVA por loja e tipo (as inativas ficam de histórico).
CREATE UNIQUE INDEX IF NOT EXISTS idx_reguas_uma_ativa ON reguas(loja_id, tipo) WHERE ativa = 1;

CREATE TABLE IF NOT EXISTS regua_passos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loja_id INTEGER NOT NULL,
    regua_id INTEGER NOT NULL REFERENCES reguas(id),
    ordem INTEGER NOT NULL,
    nome TEXT NOT NULL,
    gatilho TEXT NOT NULL,
    deslocamento_dias INTEGER NOT NULL,
    condicao_pagamento TEXT NOT NULL DEFAULT 'todos'
        CHECK (condicao_pagamento IN ('todos','avista','financiado')),
    acao TEXT NOT NULL CHECK (acao IN ('enviar_modelo','avisar_vendedor')),
    modelo TEXT,
    ativo INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_passos_regua ON regua_passos(loja_id, regua_id, ordem);

CREATE TABLE IF NOT EXISTS regua_execucoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loja_id INTEGER NOT NULL,
    regua_id INTEGER NOT NULL,
    passo_id INTEGER NOT NULL,
    lead_id TEXT NOT NULL,
    evento_tipo TEXT NOT NULL,
    evento_id INTEGER NOT NULL,
    agendado_para TIMESTAMP NOT NULL,
    estado TEXT NOT NULL DEFAULT 'agendado' CHECK (estado IN
        ('agendado','enviado','avisado','falhou','simulado','cancelado','bloqueado')),
    motivo TEXT,
    modelo TEXT,
    categoria TEXT CHECK (categoria IN ('marketing','utilidade','livre')),
    contexto TEXT,
    custo_meta REAL,
    execucao_id TEXT,
    executado_em TIMESTAMP,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (passo_id, evento_tipo, evento_id)
);
CREATE INDEX IF NOT EXISTS idx_execucoes_loja ON regua_execucoes(loja_id, estado, agendado_para);

-- Cada loja tem a própria conta na Meta: aprovação é POR LOJA.
CREATE TABLE IF NOT EXISTS modelos_loja (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loja_id INTEGER NOT NULL,
    nome TEXT NOT NULL,
    idioma TEXT NOT NULL DEFAULT 'pt_BR',
    status TEXT NOT NULL DEFAULT 'rascunho'
        CHECK (status IN ('rascunho','submetido','aprovado','rejeitado')),
    categoria_efetiva TEXT CHECK (categoria_efetiva IN ('marketing','utilidade')),
    atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (loja_id, nome, idioma)
);

-- Carro de interesse do lead (validado contra o estoque da loja no Bloco 5).
-- Tabela própria em vez de ALTER TABLE leads: o SQLite não tem
-- "ADD COLUMN IF NOT EXISTS" e toda migração precisa poder rodar de novo.
CREATE TABLE IF NOT EXISTS interesse_veiculo (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loja_id INTEGER NOT NULL,
    lead_id TEXT NOT NULL,
    veiculo_id INTEGER NOT NULL,
    atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (loja_id, lead_id)
);
"""
_MIGRACAO_6 = """
-- Etapa 2, Bloco 6A: a base que a loja já tinha antes do sistema (planilha/CRM).
CREATE TABLE IF NOT EXISTS importacoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loja_id INTEGER NOT NULL,
    arquivo TEXT,
    usuario TEXT NOT NULL,
    consentimento INTEGER NOT NULL DEFAULT 0,
    linhas INTEGER NOT NULL DEFAULT 0,
    contatos_novos INTEGER NOT NULL DEFAULT 0,
    contatos_atualizados INTEGER NOT NULL DEFAULT 0,
    compras INTEGER NOT NULL DEFAULT 0,
    recusadas INTEGER NOT NULL DEFAULT 0,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    desfeita_em TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_importacoes_loja ON importacoes(loja_id, criado_em);

-- Um contato por telefone (normalizado) em cada loja.
CREATE TABLE IF NOT EXISTS contatos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loja_id INTEGER NOT NULL,
    telefone TEXT NOT NULL,
    nome TEXT,
    origem TEXT NOT NULL DEFAULT 'planilha',
    consentimento INTEGER NOT NULL DEFAULT 0,
    consentimento_em TIMESTAMP,
    consentimento_por TEXT,
    importacao_id INTEGER,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (loja_id, telefone)
);

-- Compras de antes do sistema: o carro não precisa estar no estoque.
CREATE TABLE IF NOT EXISTS compras_anteriores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loja_id INTEGER NOT NULL,
    telefone TEXT NOT NULL,
    descricao TEXT NOT NULL,
    data_compra DATE NOT NULL,
    forma_pagamento TEXT CHECK (forma_pagamento IS NULL OR forma_pagamento IN ('avista','financiado')),
    meses_financiamento INTEGER,
    importacao_id INTEGER,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (loja_id, telefone, descricao, data_compra)
);
CREATE INDEX IF NOT EXISTS idx_compras_ant_tel ON compras_anteriores(loja_id, telefone);
"""
_MIGRACAO_7 = """
-- Etapa 2, Bloco 6C: reativação de contatos antigos da base (uma mensagem por modelo aprovado).
CREATE TABLE IF NOT EXISTS reativacao (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loja_id INTEGER NOT NULL,
    contato_id INTEGER NOT NULL,
    telefone TEXT NOT NULL,
    lote TEXT NOT NULL,
    meses_inativo INTEGER NOT NULL,
    criado_por TEXT NOT NULL,
    lead_id TEXT,
    modelo TEXT,
    categoria TEXT CHECK (categoria IS NULL OR categoria IN ('marketing','utilidade')),
    estado TEXT NOT NULL DEFAULT 'na_fila' CHECK (estado IN
        ('na_fila','simulado','enviado','falhou','bloqueado','cancelado')),
    motivo TEXT,
    texto TEXT,
    tentativas INTEGER NOT NULL DEFAULT 0,
    detalhe TEXT,
    custo_meta REAL,
    execucao_id TEXT,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TIMESTAMP,
    enviado_em TIMESTAMP,
    UNIQUE (loja_id, lote, telefone)
);
CREATE INDEX IF NOT EXISTS idx_reativacao_loja ON reativacao(loja_id, estado);
CREATE INDEX IF NOT EXISTS idx_reativacao_tel ON reativacao(loja_id, telefone);
"""
_MIGRACAO_8 = """
-- Etapa 2, Bloco 7: pausar/retomar todos os envios da loja (dono da loja ou operador).
-- Uma linha por ação; a situação atual é a última linha da loja.
CREATE TABLE IF NOT EXISTS pausas_envio (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loja_id INTEGER NOT NULL,
    acao TEXT NOT NULL CHECK (acao IN ('pausar','retomar')),
    usuario TEXT NOT NULL,
    papel TEXT NOT NULL CHECK (papel IN ('cliente','operador')),
    motivo TEXT,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_pausas_loja ON pausas_envio(loja_id, id);
"""


_MIGRACAO_9 = """
-- P5 (Plano Mestre): "Não enviar" e "Não procurar mais", escolha da LOJA.
-- Não é opt-out (optouts é o pedido do cliente). Desfazer não apaga a linha:
-- grava quem desfez e quando.
CREATE TABLE IF NOT EXISTS bloqueios_envio (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loja_id INTEGER NOT NULL,
    lead_id TEXT NOT NULL,
    tipo TEXT NOT NULL CHECK (tipo IN ('remarketing','pos_venda','reativacao','todos')),
    passo INTEGER,
    criado_por TEXT NOT NULL,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    desfeito_por TEXT,
    desfeito_em TIMESTAMP,
    CHECK (tipo != 'todos' OR passo IS NULL)
);
CREATE INDEX IF NOT EXISTS idx_bloqueios_loja ON bloqueios_envio(loja_id, lead_id, desfeito_em);
"""


_MIGRACAO_10 = """
-- P6 (Plano Mestre): Registro de quem fez o quê. Uma linha por ação relevante.
-- loja_id vazio = evento sem loja (ex.: mensagem de canal sem cadastro).
-- papel sem CHECK de propósito: o P8 traz os papéis de verdade.
-- antes/depois em JSON. quando em UTC, como o resto do banco.
CREATE TABLE IF NOT EXISTS registro_acoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quando TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    loja_id INTEGER,
    pessoa TEXT NOT NULL,
    papel TEXT NOT NULL,
    acao TEXT NOT NULL,
    alvo TEXT,
    antes TEXT,
    depois TEXT,
    origem TEXT NOT NULL CHECK (origem IN ('painel','api','job','webhook'))
);
CREATE INDEX IF NOT EXISTS idx_registro_loja ON registro_acoes(loja_id, quando);
"""

_MIGRACAO_11 = """
-- P7 (Plano Mestre): estado da loja. 'em_teste' = nada proativo sai de verdade
-- e o assistente só responde aos números de teste; 'no_ar' = funciona normal.
-- Não se confunde com 'ativo' (loja desligada) nem com o roteamento dos canais.
-- Tabela própria (e não ALTER TABLE lojas): toda migração precisa poder rodar
-- de novo, e o SQLite não tem "ADD COLUMN IF NOT EXISTS" (mesmo motivo da 5).
-- Loja SEM linha aqui = em teste. Assim toda loja nova nasce em teste.
CREATE TABLE IF NOT EXISTS estado_lojas (
    loja_id INTEGER PRIMARY KEY,
    estado TEXT NOT NULL CHECK (estado IN ('em_teste','no_ar')),
    no_ar_em TIMESTAMP,
    alterado_por TEXT,
    atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
-- As lojas que JÁ existiam continuam como hoje: entram no ar. Só na primeira
-- vez (tabela vazia); rodar de novo não muda o estado de ninguém.
INSERT INTO estado_lojas (loja_id, estado, no_ar_em, alterado_por)
    SELECT id, 'no_ar', CURRENT_TIMESTAMP, 'Sistema' FROM lojas
    WHERE NOT EXISTS (SELECT 1 FROM estado_lojas);
-- Quem pode conversar com uma loja em teste (id_externo já normalizado).
CREATE TABLE IF NOT EXISTS numeros_de_teste (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loja_id INTEGER NOT NULL,
    tipo_de_canal TEXT NOT NULL CHECK (tipo_de_canal IN ('whatsapp','telegram','instagram')),
    id_externo TEXT NOT NULL,
    nome TEXT,
    ativo INTEGER NOT NULL DEFAULT 1,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (loja_id, tipo_de_canal, id_externo)
);
CREATE INDEX IF NOT EXISTS idx_numeros_teste_loja ON numeros_de_teste(loja_id, tipo_de_canal, ativo);
"""


# ---------------------------------------------------------------------
# Migração 12 (P8 do Plano Mestre): usuarios_login.
# É a primeira migração em Python, e não em texto SQL. Motivo: ela precisa
# RECRIAR a tabela usuarios (o SQLite não altera um CHECK) e toda migração
# precisa poder rodar de novo (testes antigos voltam o user_version). Em
# texto SQL, rodar de novo recriaria a tabela e perderia os e-mails. Aqui a
# função olha a tabela antes: se a coluna email já existe, não recria.
# migrar() roda a função numa transação só: erro no meio = nada muda.
# ---------------------------------------------------------------------

class MigracaoRecusada(RuntimeError):
    """A migração achou dados que não pode levar sem perder nada: parou e não mudou nada."""


_COLUNAS_USUARIOS_V12 = (
    "id", "loja_id", "nome", "papel", "email", "contato_telegram", "contato_whatsapp",
    "senha_hash", "ativo", "criado_em", "ultimo_acesso",
)

# loja_id vazio só para operador e suporte (enxergam todas as lojas);
# vendedor, gestor ("Gerente" nas telas) e dono sempre têm loja.
# e-mail é o login: único, sem diferença entre maiúsculas e minúsculas.
# Usuários antigos ficam sem e-mail (vazio) até o operador cadastrar.
_TABELA_USUARIOS_V12 = """
CREATE TABLE usuarios_v12 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loja_id INTEGER REFERENCES lojas(id),
    nome TEXT NOT NULL,
    papel TEXT NOT NULL CHECK (papel IN ('vendedor','gestor','dono','operador','suporte')),
    email TEXT COLLATE NOCASE UNIQUE,
    contato_telegram TEXT,
    contato_whatsapp TEXT,
    senha_hash TEXT,
    ativo INTEGER NOT NULL DEFAULT 1,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ultimo_acesso TIMESTAMP,
    CHECK ((papel IN ('operador','suporte')) = (loja_id IS NULL))
)
"""

# Uma linha por tentativa de login (limite de tentativas e registro de uso).
# resultado sem CHECK de propósito (como o papel do registro_acoes): o C3
# (link do vendedor) vai gravar outros resultados aqui. O código valida.
_TABELA_ACESSOS_V12 = """
CREATE TABLE IF NOT EXISTS acessos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id INTEGER,
    email TEXT NOT NULL,
    quando TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resultado TEXT NOT NULL
)
"""
_INDICE_ACESSOS_V12 = "CREATE INDEX IF NOT EXISTS idx_acessos_email ON acessos(email, quando)"


def _recriar_usuarios_v12(conexao, colunas_antigas) -> None:
    """Cria a tabela nova, copia TODOS os usuários com os mesmos ids, troca as
    tabelas e mantém o contador de ids (id apagado não volta a ser usado)."""
    ruins = [l[0] for l in conexao.execute(
        "SELECT id FROM usuarios "
        "WHERE (papel IN ('operador','suporte')) != (loja_id IS NULL) ORDER BY id")]
    if ruins:
        raise MigracaoRecusada(
            "Migração 12 parada, nada foi mudado: usuário(s) com papel e loja que não "
            f"combinam (ids {', '.join(map(str, ruins))}). Operador fica sem loja; "
            "vendedor e gestor ficam com loja.")
    linha = conexao.execute("SELECT seq FROM sqlite_sequence WHERE name = 'usuarios'").fetchone()
    contador = linha[0] if linha else 0
    total = conexao.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0]
    conexao.execute("DROP TABLE IF EXISTS usuarios_v12")
    conexao.execute(_TABELA_USUARIOS_V12)
    comuns = ", ".join(c for c in _COLUNAS_USUARIOS_V12 if c in colunas_antigas)
    conexao.execute(f"INSERT INTO usuarios_v12 ({comuns}) SELECT {comuns} FROM usuarios")
    if conexao.execute("SELECT COUNT(*) FROM usuarios_v12").fetchone()[0] != total:
        raise MigracaoRecusada("Migração 12 parada, nada foi mudado: a cópia dos usuários não bateu.")
    conexao.execute("DROP TABLE usuarios")
    conexao.execute("ALTER TABLE usuarios_v12 RENAME TO usuarios")
    maior = conexao.execute("SELECT COALESCE(MAX(id), 0) FROM usuarios").fetchone()[0]
    contador = max(contador or 0, maior)
    if contador:
        atualizou = conexao.execute(
            "UPDATE sqlite_sequence SET seq = ? WHERE name = 'usuarios'", (contador,)).rowcount
        if not atualizou:
            conexao.execute("INSERT INTO sqlite_sequence (name, seq) VALUES ('usuarios', ?)",
                            (contador,))


def _migracao_12(conexao) -> None:
    colunas = [l[1] for l in conexao.execute("PRAGMA table_info(usuarios)")]
    if "email" not in colunas:          # primeira vez: recria. Rodando de novo: não mexe.
        _recriar_usuarios_v12(conexao, colunas)
    conexao.execute(_TABELA_ACESSOS_V12)
    conexao.execute(_INDICE_ACESSOS_V12)


def _rodar_migracao_python(conexao, versao, passo) -> None:
    """Migração em Python: tudo numa transação só. Erro no meio = nada muda."""
    anterior = conexao.isolation_level
    conexao.isolation_level = None          # aqui nós controlamos BEGIN e COMMIT
    try:
        conexao.execute("BEGIN")
        try:
            passo(conexao)
            conexao.execute(f"PRAGMA user_version = {int(versao)}")
            conexao.execute("COMMIT")
        except BaseException:
            if conexao.in_transaction:
                conexao.execute("ROLLBACK")
            raise
    finally:
        conexao.isolation_level = anterior


_MIGRACAO_13 = """
-- S2 (Fase 3): itens MANUAIS do checklist de implantação (o operador marca,
-- com autor e data). Os itens automáticos são conferidos na hora por
-- app/implantacao.py e não ficam aqui. item sem CHECK de propósito: a lista
-- mora no código. Pode rodar de novo (IF NOT EXISTS): testes antigos voltam
-- o user_version e rodam tudo outra vez.
CREATE TABLE IF NOT EXISTS checklist_implantacao (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loja_id INTEGER NOT NULL,
    item TEXT NOT NULL,
    marcado_por TEXT NOT NULL,
    marcado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    observacao TEXT,
    UNIQUE (loja_id, item)
);
"""


_MIGRACAO_14 = """
-- S10 (Fase 3): índices para as telas do operador. Só cria índice: nenhum
-- dado muda e nada é apagado. IF NOT EXISTS: pode rodar de novo (testes
-- antigos voltam o user_version). Número 14 (decisão 2A do analista): as
-- v14 e v15 da branch painel-rotas passam a ser 15 e 16.
-- Regra: loja_id na frente. remarketing_envios, leads e uso_custos já têm
-- índice por loja (migrações 1 e 5): nada novo neles.
CREATE INDEX IF NOT EXISTS idx_mensagens_loja_direcao ON mensagens(loja_id, direcao, criado_em, lead_id);
CREATE INDEX IF NOT EXISTS idx_handoffs_loja_estado ON handoffs(loja_id, estado, criado_em);
-- As duas exceções (decisão 3A): consultas da Visão geral que olham TODAS
-- as lojas, só no painel do operador. Valem porque o EXPLAIN QUERY PLAN
-- mostra que são usadas (tests/test_s10b_limpeza.py). O painel do cliente
-- continua sempre filtrando por loja.
CREATE INDEX IF NOT EXISTS idx_mensagens_direcao_canal ON mensagens(direcao, canal, criado_em);
CREATE INDEX IF NOT EXISTS idx_custos_data ON uso_custos(criado_em, tipo, latencia_ms);
"""


MIGRACOES = {1: _MIGRACAO_1, 2: _MIGRACAO_2, 3: _MIGRACAO_3, 4: _MIGRACAO_4, 5: _MIGRACAO_5, 6: _MIGRACAO_6, 7: _MIGRACAO_7, 8: _MIGRACAO_8, 9: _MIGRACAO_9, 10: _MIGRACAO_10, 11: _MIGRACAO_11, 12: _migracao_12, 13: _MIGRACAO_13, 14: _MIGRACAO_14}
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
            passo = MIGRACOES[versao]
            if callable(passo):              # migração em Python (a partir da 12)
                _rodar_migracao_python(conexao, versao, passo)
                continue
            conexao.executescript(
                "BEGIN;\n" + passo
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
