# Como abrir e mostrar a demo do Léo

Tudo roda no seu computador. Nada sai para WhatsApp, Telegram ou cliente de verdade: a loja de
demonstração ("Recife Seminovos Demo") é fictícia e só usa o simulador.

## 1. Preparar (uma vez, ou quando quiser começar do zero)

Abra o PowerShell na pasta do projeto (`C:\Users\Samuel\agente-auto`) e rode, nesta ordem:

```powershell
.venv-teste\Scripts\python scripts\criar_loja_demo.py
```

Ele cria a loja com 18 carros (fotos ilustrativas), as políticas (troca, garantia, financiamento,
test-drive), a equipe fictícia e 30 dias de histórico. No fim aparece "Loja de demonstração pronta".

## 2. Abrir as telas (cada uma num PowerShell separado)

Simulador (a conversa com cara de WhatsApp):

```powershell
.venv-teste\Scripts\streamlit run app.py
```

Painel do operador (Resumo, Configuração, Registro):

```powershell
.venv-teste\Scripts\streamlit run operador.py --server.port 8502
```

Painel da loja (Fila de atendimento, Conversas, Resultados, Retomadas e pós-venda):

```powershell
.venv-teste\Scripts\streamlit run painel.py --server.port 8503
```

O navegador abre sozinho. Se não abrir, use o endereço que aparece no PowerShell
(ex.: http://localhost:8501).

### Painel novo do cliente (celular e computador)

É a tela nova (repositório `leo-painel-web`), ligada na API do painel. Precisa de dois PowerShell.

1. API do painel, na pasta `C:\Users\Samuel\agente-auto`:

   ```powershell
   .venv-teste\Scripts\python -m uvicorn app.api_painel.main:app --host 127.0.0.1 --port 8001
   ```

2. Tela, na pasta `C:\Users\Samuel\leo-painel-web` (só na primeira vez: `npm ci` e crie o
   arquivo `.env.local` com a linha `VITE_API_URL=/api/v1`):

   ```powershell
   npm run dev
   ```

   Abra http://localhost:5173 e entre com o **Dono Demo** (`dono.loja<N>@demo.exemplo`, onde
   `<N>` é o número da loja demo). A senha aparece no PowerShell quando você roda
   `scripts\criar_usuarios_demo.py` ou `scripts\reiniciar_demo.py` (ela não fica gravada em
   lugar nenhum). Há também o **Gerente Demo** e o **Vendedor Demo**.

O que dá para mostrar no painel novo:
- a luz do topo fica verde ("Léo atendendo"): na demo, o simulador conta como canal;
- **Atender**: quem chamou vendedor no simulador aparece em "Esperando vendedor". Toque no nome,
  **Assumir** e escreva uma resposta: em até 4 segundos ela aparece no simulador, num balão
  azul com o nome do vendedor. Nada é enviado a ninguém;
- **Registrar venda** escolhendo o carro; **Leads**; **Resultado** com as setas de período;
- **Estoque** com as fotos ilustrativas; dá para editar um carro e salvar.

## 3. O que mostrar em cada tela

1. **Simulador** (a loja demo já vem escolhida na barra da esquerda):
   - escreva "oi, vocês têm Corolla?" e depois "me manda uma foto dele": o Léo responde com preço e foto;
   - "quanto fica a parcela do Corolla em 48 vezes com 30 mil de entrada?": ele simula e avisa que é estimativa;
   - "faz por 115 mil à vista?": ele não promete desconto e chama um vendedor. À direita aparece
     **"O vendedor recebeu"** com o motivo e o resumo (é o aviso que iria para o celular do vendedor).
2. **Painel da loja, Fila de atendimento:** o chamado do desconto aparece. Assuma a conversa e volte ao
   simulador: o Léo fica em silêncio.
3. **Painel do operador, Configuração:** troque o tom (ex.: "formal") e salve. No simulador, clique em
   "Nova conversa" e repita uma pergunta: a resposta muda de jeito.
4. **Painel da loja, Resultados:** conversas do mês, fora do horário, tempo de resposta, vendas e custo.
5. **Painel da loja, Retomadas e pós-venda:** as mensagens automáticas em modo de teste e o botão Pausar.

## 4. Reiniciar a demo (antes de cada reunião)

Pelo painel do operador: escolha a loja "Recife Seminovos Demo", tela **Resumo**, marque
"Entendi..." e clique em **Reiniciar demo**. Ou pelo PowerShell:

```powershell
.venv-teste\Scripts\python scripts\reiniciar_demo.py
```

Só a loja de demonstração é apagada e recriada. Qualquer outra loja é recusada.

O script também recria o Dono Demo, o Gerente Demo e o Vendedor Demo do painel novo e mostra as
**senhas novas** no PowerShell (anote na hora). Se você reiniciar pelo painel do operador, rode
depois `.venv-teste\Scripts\python scripts\criar_usuarios_demo.py` para ter as pessoas de teste de novo.

## 5. Se algo der errado

- "Nenhuma loja cadastrada": rode o passo 1.
- O Léo não responde: confira se o `.env` do projeto tem a chave do Gemini (não mostre a chave a ninguém).
- Para fechar uma tela: no PowerShell dela, aperte Ctrl+C.
- Grave um vídeo de reserva da demo completa, para o caso de o computador falhar na hora.
