# O9 — Por que o Conhecimento só valia depois de reiniciar

## Causa (provada)
A ferramenta buscar_conhecimento abria o índice (Chroma) uma vez por processo e guardava a cópia. O painel e o bot são processos diferentes: o painel gravava no disco, mas o bot continuava com a cópia antiga até reiniciar. Às vezes ainda dava erro ("Error finding id").

## Experimento (Windows 10, Python 3.13.9, chromadb 1.5.9, langchain-chroma 1.1.0)
Foram dois processos separados abertos ao mesmo tempo: o "bot", que busca, e o "painel", que salva com salvar_documento e apaga com apagar_documento. Testou-se documento novo, editado e apagado, com duas lojas. Os embeddings eram falsos, mas o Chroma e o código eram os de verdade.

| Rodada | Resultado |
|---|---|
| Código de hoje | FALHOU (9 de 12) |
| Reabrir quando chroma.sqlite3 muda, sem limpar o cache | FALHOU (9 de 12) |
| Reabrir quando chroma.sqlite3 muda, limpando o cache | PASSOU (12 de 12) |
| Reabrir quando qualquer arquivo da pasta muda, limpando o cache | PASSOU (12 de 12) |

## Decisão
Resolver de vez, com a saída (a) aprovada pelo analista. Antes de cada busca, a ferramenta confere a data e o tamanho de chroma.sqlite3 (e do -wal, se existir). Se mudou, descarta a cópia, limpa o cache interno do Chroma e reabre. Se a busca der erro, reabre e tenta uma vez mais. O botão "Publicar" não foi feito. Fica no lugar dele "Atualizar a consulta do assistente", que refaz o índice só daquela loja.

## Limites
O teste à mão com o bot real e o Gemini real fica para o fim do S4c. A limpeza do cache vale para o processo inteiro; com muitas buscas simultâneas no mesmo processo, uma pode precisar da nova tentativa. A troca para PostgreSQL ou para um servidor do Chroma é assunto da Etapa 5.
