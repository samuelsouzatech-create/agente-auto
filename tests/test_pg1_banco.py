"""
PG1 (Maratona Postgres): o banco PostgreSQL e a camada única de conexão (banco.py).

- A migração-base cria exatamente as tabelas, colunas e índices que o SQLite tinha na v20.
- O registro de migrações aplicadas fica no próprio banco; rodar de novo não refaz nada;
  migração com erro no meio não deixa nada pela metade; número nunca se repete; 21 = Instagram.
- A camada traduz o jeito SQLite ("?", INSERT OR IGNORE, LIKE, CURRENT_TIMESTAMP) e devolve
  linhas por posição e por nome; True/False viram 1/0; datas viram o mesmo texto de antes.
- Busca sem acento (unaccent) e fone_br do banco dão o mesmo resultado das funções em Python.
- Os testes usam um banco separado (_teste), nunca o de uso; nenhum código do Léo usa sqlite3.
"""
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

import banco
from app.telefone import normalizar_telefone_br

RAIZ = Path(__file__).resolve().parent.parent

# Gerado do banco SQLite na v20 (antes da troca): tabela -> colunas, na ordem.
ESQUEMA_V20 = {
    'acessos': ('id', 'usuario_id', 'email', 'quando', 'resultado'),
    'agendamentos': ('id', 'lead_id', 'loja_id', 'nome_cliente', 'tipo', 'data_hora', 'status', 'criado_em'),
    'avisos': ('id', 'loja_id', 'tipo', 'referencia', 'destino', 'texto', 'status', 'tentativas', 'erro', 'criado_em', 'atualizado_em'),
    'bloqueios_envio': ('id', 'loja_id', 'lead_id', 'tipo', 'passo', 'criado_por', 'criado_em', 'desfeito_por', 'desfeito_em'),
    'canais': ('id', 'loja_id', 'tipo', 'id_externo', 'token_ref', 'ativo', 'criado_em'),
    'checklist_implantacao': ('id', 'loja_id', 'item', 'marcado_por', 'marcado_em', 'observacao'),
    'compras_anteriores': ('id', 'loja_id', 'telefone', 'descricao', 'data_compra', 'forma_pagamento', 'meses_financiamento', 'importacao_id', 'criado_em'),
    'config_historico': ('id', 'loja_id', 'usuario', 'chave', 'valor_antigo', 'valor_novo', 'criado_em'),
    'conhecimento': ('id', 'loja_id', 'titulo', 'texto', 'atualizado_em'),
    'contatos': ('id', 'loja_id', 'telefone', 'nome', 'origem', 'consentimento', 'consentimento_em', 'consentimento_por', 'importacao_id', 'criado_em', 'atualizado_em'),
    'estado_lojas': ('loja_id', 'estado', 'no_ar_em', 'alterado_por', 'atualizado_em'),
    'estoque': ('id', 'loja_id', 'marca', 'modelo', 'ano', 'km', 'cor', 'cambio', 'preco', 'status', 'fotos'),
    'handoffs': ('id', 'lead_id', 'loja_id', 'motivo', 'resumo', 'estado', 'vendedor', 'criado_em', 'avisado_em', 'assumido_em', 'encerrado_em', 'origem', 'reavisado_em', 'gestor_avisado_em'),
    'importacoes': ('id', 'loja_id', 'arquivo', 'usuario', 'consentimento', 'linhas', 'contatos_novos', 'contatos_atualizados', 'compras', 'recusadas', 'criado_em', 'desfeita_em'),
    'interesse_veiculo': ('id', 'loja_id', 'lead_id', 'veiculo_id', 'atualizado_em'),
    'leads': ('id', 'lead_id', 'loja_id', 'nome', 'interesse', 'forma_pagamento', 'tem_troca', 'prazo', 'criado_em', 'atualizado_em'),
    'links_senha': ('id', 'token_hash', 'usuario_id', 'loja_id', 'tipo', 'criado_em', 'expira_em', 'usado_em', 'revogado_em'),
    'links_vendedor': ('id', 'token_hash', 'loja_id', 'usuario_id', 'lead_id', 'criado_em', 'expira_em', 'usado_em', 'revogado_em'),
    'lojas': ('id', 'nome', 'segmento', 'config', 'versao_config', 'ativo', 'criado_em'),
    'mensagens': ('id', 'lead_id', 'loja_id', 'canal', 'direcao', 'tipo', 'conteudo', 'criado_em', 'autor'),
    'modelos_loja': ('id', 'loja_id', 'nome', 'idioma', 'status', 'categoria_efetiva', 'atualizado_em'),
    'numeros_de_teste': ('id', 'loja_id', 'tipo_de_canal', 'id_externo', 'nome', 'ativo', 'criado_em'),
    'optouts': ('id', 'loja_id', 'lead_id', 'canal', 'criado_em', 'motivo'),
    'pausas_envio': ('id', 'loja_id', 'acao', 'usuario', 'papel', 'motivo', 'criado_em'),
    'precos': ('id', 'item', 'valor', 'moeda', 'unidade', 'vigente_desde'),
    'reativacao': ('id', 'loja_id', 'contato_id', 'telefone', 'lote', 'meses_inativo', 'criado_por', 'lead_id', 'modelo', 'categoria', 'estado', 'motivo', 'texto', 'tentativas', 'detalhe', 'custo_meta', 'execucao_id', 'criado_em', 'atualizado_em', 'enviado_em'),
    'recados': ('id', 'loja_id', 'autor', 'texto', 'valido_ate', 'ativo', 'criado_em'),
    'registro_acoes': ('id', 'quando', 'loja_id', 'pessoa', 'papel', 'acao', 'alvo', 'antes', 'depois', 'origem'),
    'regua_execucoes': ('id', 'loja_id', 'regua_id', 'passo_id', 'lead_id', 'evento_tipo', 'evento_id', 'agendado_para', 'estado', 'motivo', 'modelo', 'categoria', 'contexto', 'custo_meta', 'execucao_id', 'executado_em', 'criado_em'),
    'regua_passos': ('id', 'loja_id', 'regua_id', 'ordem', 'nome', 'gatilho', 'deslocamento_dias', 'condicao_pagamento', 'acao', 'modelo', 'ativo'),
    'reguas': ('id', 'loja_id', 'tipo', 'modelo_origem', 'ativa', 'criado_em', 'atualizado_em'),
    'remarketing_envios': ('id', 'loja_id', 'lead_id', 'canal', 'toque', 'veiculo_id', 'modelo', 'categoria', 'estado', 'motivo_bloqueio', 'contexto', 'enviado_em', 'criado_em', 'custo_meta', 'execucao_id'),
    'resultados': ('id', 'lead_id', 'loja_id', 'resultado', 'motivo', 'vendedor', 'criado_em'),
    'sessoes': ('id', 'token_hash', 'usuario_id', 'loja_id', 'papel', 'escopo', 'lead_id', 'criado_em', 'expira_em', 'revogada_em'),
    'situacao_lead': ('id', 'loja_id', 'lead_id', 'situacao', 'motivo', 'retomar_em', 'atualizado_em'),
    'sombra_sugestoes': ('id', 'loja_id', 'lead_id', 'canal', 'mensagem_cliente', 'sugestao', 'ferramentas', 'criado_em'),
    'trocas': ('id', 'lead_id', 'loja_id', 'modelo', 'ano', 'km', 'estado', 'criado_em'),
    'uso_custos': ('id', 'loja_id', 'lead_id', 'canal', 'execucao_id', 'criado_em', 'tokens_entrada', 'tokens_saida', 'tokens_audio', 'msgs_servico', 'msgs_utilidade', 'msgs_marketing', 'custo_llm', 'custo_meta', 'ferramentas', 'latencia_ms', 'tipo', 'modelo', 'custo_completo'),
    'usuarios': ('id', 'loja_id', 'nome', 'papel', 'email', 'contato_telegram', 'contato_whatsapp', 'senha_hash', 'ativo', 'criado_em', 'ultimo_acesso'),
    'vendas': ('id', 'loja_id', 'lead_id', 'veiculo_id', 'data_venda', 'forma_pagamento', 'meses_financiamento', 'vendedor', 'criado_em'),
}
INDICES_V20 = ('idx_acessos_email', 'idx_agendamentos_loja', 'idx_avisos_loja', 'idx_bloqueios_loja', 'idx_compras_ant_tel', 'idx_custos_data', 'idx_custos_execucao', 'idx_custos_loja_data', 'idx_estoque_loja', 'idx_execucoes_loja', 'idx_handoffs_loja', 'idx_handoffs_loja_estado', 'idx_importacoes_loja', 'idx_links_senha_loja', 'idx_links_vendedor_loja', 'idx_mensagens_direcao_canal', 'idx_mensagens_loja', 'idx_mensagens_loja_direcao', 'idx_numeros_teste_loja', 'idx_passos_regua', 'idx_pausas_loja', 'idx_reativacao_loja', 'idx_reativacao_tel', 'idx_recados_loja', 'idx_registro_loja', 'idx_reguas_uma_ativa', 'idx_remarketing_loja', 'idx_resultados_loja', 'idx_sessoes_usuario', 'idx_sombra_loja', 'idx_trocas_loja', 'idx_vendas_loja')


