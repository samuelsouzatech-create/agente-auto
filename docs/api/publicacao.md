# Publicar a API do painel (Marco 4)

Checklist para quando a API sair do computador e for para um servidor de verdade.

## 1. Rodar atrás do proxy (nginx), nunca exposta direto

A API conta "links errados demais" (429) por origem, isto é, pelo endereço de quem pediu.
Atrás de um proxy, todo pedido chega com o endereço do proxy. Sem a configuração abaixo,
alguém errando 10 links travaria TODOS os vendedores por 15 minutos.

Comando (o proxy na mesma máquina, 127.0.0.1):

```
uvicorn app.api_painel.main:app --host 127.0.0.1 --port 8001 --proxy-headers --forwarded-allow-ips 127.0.0.1
```

- `--forwarded-allow-ips` recebe SÓ o endereço do proxy. Nunca `*`: com `*`, qualquer pessoa
  poderia inventar o próprio endereço e escapar do limite.
- No nginx, mandar o endereço real do visitante:

```
proxy_set_header X-Forwarded-For $remote_addr;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_set_header Host $host;
```

## 2. Variáveis do .env

| Variável | Para quê |
|---|---|
| `PAINEL_ORIGEM` | Endereço do front, para o CORS (nunca `*`). |
| `PAINEL_URL` | Para onde o link de senha e o link do vendedor levam. |
| `API_PUBLICA_URL` | Endereço público da API. Sem ela, o aviso do Telegram sai sem link. |

## 3. Cookie

- Só HTTPS: o cookie `leo_sessao` é `Secure`.
- Front e API no mesmo domínio-base (ex.: `painel.loja.com` e `api.loja.com`), senão o
  navegador não manda o cookie.
- O link do vendedor usa o mesmo cookie do login: aberto no navegador onde a pessoa já está
  logada, troca a sessão completa pela de uma conversa só (lacuna 35 do contrato).
- Sessão do login: 7 dias. Sessão do link: 12 h.
