import os
from dotenv import load_dotenv
from typing import Annotated
from langchain_core.tools import tool, InjectedToolArg
from banco import conectar
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_chroma import Chroma

# Garante que a chave do .env esteja carregada antes de qualquer uso da API
load_dotenv()


def formatar_brl(valor: float) -> str:
    """Formata um número no padrão de moeda brasileiro. Ex: 98000.0 -> 98.000,00"""
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


@tool
def consultar_estoque(marca: str = "", modelo: str = "", cor: str = "",
                      cambio: str = "", preco_max: float = 0) -> str:
    """Consulta os carros DISPONÍVEIS no estoque da loja.
    Use esta ferramenta sempre que o cliente perguntar sobre carros,
    modelos, preços ou disponibilidade. NUNCA invente carros ou preços.

    Parâmetros (todos opcionais — preencha só os que o cliente mencionou):
    - marca: ex. "Honda", "Fiat"
    - modelo: ex. "Civic", "Onix"
    - cor: ex. "Branco", "Preto"
    - cambio: "Automático" ou "Manual"
    - preco_max: preço máximo que o cliente quer pagar (ex. 80000)
    """
    conexao = conectar()
    cursor = conexao.cursor()

    # Começa buscando só carros disponíveis (nunca vendidos)
    sql = "SELECT * FROM estoque WHERE status = 'disponivel'"
    parametros = []

    # Adiciona filtros só para o que o cliente mencionou
    if marca:
        sql += " AND marca LIKE ?"
        parametros.append(f"%{marca}%")
    if modelo:
        sql += " AND modelo LIKE ?"
        parametros.append(f"%{modelo}%")
    if cor:
        sql += " AND cor LIKE ?"
        parametros.append(f"%{cor}%")
    if cambio:
        sql += " AND cambio LIKE ?"
        parametros.append(f"%{cambio}%")
    if preco_max and preco_max > 0:
        sql += " AND preco <= ?"
        parametros.append(preco_max)

    cursor.execute(sql, parametros)
    carros = cursor.fetchall()
    conexao.close()

    if not carros:
        return "Nenhum carro disponível encontrado com esses critérios."

    # Monta um texto limpo com os resultados para o agente ler
    linhas = []
    for c in carros:
        km_formatado = f"{c['km']:,}".replace(",", ".")
        linhas.append(
            f"ID {c['id']}: {c['marca']} {c['modelo']} {c['ano']}, "
            f"{c['cor']}, {c['cambio']}, {km_formatado} km, "
            f"{formatar_brl(c['preco'])}"
        )
    return "Carros disponíveis:\n" + "\n".join(linhas)


@tool
def detalhes_veiculo(id_veiculo: int) -> str:
    """Retorna a ficha completa de um carro específico pelo seu ID.
    Use quando o cliente demonstrar interesse em um carro específico
    que já apareceu na conversa e quiser saber mais detalhes.
    """
    conexao = conectar()
    cursor = conexao.cursor()
    cursor.execute(
        "SELECT * FROM estoque WHERE id = ? AND status = 'disponivel'",
        (id_veiculo,)
    )
    c = cursor.fetchone()
    conexao.close()

    if not c:
        return "Carro não encontrado ou não está mais disponível."

    km_formatado = f"{c['km']:,}".replace(",", ".")
    return (
        f"{c['marca']} {c['modelo']} {c['ano']}\n"
        f"Cor: {c['cor']}\n"
        f"Câmbio: {c['cambio']}\n"
        f"Quilometragem: {km_formatado} km\n"
        f"Preço: {formatar_brl(c['preco'])}"
    )


@tool
def simular_financiamento(valor_carro: float, entrada: float, parcelas: int) -> str:
    """Faz uma ESTIMATIVA de financiamento. Deixe claro ao cliente que é
    apenas uma simulação aproximada, e que as condições reais dependem de
    análise de crédito feita por um vendedor.

    Parâmetros:
    - valor_carro: preço do carro
    - entrada: valor de entrada que o cliente pode dar
    - parcelas: número de parcelas (ex: 48)
    """
    if parcelas < 1 or valor_carro <= 0:
        return "Não consigo simular: informe um valor de carro válido e ao menos 1 parcela."
    if entrada >= valor_carro:
        return "A entrada cobre o valor total. Não é necessário financiamento."

    valor_financiado = valor_carro - entrada
    taxa_mensal = 0.019  # 1,9% ao mês (taxa de exemplo; configurável por loja)

    # Fórmula de parcela fixa (Tabela Price)
    fator = (1 + taxa_mensal) ** parcelas
    parcela = valor_financiado * (taxa_mensal * fator) / (fator - 1)

    return (
        f"Estimativa (não é valor definitivo, depende de análise de crédito):\n"
        f"Valor financiado: {formatar_brl(valor_financiado)}\n"
        f"{parcelas}x de aproximadamente {formatar_brl(parcela)}"
    )


@tool
def registrar_troca(modelo: str, ano: int, km: int, estado: str,
                    lead_id: Annotated[str, InjectedToolArg] = "") -> str:
    """Registra o carro que o cliente quer dar na troca. NÃO dê valor de
    avaliação — isso é feito por um vendedor presencialmente. Apenas colete
    e confirme os dados.

    Parâmetros:
    - modelo: ex. "Gol 1.0"
    - ano: ano do carro
    - km: quilometragem
    - estado: descrição geral informada pelo cliente
    """
    conexao = conectar()
    cursor = conexao.cursor()
    cursor.execute("""
        INSERT INTO trocas (lead_id, modelo, ano, km, estado)
        VALUES (?, ?, ?, ?, ?)
    """, (lead_id, modelo, ano, km, estado))
    conexao.commit()
    conexao.close()
    km_formatado = f"{km:,}".replace(",", ".")
    return (
        f"Troca registrada: {modelo} {ano}, {km_formatado} km, estado: {estado}. "
        "A avaliação com valor é feita presencialmente por um vendedor."
    )


