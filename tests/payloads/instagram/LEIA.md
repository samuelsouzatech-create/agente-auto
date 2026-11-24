# Payloads de exemplo do Instagram (FICTÍCIOS)

Montados no IG0 (Maratona 4) a partir do formato publicado pela Meta (links e situação de cada
campo em `docs/maratona4.md`, IG0). Nenhum veio de conta real; ids, textos e nomes são inventados.

| Arquivo | O que é | Situação do formato |
|---|---|---|
| `mensagem_texto.json` | mensagem de texto recebida no direct | confirmado (campos da documentação) |
| `mensagem_varias.json` | duas mensagens no mesmo aviso | confirmado (`messaging` é lista) |
| `eco_vendedor.json` | eco (`is_echo: true`) de resposta que o vendedor mandou pelo app | campo confirmado; "vem também quando é pelo app" **a confirmar** |
| `eco_do_leo.json` | eco da resposta do próprio Léo (o `mid` é o que o envio devolveu, `envio_ok.json`) | campo confirmado |
| `nao_suportado.json` | compartilhamento de post e reação | **a confirmar** (montado no mesmo jeito; o Léo só ignora com resposta curta) |
| `comentario_post.json` | comentário em post comum (forma com `changes[]`) | confirmado |
| `comentario_post_entry_direto.json` | o mesmo, na outra forma publicada (`field`/`value` direto no `entry`) | confirmado (a Meta publica as duas formas) |
| `comentario_anuncio.json` | comentário em anúncio pago (`ad_id`, `ad_title`, `original_media_id`) | confirmado só com login do Facebook |
| `comentario_da_propria_loja.json` | a própria conta da loja comentando (deve ser ignorado) | montado (o `from.id` é o da conta) |
| `legenda_do_post.json` | resposta de `GET /<id do post>?fields=caption` | confirmado só com login do Facebook |
| `resposta_privada_ok.json` | resposta da Meta ao mandar a mensagem privada do comentário | confirmado |
| `envio_ok.json` | resposta da Meta ao mandar mensagem no direct | confirmado (`recipient_id`, `message_id`) |
