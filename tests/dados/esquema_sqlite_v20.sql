-- Esquema do banco SQLite antigo (loja.db) na versão 20, copiado do próprio banco antes da troca
-- para o PostgreSQL (Maratona Postgres). Só para os testes do scripts/importar_sqlite.py montarem
-- um loja.db fictício. Não é usado pelo Léo.

CREATE TABLE estoque (
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
        );

CREATE TABLE trocas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id TEXT,
            loja_id INTEGER NOT NULL DEFAULT 1,
            modelo TEXT, ano INTEGER, km INTEGER, estado TEXT,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

CREATE TABLE agendamentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id TEXT,
            loja_id INTEGER NOT NULL DEFAULT 1,
            nome_cliente TEXT, tipo TEXT, data_hora TEXT,
            status TEXT DEFAULT 'agendado',
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

CREATE TABLE handoffs (
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
        , origem TEXT NOT NULL DEFAULT 'leo', reavisado_em TIMESTAMP, gestor_avisado_em TIMESTAMP);

CREATE TABLE mensagens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id TEXT NOT NULL,
            loja_id INTEGER NOT NULL DEFAULT 1,
            canal TEXT,
            direcao TEXT NOT NULL,
            tipo TEXT DEFAULT 'texto',
            conteudo TEXT,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        , autor TEXT);

CREATE TABLE resultados (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id TEXT NOT NULL,
            loja_id INTEGER NOT NULL DEFAULT 1,
            resultado TEXT NOT NULL,
            motivo TEXT,
            vendedor TEXT,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

CREATE TABLE lojas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    segmento TEXT NOT NULL DEFAULT 'veiculos',
    config TEXT NOT NULL DEFAULT '{}',
    versao_config INTEGER NOT NULL DEFAULT 1,
    ativo INTEGER NOT NULL DEFAULT 1,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE canais (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loja_id INTEGER NOT NULL REFERENCES lojas(id),
    tipo TEXT NOT NULL CHECK (tipo IN ('whatsapp','instagram','telegram','simulador')),
    id_externo TEXT NOT NULL,
    token_ref TEXT,
    ativo INTEGER NOT NULL DEFAULT 1,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (tipo, id_externo)
);

CREATE TABLE optouts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loja_id INTEGER NOT NULL,
    lead_id TEXT NOT NULL,
    canal TEXT NOT NULL,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP, motivo TEXT,
    UNIQUE (loja_id, lead_id, canal)
);

CREATE TABLE uso_custos (
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
, tipo TEXT NOT NULL DEFAULT 'turno', modelo TEXT, custo_completo INTEGER NOT NULL DEFAULT 0);

CREATE TABLE precos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item TEXT NOT NULL,
    valor REAL NOT NULL,
    moeda TEXT NOT NULL DEFAULT 'BRL',
    unidade TEXT,
    vigente_desde DATE NOT NULL,
    UNIQUE (item, vigente_desde)
);

