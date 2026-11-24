# Porteiro HTTPS do Léo (DK1): Caddy com a tela leo-painel-web já compilada dentro.
# A tela vem do outro repositório pelo contexto "tela" (docker-compose.yml, TELA_PASTA).

# --- Etapa 1: compila a tela (React) ---
FROM node:22.21.1-alpine AS compilar
WORKDIR /tela
COPY --from=tela package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY --from=tela index.html tsconfig.json vite.config.ts tailwind.config.ts postcss.config.js ./
COPY --from=tela public ./public
COPY --from=tela src ./src
COPY --from=tela mocks ./mocks
COPY --from=tela contrato ./contrato
# A tela fala com a API pelo mesmo endereço (o porteiro manda /api para a API do painel).
ENV VITE_API_URL=/api/v1
RUN npm run build

# --- Etapa 2: o porteiro (Caddy) com a tela pronta ---
FROM caddy:2.10.2-alpine
COPY docker/Caddyfile /etc/caddy/Caddyfile
COPY --from=compilar /tela/dist /srv/tela
