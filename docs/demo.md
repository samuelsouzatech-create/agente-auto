# Como abrir e mostrar a demo do Léo

Tudo roda no seu computador. Nada sai para WhatsApp, Telegram ou cliente de verdade: a loja de
demonstração ("Recife Seminovos Demo") é fictícia e só usa o simulador.

## 0. Ligar tudo (um comando só)

Desde a Maratona Docker (DK1) **todas as peças rodam no Docker**: banco, Redis, webhook, API do
painel, relógio, painel do operador, simulador, a tela nova e o porteiro HTTPS. Abra o
**Docker Desktop** e espere ele dizer que está ligado. Depois, no PowerShell, na pasta do
projeto (`C:\Users\Samuel\agente-auto`):

```powershell
docker compose up -d
```

Na primeira vez demora (uns 8 minutos: ele monta as imagens). Depois é questão de segundos.
Para conferir: `docker compose ps` (todas as peças "healthy"). Para desligar no fim do dia:
`docker compose stop` (os dados ficam guardados nos volumes).

Depois de mudar o código do Léo ou da tela: `docker compose up -d --build`.

### Endereços (só neste computador)

| O quê | Endereço |
|---|---|
| Painel novo da loja (celular e computador) | https://localhost |
| Painel do operador | https://localhost:8502 |
| Simulador (conversa com cara de WhatsApp; usa a IA de verdade) | https://localhost:8501 |

O simulador só sobe com `COMPOSE_PROFILES=demo` no `.env` (já está assim neste computador).

**Aviso de "conexão não particular" no navegador:** o certificado é feito pelo próprio porteiro,
só para este computador. Para o navegador confiar nele (uma vez só):

```powershell
docker compose cp porteiro:/data/caddy/pki/authorities/local/root.crt "$env:TEMP\leo-local.crt"
certutil -user -addstore Root "$env:TEMP\leo-local.crt"
```

Feche e abra o navegador. (Sem isso, dá para clicar em "Avançado" e "Continuar".)

## 1. Preparar a demo (uma vez, ou quando quiser começar do zero)

Com tudo ligado (passo 0), se a loja de demonstração ainda não existe:

```powershell
docker compose exec api-painel python scripts/criar_loja_demo.py --sem-indexar
docker compose exec api-painel python scripts/criar_usuarios_demo.py
```

O primeiro cria a loja com 18 carros (fotos ilustrativas), as políticas (troca, garantia,
financiamento, test-drive), a equipe fictícia e 30 dias de histórico. O segundo mostra as
**senhas** do Dono Demo, do Gerente Demo e do Vendedor Demo (anote na hora: elas não ficam
gravadas em lugar nenhum). Sem `--sem-indexar`, o primeiro também monta a base de conhecimento,
o que usa o Gemini.

Se você tinha fotos e base de conhecimento de antes do Docker (pastas `fotos_deposito` e
`chroma_db` do projeto), copie uma vez para dentro do Docker: `docs/docker.md`, DK1,
"Trazer os dados de antes".

## 2. Abrir as telas

Nada de abrir um PowerShell para cada tela: o passo 0 já ligou tudo.

### Painel novo da loja (https://localhost)

Entre com o **Dono Demo** (`dono.loja<N>@demo.exemplo`, onde `<N>` é o número da loja demo) e a
senha do passo 1 (ou do passo 4). Há também o **Gerente Demo** e o **Vendedor Demo**.

O que dá para mostrar no painel novo:
- a luz do topo fica verde ("Léo atendendo"): na demo, o simulador conta como canal;
- **Atender**: quem chamou vendedor no simulador aparece em "Esperando vendedor". Toque no nome,
  **Assumir** e escreva uma resposta: em até 4 segundos ela aparece no simulador, num balão
  azul com o nome do vendedor. Nada é enviado a ninguém;
- **Registrar venda** escolhendo o carro; **Leads**; **Resultado** com as setas de período;
- **Acompanhamento**: as mensagens automáticas e o botão Pausar;
- **Estoque** com as fotos ilustrativas; dá para editar um carro e salvar.

### Painel do operador (https://localhost:8502)

Visão geral, Custos e preços e, por loja: Resumo, Configuração, Mensagens automáticas, Base de
clientes, Recados e Registro. Sem login: só abre neste computador.

### Simulador (https://localhost:8501)

A conversa com o Léo (a loja demo já vem escolhida na barra da esquerda). **Usa o Gemini**
(precisa de crédito).

## 3. O que mostrar em cada tela

1. **Simulador**:
   - escreva "oi, vocês têm Corolla?" e depois "me manda uma foto dele": o Léo responde com preço e foto;
   - "quanto fica a parcela do Corolla em 48 vezes com 30 mil de entrada?": ele simula e avisa que é estimativa;
   - "faz por 115 mil à vista?": ele não promete desconto e chama um vendedor. À direita aparece
     **"O vendedor recebeu"** com o motivo e o resumo (é o aviso que iria para o celular do vendedor).
2. **Painel novo, Atender:** o chamado do desconto aparece em "Esperando vendedor". Assuma a
   conversa e volte ao simulador: o Léo fica em silêncio.
3. **Painel do operador, Configuração:** troque o tom (ex.: "formal") e salve. No simulador, clique em
   "Nova conversa" e repita uma pergunta: a resposta muda de jeito.
4. **Painel novo, Resultado:** conversas do mês, fora do horário, tempo de resposta, vendas e custo.
5. **Painel novo, Acompanhamento:** as mensagens automáticas em modo de teste e o botão Pausar.

## 4. Reiniciar a demo (antes de cada reunião)

Pelo painel do operador: escolha a loja "Recife Seminovos Demo", tela **Resumo**, marque
"Entendi..." e clique em **Reiniciar demo**. Ou pelo PowerShell:

```powershell
docker compose exec api-painel python scripts/reiniciar_demo.py --sem-indexar
```

Só a loja de demonstração é apagada e recriada. Qualquer outra loja é recusada.

O script também recria o Dono Demo, o Gerente Demo e o Vendedor Demo do painel novo e mostra as
**senhas novas** no PowerShell (anote na hora). Se você reiniciar pelo painel do operador, rode
depois `docker compose exec api-painel python scripts/criar_usuarios_demo.py` para ter as pessoas
de teste de novo.

## 5. Se algo der errado

- "Nenhuma loja cadastrada": rode o passo 1.
- Uma peça não fica "healthy" em `docker compose ps`: veja o motivo com
  `docker compose logs <peça>` (ex.: `docker compose logs api-painel`) e religue com
  `docker compose up -d`.
- "coloque POSTGRES_SENHA no .env" ou "coloque REDIS_SENHA no .env": falta a linha no `.env`
  (veja `.env.example`).
- https://localhost não abre: o Docker Desktop está ligado? Outro programa usa a porta 443? (Se
  usar, ponha `PORTEIRO_PORTA=8443` no `.env`, rode `docker compose up -d` e abra
  https://localhost:8443.)
- O Léo não responde no simulador: confira se o `.env` do projeto tem a chave do Gemini (não
  mostre a chave a ninguém) e se há crédito.
- Para desligar tudo: `docker compose stop`.
- Grave um vídeo de reserva da demo completa, para o caso de o computador falhar na hora.