def _um(comando, parametros=()):
    c = banco.conectar()
    try:
        return c.execute(comando, parametros).fetchone()[0]
    finally:
        c.close()


def _executar(comando, parametros=()):
    c = banco.conectar()
    try:
        cur = c.execute(comando, parametros)
        c.commit()
        return cur
    finally:
        c.close()


# ------------------------------------------------------------ esquema

def test_base_tem_as_mesmas_tabelas_e_colunas_do_sqlite_v20():
    memoria = {"checkpoints", "checkpoint_blobs", "checkpoint_writes", "checkpoint_migrations"}
    # IG1 (Maratona 4): a migração 21 (Instagram) só ACRESCENTA tabelas e colunas, no fim.
    mig21 = {"instagram_comentarios", "instagram_legendas", "clientes_vinculados", "pedidos_exclusao"}
    novas_21 = {"mensagens": ("id_externo",), "leads": ("origem", "origem_detalhe", "telefone", "telefone_em")}
    mig22 = {"cofre_credenciais"}      # SE2 (Maratona Segurança): só acrescenta a tabela do cofre
    assert set(banco.tabelas()) == set(ESQUEMA_V20) | memoria | mig21 | mig22     # PG2: + memória das conversas
    for tabela, colunas in ESQUEMA_V20.items():
        assert tuple(banco.colunas(tabela)) == colunas + novas_21.get(tabela, ()), tabela


