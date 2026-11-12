"""API do painel do cliente (C2 do Plano Mestre). Aplicação separada do webhook,
porta 8001: uvicorn app.api_painel.main:app --host 127.0.0.1 --port 8001
Camada fina sobre app/: nenhuma regra de negócio mora aqui."""
