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