def test_base_tem_os_mesmos_indices_e_o_do_email():
    c = banco.conectar()
    try:
        nomes = {r[0] for r in c.execute(
            "SELECT indexname FROM pg_indexes WHERE schemaname = current_schema()").fetchall()}
    finally:
        c.close()
    assert set(INDICES_V20) <= nomes
    assert "idx_usuarios_email" in nomes


def test_registro_de_migracoes_e_rodar_de_novo_nao_refaz_nada():
    # IG1 (Maratona 4): + a migração 21 (Instagram).
    assert banco.versao_schema() == banco.VERSAO_SCHEMA >= 22      # SE2: a 22 (cofre)
    assert _um("SELECT nome FROM migracoes_aplicadas WHERE versao = 20") == "base_postgres"
    assert _um("SELECT nome FROM migracoes_aplicadas WHERE versao = 21") == "instagram"
    assert banco.migrar() == []
    assert _um("SELECT COUNT(*) FROM migracoes_aplicadas") == len(banco.migracoes_disponiveis())   # SE2: + a 22
    assert _um("SELECT COUNT(*) FROM lojas") == 1      # a semente não duplica


def test_loja_1_nasce_no_ar_e_o_proximo_id_e_2():
    assert _um("SELECT estado FROM estado_lojas WHERE loja_id = 1") == "no_ar"
    novo = _executar("INSERT INTO lojas (nome) VALUES (?)", ("Loja B",)).lastrowid
    assert novo == 2


