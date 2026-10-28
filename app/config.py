import os
from dotenv import load_dotenv

# Carrega as variáveis do .env uma vez, de forma centralizada.
# Na Fase 2, as chaves da Meta, Redis e PostgreSQL também virão para cá.
load_dotenv()

# Chave da API do Google Gemini
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

# Modelo de linguagem usado pelo agente
MODELO_LLM = "gemini-3.1-flash-lite"

# Configurações do modelo (centralizadas para fácil ajuste)
TEMPERATURA = 0.2
TIMEOUT = 30
MAX_RETRIES = 3

# Token de verificação do webhook do WhatsApp (uma senha que VOCÊ inventa
# e cadastra na Meta; serve para a Meta provar que o webhook é seu).
WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "leo-webhook-2026")

# --- Credenciais da Meta/WhatsApp (ficam no .env, nunca no código) ---
# Token de acesso: hoje é o temporário de 24h; depois vira o permanente.
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")

# ID do número de teste da Meta (aquele que você copiou no painel).
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")

# Chave Secreta do App (App Secret). Valida que cada POST do webhook veio MESMO
# da Meta (assinatura X-Hub-Signature-256). Falha FECHADA: se ficar vazio,
# o webhook REJEITA tudo. Não existe modo "sem validação".
WHATSAPP_APP_SECRET = os.getenv("WHATSAPP_APP_SECRET", "")

# Versão da API da Meta (Graph API). v21.0 é estável em 2026.
WHATSAPP_API_VERSION = "v21.0"

# --- Credenciais do Telegram (ficam no .env, nunca no código) ---
# Token do bot criado no @BotFather. É uma senha: controla o bot inteiro.
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")

# --- Bot único de AVISOS (Bloco 7B): fala só com a equipe e com o operador ---
TELEGRAM_AVISOS_TOKEN = os.getenv("TELEGRAM_AVISOS_TOKEN", "")

# Seu chat_id: recebe os alertas de gasto (é do operador, não da loja).
TELEGRAM_AVISOS_OPERADOR_CHAT_ID = os.getenv("TELEGRAM_AVISOS_OPERADOR_CHAT_ID", "")

