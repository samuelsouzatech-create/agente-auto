# Roteiros de bancada do Instagram (BA2, Maratona 5)

Rodam pelo **webhook de verdade** (`POST /webhook/instagram`, e `POST /webhook` na passagem para o
WhatsApp), com o Gemini real e o **servidor falso da Meta** (`tests/meta_falsa.py`) no lugar da Meta:

    .venv-teste\Scripts\python scripts\bancada_instagram.py
    .venv-teste\Scripts\python scripts\bancada_instagram.py --roteiro ig_pede_whatsapp

Ficam FORA de `bancada/roteiros/` de propósito: a bancada de sempre roda pelo canal simulador e não
sabe fazer comentário, eco de vendedor nem passagem para o WhatsApp. Relatório:
`logs/bancada/instagram_<data>.md`. O formato está no topo de `scripts/bancada_instagram.py`.
Escritos no IG3 (Maratona 4, não rodados) e refeitos no BA2: `ig_01` a `ig_04` vêm de lá; `ig_05`
(mesmo cliente nos dois canais) e `ig_06` (legenda com preço diferente do estoque) são novos.