def test_numeracao_das_migracoes(tmp_path, monkeypatch):
    monkeypatch.setattr(banco, "PASTA_MIGRACOES", tmp_path)
    (tmp_path / "020_base_postgres.sql").write_text("SELECT 1;", encoding="utf-8")
    (tmp_path / "022_coisa.sql").write_text("SELECT 1;", encoding="utf-8")
    assert [n for n, _, _ in banco.migracoes_disponiveis()] == [20, 22]
    (tmp_path / "022_outra.sql").write_text("SELECT 1;", encoding="utf-8")
    with pytest.raises(RuntimeError, match="mesmo número"):
        banco.migracoes_disponiveis()
    (tmp_path / "022_outra.sql").unlink()
    (tmp_path / "021_qualquer.sql").write_text("SELECT 1;", encoding="utf-8")
    with pytest.raises(RuntimeError, match="Instagram"):
        banco.migracoes_disponiveis()


def test_migracao_com_erro_no_meio_nao_deixa_nada_pela_metade(tmp_path, monkeypatch):
    for arquivo in banco.PASTA_MIGRACOES.glob("*.sql"):
        (tmp_path / arquivo.name).write_text(arquivo.read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "999_quebrada.sql").write_text(                  # SE2: número que nunca existirá
        "CREATE TABLE tabela_nova (id BIGINT);\nSELECT * FROM tabela_que_nao_existe;\n",
        encoding="utf-8")
    monkeypatch.setattr(banco, "PASTA_MIGRACOES", tmp_path)
    with pytest.raises(Exception):
        banco.migrar()
    assert "tabela_nova" not in banco.tabelas()
    assert banco.versao_schema() == banco.VERSAO_SCHEMA      # as de verdade já estavam aplicadas


# ------------------------------------------------------------ tradução do SQL

@pytest.mark.parametrize("antes,com,depois", [
    ("SELECT * FROM t WHERE a = ? AND b = ?", True, "SELECT * FROM t WHERE a = %s AND b = %s"),
    ("SELECT '?' , x FROM t WHERE y LIKE ?", True, "SELECT '?' , x FROM t WHERE y ILIKE %s"),
    ("SELECT 'a%b' FROM t WHERE c = ?", True, "SELECT 'a%%b' FROM t WHERE c = %s"),
    ("INSERT OR IGNORE INTO t (a) VALUES (?)", True,
     "INSERT INTO t (a) VALUES (%s) ON CONFLICT DO NOTHING"),
    ("UPDATE t SET quando = CURRENT_TIMESTAMP WHERE id = ?", True,
     "UPDATE t SET quando = agora_texto() WHERE id = %s"),
    ("SELECT x -- com ? e LIKE\nFROM t", False, "SELECT x -- com ? e LIKE\nFROM t"),
])
def test_traducao_do_jeito_sqlite(antes, com, depois):
    assert banco.traduzir(antes, com)[0] == depois


@pytest.mark.parametrize("comando", ["PRAGMA user_version", "INSERT OR REPLACE INTO t VALUES (1)"])
def test_comando_so_do_sqlite_e_recusado(comando):
    with pytest.raises(NotImplementedError):
        banco.traduzir(comando, False)


def test_linha_por_posicao_e_por_nome_e_tipos_como_no_sqlite():
    novo = _executar(
        "INSERT INTO numeros_de_teste (loja_id, tipo_de_canal, id_externo, ativo, criado_em) "
        "VALUES (?, ?, ?, ?, ?)",
        (1, "telegram", "123", True, datetime(2026, 11, 23, 13, 5, 7))).lastrowid
    c = banco.conectar()
    try:
        linha = c.execute("SELECT * FROM numeros_de_teste WHERE id = ?", (novo,)).fetchone()
        soma = c.execute("SELECT SUM(ativo), AVG(ativo) FROM numeros_de_teste").fetchone()
    finally:
        c.close()
    assert linha["ativo"] == linha[5] == 1
    assert linha["criado_em"] == "2026-11-23 13:05:07"
    assert dict(linha)["id_externo"] == "123" and "tipo_de_canal" in linha.keys()
    assert soma[0] == 1 and isinstance(soma[0], int) and soma[1] == 1.0
    assert _um("SELECT COUNT(*) FROM numeros_de_teste WHERE criado_em >= ?",
               (date(2026, 11, 23),)) == 1


