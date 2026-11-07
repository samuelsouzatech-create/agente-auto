"""
Limites dos alertas da Visão geral (S9 da Fase 3). Todos os valores num lugar só.
Mudar um número aqui muda a tela; nenhum outro arquivo repete estes valores
(o Resumo da loja também lê DIAS_SEM_VENDA daqui).

Decisões do S9 (analista, 05/11/2026): 1A, 2A, 3A, 4A, 5A, 6A, 7A, 8A, 9A, 10A, 11A.
O prazo do "cliente esperando" não fica aqui: é o handoff.gestor_min de cada
loja (Configuração), o mesmo do aviso ao gerente (decisão 6A).
"""

# Relógio (1A): segundos sem giro para ficar amarelo e vermelho.
# "Parado" (Ctrl+C) fica vermelho na hora, sem esperar estes tempos.
RELOGIO_AMARELO_S = 60
RELOGIO_VERMELHO_S = 120

# Limite de envios do mês (3A): 80% amarelo, 100% vermelho.
# NÃO voltar para 90%. O 90% era do documento "Painel do operador" (31/10),
# substituído pelo Plano Mestre; o analista confirmou 80/100 na decisão 3A.
LIMITE_AMARELO = 0.80
LIMITE_VERMELHO = 1.00

# IA na última hora (4A): tempo MÉDIO das respostas e erros contados à parte.
IA_JANELA_MIN = 60
IA_LENTA_AMARELO_MS = 15_000
IA_LENTA_VERMELHO_MS = 30_000
IA_ERROS_AMARELO = 1
IA_ERROS_VERMELHO = 3

# Canal sem mensagens (5A): comparado com o ritmo da PRÓPRIA loja.
# Só canal com pelo menos CANAL_MIN_MENSAGENS mensagens de cliente nos últimos
# CANAL_JANELA_DIAS dias; abaixo disso a tabela mostra "poucos dados".
CANAL_JANELA_DIAS = 14
CANAL_MIN_MENSAGENS = 10
CANAL_VEZES_A_MEDIA = 5
CANAL_MINIMO_H = 18

# Mensagem de cliente real recusada em loja Em teste: janela de horas.
RECUSA_JANELA_H = 24

# Loja No ar sem venda registrada (mesmo valor do Resumo da loja).
DIAS_SEM_VENDA = 14

# Tela (10A): cache curto por loja e atualização automática.
CACHE_S = 25
ATUALIZAR_S = 30