@tool
def agendar_visita(nome_cliente: str, tipo: str, data_hora: str,
                  lead_id: Annotated[str, InjectedToolArg] = "") -> str:
    """Agenda uma visita, test-drive ou ligação com vendedor.

    Parâmetros:
    - nome_cliente: nome de quem está agendando
    - tipo: "visita", "test-drive" ou "ligacao"
    - data_hora: data e hora combinadas (ex: "sábado 10h", "12/10 às 15h")
    """
    conexao = conectar()
    cursor = conexao.cursor()
    cursor.execute("""
        INSERT INTO agendamentos (lead_id, nome_cliente, tipo, data_hora)
        VALUES (?, ?, ?, ?)
    """, (lead_id, nome_cliente, tipo, data_hora))
    conexao.commit()
    conexao.close()
    return f"Agendamento confirmado: {tipo} para {nome_cliente} em {data_hora}."


@tool
def registrar_lead(nome: str, interesse: str, forma_pagamento: str = "",
                   tem_troca: str = "", prazo: str = "",
                   lead_id: Annotated[str, InjectedToolArg] = "") -> str:
    """Registra/atualiza os dados de qualificação do lead ao longo da conversa.
    Use quando tiver coletado informações relevantes do cliente. Pode ser
    chamada várias vezes na mesma conversa — os dados vão sendo completados.

    Parâmetros:
    - nome: nome do cliente
    - interesse: o que ele procura (modelo, faixa de preço)
    - forma_pagamento: "à vista" ou "financiado" (se souber)
    - tem_troca: "sim" ou "não" (se souber)
    - prazo: urgência/quando quer resolver (se souber)
    """
    conexao = conectar()
    cursor = conexao.cursor()

    # Verifica se já existe um lead para esta conversa
    cursor.execute("SELECT id FROM leads WHERE lead_id = ?", (lead_id,))
    existente = cursor.fetchone()

    if existente:
        # Já existe: ATUALIZA só os campos que vieram preenchidos
        cursor.execute("""
            UPDATE leads SET
                nome = COALESCE(NULLIF(?, ''), nome),
                interesse = COALESCE(NULLIF(?, ''), interesse),
                forma_pagamento = COALESCE(NULLIF(?, ''), forma_pagamento),
                tem_troca = COALESCE(NULLIF(?, ''), tem_troca),
                prazo = COALESCE(NULLIF(?, ''), prazo),
                atualizado_em = CURRENT_TIMESTAMP
            WHERE lead_id = ?
        """, (nome, interesse, forma_pagamento, tem_troca, prazo, lead_id))
    else:
        # Não existe: INSERE um novo
        cursor.execute("""
            INSERT INTO leads (lead_id, nome, interesse, forma_pagamento, tem_troca, prazo)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (lead_id, nome, interesse, forma_pagamento, tem_troca, prazo))

    conexao.commit()
    conexao.close()
    return f"Lead registrado/atualizado: {nome} — {interesse}."


@tool
def acionar_handoff(motivo: str, resumo: str,
                   lead_id: Annotated[str, InjectedToolArg] = "") -> str:
    """Aciona a passagem da conversa para um vendedor humano (handoff).
    Use quando: o cliente pedir para falar com uma pessoa; pedir desconto
    ou negociar preço; pedir aprovação de crédito; houver reclamação;
    ou qualquer assunto que você não pode resolver sozinho.

    Parâmetros:
    - motivo: por que está passando (ex: "cliente pediu desconto")
    - resumo: resumo do lead e da conversa para o vendedor
    """
    conexao = conectar()
    cursor = conexao.cursor()
    cursor.execute("""
        INSERT INTO handoffs (lead_id, motivo, resumo, estado)
        VALUES (?, ?, ?, 'aguardando_humano')
    """, (lead_id, motivo, resumo))
    conexao.commit()
    conexao.close()
    return (
        "Handoff acionado. Avise o cliente que um vendedor vai continuar "
        "o atendimento em instantes."
    )


# --- RAG: acesso ao conhecimento (inicialização preguiçosa) ---
# Em vez de criar o Chroma no import (o que exigia a chave já carregada e
# conectava mesmo sem uso), criamos só na primeira vez que a tool é chamada.
_banco_conhecimento = None


def _get_banco_conhecimento():
    """Cria a conexão com o Chroma uma única vez, sob demanda (lazy)."""
    global _banco_conhecimento
    if _banco_conhecimento is None:
        embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")
        _banco_conhecimento = Chroma(
            persist_directory="chroma_db",
            embedding_function=embeddings,
        )
    return _banco_conhecimento


@tool
def buscar_conhecimento(pergunta: str) -> str:
    """Busca informações sobre as POLÍTICAS da loja: formas de pagamento,
    regras de financiamento, regras de troca, garantia, test-drive e horário
    de atendimento. Use esta ferramenta sempre que o cliente perguntar sobre
    COMO a loja funciona (e NÃO sobre quais carros existem — para carros, use
    consultar_estoque).

    Parâmetros:
    - pergunta: a dúvida do cliente, em linguagem natural
    """
    banco = _get_banco_conhecimento()
    resultados = banco.similarity_search(pergunta, k=3)
    if not resultados:
        return "Não encontrei essa informação nas políticas da loja."
    trechos = [doc.page_content for doc in resultados]
    return "\n\n---\n\n".join(trechos)



