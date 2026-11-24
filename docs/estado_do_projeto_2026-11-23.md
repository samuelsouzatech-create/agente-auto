# Estado do projeto Léo — 23/11/2026

Resumo para quem chega agora (analista, Samuel ou o próximo bloco). O anterior é
`estado_do_projeto_2026-11-22.md` (na raiz). Diário desta maratona: `docs/postgres.md`.

## Onde estamos

- **agente-auto, main:** `8daf273` (Merge F2). Tag: **`agente-fotos`**.
- **leo-painel-web, main:** `ffea876` (Merge P7). Tag: **`painel-v1.2`**.
- **Suíte offline:** 2.919 testes passando na main (suíte inteira, 17 min).
- **Banco:** SQLite. Migrações 1 a 17, 19 e 20 (a 18 nunca existiu e não será usada); a 21 está
  reservada ao Instagram. A partir da Maratona Postgres, o banco passa a ser **PostgreSQL 17**.
- **Contrato da API do painel:** versão 1.2.0 (`docs/api/openapi.yaml`, 32 operações, 85 mocks).

## O que está pronto

| Parte | Situação |
|-------|----------|
| Núcleo do Léo (agente, guardas, jobs, régua, handoff) | pronto; Fase Cérebro fechada com ressalva (21/11) |
| Remarketing, pós-venda, reativação da base | pronto, em modo de teste por padrão; **E2-1 limite diário da reativação** feito no PG0 |
| API do painel (FastAPI, porta 8001, `/api/v1`) | pronta: login, sessão por cookie, CSRF, papéis, conversas, estoque, acompanhamento, resultado, configuração |
| Painel do cliente novo (`leo-painel-web`, React) | pronto: login, conversas, estoque com fotos, acompanhamento, resultado, trocar senha |
| Fotos do estoque | um caminho só: preparo único (sem GPS, reduzida, por loja), depósito local ou nuvem (S3), envio de arquivo pelo painel |
| Demo | loja "Recife Seminovos Demo", reiniciar pelo script ou pelo botão do operador; pessoas de teste com senha nova a cada reinício |
| Painel do operador (Streamlit) | pronto, só no computador local, **sem login** (revisão #6) |
| Painel do cliente antigo (Streamlit, `painel.py`) | ainda existe; vai ser aposentado |
| Login | 5 erros por e-mail + origem; 20 por origem (revisão #5, parte média) |

## O que falta (em ordem)

1. **Postgres** (esta maratona): PG0 documentos e E2-1; PG1 banco PostgreSQL com uma camada única de
   conexão; PG2 memória das conversas no Postgres e importação do `loja.db`; PG3 teste de carga
   com 10 lojas.
2. **Docker e aposentar o painel Streamlit do cliente:** a aplicação inteira em contêineres
   (API do painel, webhook, relógio dos jobs, Redis, Postgres); o painel do cliente passa a ser só
   o `leo-painel-web`.
3. **Segurança:** login no painel do operador (revisão #6), conexão do link de foto no IP
   conferido, revisão das pendências de `docs/revisao_geral.md` (#16 a #19, #30, #31).
4. **Hospedagem com R2:** servidor de verdade, depósito de fotos na nuvem (Cloudflare R2, com a
   mesma tomada S3 já pronta), endereço https público para o WhatsApp receber as fotos.
5. **Teste ponta a ponta:** uma loja de teste do começo ao fim no servidor (canal real só com
   autorização do Samuel).

## Precisa de decisão do Samuel (continua de 22/11)

- `WHATSAPP_VERIFY_TOKEN` no `.env` antes de mexer no webhook da Meta.
- Tirar a ressalva da Fase Cérebro quando houver crédito no Gemini (bancada 2 vezes).
- **A8:** o número do limite diário da reativação (o padrão ficou 30, baixo de propósito).
- Depósito na nuvem: escolher o provedor (o plano diz R2) e criar o "balde" quando for hospedar.