def test_texto_comparado_com_numero_e_numero_com_texto():
    _executar("INSERT INTO mensagens (lead_id, loja_id, direcao) VALUES (?, ?, ?)", ("555", "1", "cliente"))
    assert _um("SELECT COUNT(*) FROM mensagens WHERE lead_id = ? AND loja_id = ?", (555, 1)) == 1


def test_like_nao_diferencia_maiusculas_como_no_sqlite():
    _executar("INSERT INTO conhecimento (loja_id, titulo, texto) VALUES (1, 'Garantia', 'x')")
    assert _um("SELECT COUNT(*) FROM conhecimento WHERE titulo LIKE ?", ("%garantia%",)) == 1


def test_current_timestamp_grava_texto_utc():
    _executar("INSERT INTO recados (loja_id, autor, texto, valido_ate, criado_em) "
              "VALUES (1, 'a', 'b', '2026-12-01', CURRENT_TIMESTAMP)")
    gravado = _um("SELECT criado_em FROM recados")
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", gravado)
    assert gravado[:13] == datetime.now(timezone.utc).strftime("%Y-%m-%d %H")


def test_with_confirma_e_erro_desfaz():
    c = banco.conectar()
    try:
        with c:
            c.execute("INSERT INTO conhecimento (loja_id, titulo, texto) VALUES (1, 'a', 'b')")
        with pytest.raises(banco.ErroDeIntegridade):
            with c:
                c.execute("INSERT INTO conhecimento (loja_id, titulo, texto) VALUES (1, 'c', 'd')")
                c.execute("INSERT INTO lojas (id, nome) VALUES (1, 'repetida')")
    finally:
        c.close()
    assert _um("SELECT COUNT(*) FROM conhecimento") == 1


def test_fechar_sem_commit_desfaz():
    c = banco.conectar()
    c.execute("INSERT INTO conhecimento (loja_id, titulo, texto) VALUES (1, 'a', 'b')")
    c.close()
    assert _um("SELECT COUNT(*) FROM conhecimento") == 0


def test_conexao_somente_leitura_recusa_escrita():
    c = banco.conectar(somente_leitura=True)
    try:
        assert c.execute("SELECT COUNT(*) FROM lojas").fetchone()[0] == 1
        with pytest.raises(banco.Erro):
            c.execute("DELETE FROM lojas")
    finally:
        c.close()
    assert _um("SELECT COUNT(*) FROM lojas") == 1


def test_insert_or_ignore_nao_duplica():
    for _ in range(2):
        _executar("INSERT OR IGNORE INTO optouts (loja_id, lead_id, canal) VALUES (1, 'x', 'whatsapp')")
    assert _um("SELECT COUNT(*) FROM optouts") == 1


def test_conexoes_voltam_para_o_pool():
    for _ in range(3 * banco.POOL_MAX):
        c = banco.conectar()
        c.execute("SELECT 1").fetchone()
        c.close()
    for _ in range(3 * banco.POOL_MAX):          # esquecida aberta: volta sozinha
        banco.conectar().execute("SELECT 1").fetchone()
    assert _um("SELECT 1") == 1


# ------------------------------------------------------------ funções do banco

@pytest.mark.parametrize("texto,esperado", [
    ("Doblò", "Doblo"), ("Civíc", "Civic"), ("Ação Câmbio Pé", "Acao Cambio Pe"), (None, None)])
def test_sem_acento_do_banco(texto, esperado):
    assert _um("SELECT sem_acento(?)", (texto,)) == esperado


