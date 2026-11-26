-- Migração 23: tranca por loja dentro do banco (Row Level Security; Maratona Segurança, SE3).
-- Não muda nem apaga dado nenhum: liga a tranca e cria a regra em TODA tabela que tem loja_id.
--
-- Regra (a mesma em todas): a linha aparece, e pode ser gravada, só se
--   loja_id = a loja marcada na conexão (leo.loja)  OU  a conexão está no modo sistema (leo.modo).
-- Quem marca a conexão é o banco.py. Conexão sem marca não vê nada destas tabelas.
-- A tranca vale para o usuário do APP (leo_app, que não é dono das tabelas). O dono (quem roda as
-- migrações) passa por cima, de propósito: migração, backup e limpeza dos testes.
-- Tabela nova com loja_id precisa entrar na tranca: o teste tests/test_se3_tranca.py reprova se faltar.

CREATE OR REPLACE FUNCTION leo_pode_ver(loja BIGINT) RETURNS BOOLEAN
LANGUAGE sql STABLE PARALLEL SAFE AS $$
    SELECT COALESCE(current_setting('leo.modo', true), '') = 'sistema'
        OR (loja IS NOT NULL AND loja = NULLIF(current_setting('leo.loja', true), '')::BIGINT)
$$;

DO $$
DECLARE
    t RECORD;
BEGIN
    FOR t IN
        SELECT c.table_name
        FROM information_schema.columns c
        JOIN information_schema.tables tb ON tb.table_name = c.table_name AND tb.table_schema = c.table_schema
        WHERE c.table_schema = current_schema() AND c.column_name = 'loja_id' AND tb.table_type = 'BASE TABLE'
        ORDER BY c.table_name
    LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t.table_name);
        EXECUTE format('DROP POLICY IF EXISTS leo_por_loja ON %I', t.table_name);
        EXECUTE format('CREATE POLICY leo_por_loja ON %I USING (leo_pode_ver(loja_id)) '
                       'WITH CHECK (leo_pode_ver(loja_id))', t.table_name);
    END LOOP;
END
$$;