CREATE TABLE conhecimento (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loja_id INTEGER NOT NULL,
    titulo TEXT NOT NULL,
    texto TEXT NOT NULL,
    atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE config_historico (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loja_id INTEGER NOT NULL,
    usuario TEXT NOT NULL,
    chave TEXT NOT NULL,
    valor_antigo TEXT,
    valor_novo TEXT,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE "leads" (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id TEXT NOT NULL,
    loja_id INTEGER NOT NULL DEFAULT 1,
    nome TEXT, interesse TEXT, forma_pagamento TEXT, tem_troca TEXT, prazo TEXT,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (loja_id, lead_id)
);

CREATE TABLE situacao_lead (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loja_id INTEGER NOT NULL,
    lead_id TEXT NOT NULL,
    situacao TEXT NOT NULL CHECK (situacao IN ('pediu_tempo','sem_interesse','nao_contatar')),
    motivo TEXT,
    retomar_em DATE,
    atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (loja_id, lead_id)
);

CREATE TABLE avisos (
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

CREATE TABLE remarketing_envios (
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

CREATE TABLE vendas (
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

CREATE TABLE reguas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loja_id INTEGER NOT NULL,
    tipo TEXT NOT NULL CHECK (tipo IN ('pos_venda')),
    modelo_origem TEXT,
    ativa INTEGER NOT NULL DEFAULT 1,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE regua_passos (
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

CREATE TABLE regua_execucoes (
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

CREATE TABLE modelos_loja (
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

CREATE TABLE interesse_veiculo (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loja_id INTEGER NOT NULL,
    lead_id TEXT NOT NULL,
    veiculo_id INTEGER NOT NULL,
    atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (loja_id, lead_id)
);

CREATE TABLE importacoes (
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

CREATE TABLE contatos (
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

CREATE TABLE compras_anteriores (
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

CREATE TABLE reativacao (
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

CREATE TABLE pausas_envio (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loja_id INTEGER NOT NULL,
    acao TEXT NOT NULL CHECK (acao IN ('pausar','retomar')),
    usuario TEXT NOT NULL,
    papel TEXT NOT NULL CHECK (papel IN ('cliente','operador')),
    motivo TEXT,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE bloqueios_envio (
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

CREATE TABLE registro_acoes (
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

CREATE TABLE estado_lojas (
    loja_id INTEGER PRIMARY KEY,
    estado TEXT NOT NULL CHECK (estado IN ('em_teste','no_ar')),
    no_ar_em TIMESTAMP,
    alterado_por TEXT,
    atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE numeros_de_teste (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loja_id INTEGER NOT NULL,
    tipo_de_canal TEXT NOT NULL CHECK (tipo_de_canal IN ('whatsapp','telegram','instagram')),
    id_externo TEXT NOT NULL,
    nome TEXT,
    ativo INTEGER NOT NULL DEFAULT 1,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (loja_id, tipo_de_canal, id_externo)
);

CREATE TABLE "usuarios" (
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
);

CREATE TABLE acessos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id INTEGER,
    email TEXT NOT NULL,
    quando TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resultado TEXT NOT NULL
);

CREATE TABLE checklist_implantacao (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loja_id INTEGER NOT NULL,
    item TEXT NOT NULL,
    marcado_por TEXT NOT NULL,
    marcado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    observacao TEXT,
    UNIQUE (loja_id, item)
);

CREATE TABLE sessoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_hash TEXT NOT NULL UNIQUE,
    usuario_id INTEGER NOT NULL,
    loja_id INTEGER NOT NULL,
    papel TEXT NOT NULL,
    escopo TEXT NOT NULL,
    lead_id TEXT,
    criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expira_em TIMESTAMP NOT NULL,
    revogada_em TIMESTAMP
);

CREATE TABLE links_senha (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_hash TEXT NOT NULL UNIQUE,
    usuario_id INTEGER NOT NULL,
    loja_id INTEGER NOT NULL,
    tipo TEXT NOT NULL CHECK (tipo IN ('criar','redefinir')),
    criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expira_em TIMESTAMP NOT NULL,
    usado_em TIMESTAMP,
    revogado_em TIMESTAMP
);

CREATE TABLE links_vendedor (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_hash TEXT NOT NULL UNIQUE,
    loja_id INTEGER NOT NULL,
    usuario_id INTEGER NOT NULL,
    lead_id TEXT NOT NULL,
    criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expira_em TIMESTAMP NOT NULL,
    usado_em TIMESTAMP,
    revogado_em TIMESTAMP
);

CREATE TABLE recados (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loja_id INTEGER NOT NULL,
    autor TEXT NOT NULL,
    texto TEXT NOT NULL,
    valido_ate TEXT NOT NULL,
    ativo INTEGER NOT NULL DEFAULT 1,
    criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE sombra_sugestoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loja_id INTEGER NOT NULL,
    lead_id TEXT NOT NULL,
    canal TEXT NOT NULL,
    mensagem_cliente TEXT NOT NULL,
    sugestao TEXT NOT NULL,
    ferramentas TEXT NOT NULL DEFAULT '[]',
    criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_estoque_loja      ON estoque(loja_id, status);

CREATE INDEX idx_mensagens_loja    ON mensagens(loja_id, lead_id, id);

CREATE INDEX idx_handoffs_loja     ON handoffs(loja_id, lead_id, estado);

CREATE INDEX idx_agendamentos_loja ON agendamentos(loja_id, lead_id, tipo);

CREATE INDEX idx_trocas_loja       ON trocas(loja_id, lead_id);

CREATE INDEX idx_resultados_loja   ON resultados(loja_id, lead_id);

CREATE INDEX idx_custos_loja_data  ON uso_custos(loja_id, criado_em);

CREATE INDEX idx_custos_execucao ON uso_custos(execucao_id);

CREATE INDEX idx_avisos_loja ON avisos(loja_id, criado_em);

CREATE INDEX idx_remarketing_loja ON remarketing_envios(loja_id, estado, criado_em);

CREATE INDEX idx_vendas_loja ON vendas(loja_id, lead_id);

CREATE UNIQUE INDEX idx_reguas_uma_ativa ON reguas(loja_id, tipo) WHERE ativa = 1;

CREATE INDEX idx_passos_regua ON regua_passos(loja_id, regua_id, ordem);

CREATE INDEX idx_execucoes_loja ON regua_execucoes(loja_id, estado, agendado_para);

CREATE INDEX idx_importacoes_loja ON importacoes(loja_id, criado_em);

CREATE INDEX idx_compras_ant_tel ON compras_anteriores(loja_id, telefone);

CREATE INDEX idx_reativacao_loja ON reativacao(loja_id, estado);

CREATE INDEX idx_reativacao_tel ON reativacao(loja_id, telefone);

CREATE INDEX idx_pausas_loja ON pausas_envio(loja_id, id);

CREATE INDEX idx_bloqueios_loja ON bloqueios_envio(loja_id, lead_id, desfeito_em);

CREATE INDEX idx_registro_loja ON registro_acoes(loja_id, quando);

CREATE INDEX idx_numeros_teste_loja ON numeros_de_teste(loja_id, tipo_de_canal, ativo);

CREATE INDEX idx_acessos_email ON acessos(email, quando);

CREATE INDEX idx_mensagens_loja_direcao ON mensagens(loja_id, direcao, criado_em, lead_id);

CREATE INDEX idx_handoffs_loja_estado ON handoffs(loja_id, estado, criado_em);

CREATE INDEX idx_mensagens_direcao_canal ON mensagens(direcao, canal, criado_em);

CREATE INDEX idx_custos_data ON uso_custos(criado_em, tipo, latencia_ms);

CREATE INDEX idx_sessoes_usuario ON sessoes(usuario_id, revogada_em);

CREATE INDEX idx_links_senha_loja ON links_senha(loja_id, usuario_id, usado_em);

CREATE INDEX idx_links_vendedor_loja
    ON links_vendedor(loja_id, usuario_id, lead_id, usado_em);

CREATE INDEX idx_recados_loja ON recados(loja_id, ativo, valido_ate);

CREATE INDEX idx_sombra_loja ON sombra_sugestoes(loja_id, criado_em);