def test_busca_sem_acento_no_estoque():
    _executar("INSERT INTO estoque (loja_id, marca, modelo, ano, km, cor, cambio, preco) "
              "VALUES (1, 'Fiat', 'Doblò', 2016, 1, 'Prata', 'Manual', 50000)")
    assert _um("SELECT COUNT(*) FROM estoque WHERE sem_acento(modelo) LIKE sem_acento(?)",
               ("%doblo%",)) == 1


@pytest.mark.parametrize("texto", [
    "81999998888", "(81) 9 9999-8888", "5581999998888", "+55 81 99999-8888", "8199998888",
    "81 3333-4444", "01999998888", "1234", "", None, "0081999998888", "558188887777",
    "81988887777", "11987654321", "5511987654321", "21 7777-6666", "abc", "081999998888"])
def test_fone_br_do_banco_igual_ao_do_python(texto):
    assert _um("SELECT fone_br(?)", (texto,)) == normalizar_telefone_br(texto)


def test_round_com_numero_decimal():
    assert _um("SELECT round(CAST(? AS double precision), 2)", (1.23456,)) == 1.23


# ------------------------------------------------------------ separação e regras

def test_testes_usam_banco_separado_do_de_uso():
    nome = banco.nome_do_banco(banco.url_do_banco())
    assert nome.endswith("_teste")
    uso = os.environ.get("BANCO_URL")
    assert not uso or nome != banco.nome_do_banco(uso)


def test_apagar_banco_recusa_o_banco_de_uso(monkeypatch):
    monkeypatch.setenv("BANCO_URL", "postgresql://leo@127.0.0.1:5432/leo_de_uso")
    with pytest.raises(RuntimeError, match="banco de uso"):
        banco.apagar_banco("postgresql://leo@127.0.0.1:5432/leo_de_uso")


def test_senha_nao_aparece_no_endereco_mostrado():
    assert "segredo" not in banco.url_sem_senha("postgresql://leo:segredo@127.0.0.1:5432/leo")


def _arquivos_do_leo():
    for pasta in ("app", "tools", "scripts", "paginas", "segmentos", "bancada"):
        if (RAIZ / pasta).exists():
            yield from (RAIZ / pasta).rglob("*.py")
    yield from RAIZ.glob("*.py")


def test_nenhum_codigo_do_leo_usa_sqlite3():
    padrao = re.compile(r"^\s*(import sqlite3|from sqlite3)", re.M)
    usam = sorted(a.relative_to(RAIZ).as_posix() for a in _arquivos_do_leo()
                  if padrao.search(a.read_text(encoding="utf-8")))
    assert set(usam) <= {"scripts/importar_sqlite.py", "scripts/sqlite_legado.py"}


def test_nenhum_arquivo_abre_conexao_por_conta_propria():
    proibido = re.compile(r"psycopg\.connect\(|ConnectionPool\(")
    achados = [a.relative_to(RAIZ).as_posix() for a in _arquivos_do_leo()
               if a.name != "banco.py" and proibido.search(a.read_text(encoding="utf-8"))]
    assert achados == []


def test_compose_tem_so_o_postgres_na_porta_local_e_senha_do_env():
    texto = (RAIZ / "docker-compose.yml").read_text(encoding="utf-8")
    assert "image: postgres:17" in texto
    assert '"127.0.0.1:${BANCO_PORTA:-5432}:5432"' in texto
    assert "POSTGRES_PASSWORD: ${POSTGRES_SENHA" in texto
    assert "leo_banco:/var/lib/postgresql/data" in texto
    # DK1: o compose ganhou as outras peças (conferidas em tests/test_dk1_docker.py).
    servicos = texto.split("\nservices:")[1].split("\nnetworks:")[0]
    assert "postgres" in re.findall(r"^  ([\w-]+):$", servicos, re.M)


def test_env_exemplo_so_tem_texto_de_exemplo():
    texto = (RAIZ / ".env.example").read_text(encoding="utf-8")
    assert "BANCO_URL=postgresql://leo:TROQUE-ESTA-SENHA@" in texto
