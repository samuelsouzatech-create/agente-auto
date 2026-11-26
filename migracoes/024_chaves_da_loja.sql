-- Migração 24: chaves estrangeiras da loja (Maratona Segurança, SE3, item 4). Não muda nem apaga dado.
-- Em toda tabela com loja_id: loja_id aponta para uma loja que EXISTE (lojas.id). Linha de uma loja
-- que não existe passa a ser recusada pelo próprio banco.
-- DEFERRABLE INITIALLY DEFERRED: a conferência é feita no fim da transação (o reinício da demo e a
-- limpeza dos testes apagam e regravam numa transação só). Sem ON DELETE: apagar uma loja com dados
-- é recusado (hoje o Léo nunca apaga loja; ver docs/seguranca.md).
-- Antes de ligar, a migração confere: se já existe linha de loja inexistente, ela PARA e avisa
-- (nada é apagado).
DO $$
DECLARE
    t RECORD;
    orfas BIGINT;
BEGIN
    FOR t IN
        SELECT c.table_name
        FROM information_schema.columns c
        JOIN information_schema.tables tb ON tb.table_name = c.table_name AND tb.table_schema = c.table_schema
        WHERE c.table_schema = current_schema() AND c.column_name = 'loja_id' AND tb.table_type = 'BASE TABLE'
        ORDER BY c.table_name
    LOOP
        EXECUTE format('SELECT COUNT(*) FROM %I x WHERE x.loja_id IS NOT NULL AND NOT EXISTS '
                       '(SELECT 1 FROM lojas l WHERE l.id = x.loja_id)', t.table_name) INTO orfas;
        IF orfas > 0 THEN
            RAISE EXCEPTION 'A tabela % tem % linha(s) de loja que não existe. Nada foi mudado.', t.table_name, orfas;
        END IF;
        EXECUTE format('ALTER TABLE %I DROP CONSTRAINT IF EXISTS %I', t.table_name, 'fk_' || t.table_name || '_loja');
        EXECUTE format('ALTER TABLE %I ADD CONSTRAINT %I FOREIGN KEY (loja_id) REFERENCES lojas (id) '
                       'DEFERRABLE INITIALLY DEFERRED', t.table_name, 'fk_' || t.table_name || '_loja');
    END LOOP;
END
$$;
