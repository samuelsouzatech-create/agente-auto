"""
CRUD de estoque (Fase 3 - Bloco 5; caminho único de venda no P2; Registro no S4c).

Regra do P2: nenhuma função deste arquivo coloca um carro como 'vendido'.
A venda só acontece por app/vendas.py:registrar_venda. Um carro já vendido
também não volta para a oferta por aqui.

S4c: adicionar_carro e atualizar_carro exigem ator e vão para o Registro na
MESMA transação (cadastrar_carro e alterar_carro; alvo "carro:{id}").
atualizar_carro aceita 'esperado' (os valores que a tela mostrou): se o carro
mudou desde então, CarroMudou e nada é gravado. Salvar sem mudar nada não grava.
marcar_status não mudou (fora do S4c).
"""
from banco import conectar

OPCOES_CAMBIO = ["Automático", "Manual"]
# 'vendido' não entra aqui de propósito: só registrar_venda grava 'vendido'.
OPCOES_STATUS = ["disponivel", "reservado", "indisponivel"]
VENDIDO = "vendido"
CAMPOS_DO_CARRO = ("marca", "modelo", "ano", "km", "cor", "cambio", "preco", "status", "fotos")

MENSAGEM_USE_VENDA = ("Para vender um carro, use \"Registrar venda\" na conversa do cliente. "
                      "Assim a venda, o resultado e o pós-venda ficam registrados juntos.")
MENSAGEM_JA_VENDIDO = "Este carro já foi vendido. A situação dele não muda por aqui."
MENSAGEM_STATUS_INVALIDO = "Situação inválida. Escolha Disponível, Reservado ou Indisponível."


class StatusInvalido(ValueError):
    """Situação que o estoque não aceita (ex.: 'vendido' fora do Registrar venda)."""


class CarroMudou(ValueError):
    """Outra pessoa mudou este carro enquanto a tela estava aberta (S4c)."""


def _validar_status(status):
    if status == VENDIDO:
        raise StatusInvalido(MENSAGEM_USE_VENDA)
    if status not in OPCOES_STATUS:
        raise StatusInvalido(MENSAGEM_STATUS_INVALIDO)


def _status_atual(cursor, carro_id, loja_id):
    cursor.execute("SELECT status FROM estoque WHERE id = ? AND loja_id = ?", (carro_id, loja_id))
    linha = cursor.fetchone()
    return linha["status"] if linha else None


def valores_do_carro(carro) -> dict:
    """Os campos editáveis do carro (fotos vazias viram "")."""
    return {c: ((carro[c] or "") if c == "fotos" else carro[c]) for c in CAMPOS_DO_CARRO}


def listar_estoque(loja_id, incluir_vendidos=True):
    """Lista os carros do estoque. Por padrão traz todos; se
    incluir_vendidos=False, traz só os que não estão vendidos."""
    conexao = conectar()
    cursor = conexao.cursor()
    if incluir_vendidos:
        cursor.execute("SELECT * FROM estoque WHERE loja_id = ? ORDER BY id ASC", (loja_id,))
    else:
        cursor.execute(
            "SELECT * FROM estoque WHERE loja_id = ? AND status != 'vendido' ORDER BY id ASC",
            (loja_id,))
    linhas = cursor.fetchall()
    conexao.close()
    return [dict(linha) for linha in linhas]


def buscar_carro(carro_id, loja_id):
    """Retorna um carro pelo id, ou None se não existir."""
    conexao = conectar()
    cursor = conexao.cursor()
    cursor.execute("SELECT * FROM estoque WHERE id = ? AND loja_id = ?", (carro_id, loja_id))
    linha = cursor.fetchone()
    conexao.close()
    return dict(linha) if linha else None


def adicionar_carro(marca, modelo, ano, km, cor, cambio, preco,
                    status="disponivel", fotos="", *, loja_id):
    """Cadastra um carro novo. Retorna o id gerado.
    Carro novo nunca nasce 'vendido' (regra do P2)."""
    _validar_status(status)
    from app.registro import conferir_ator, registrar   # aqui dentro: evita import circular
    conferir_ator(loja_id)
    valores = dict(zip(CAMPOS_DO_CARRO,
                       (marca, modelo, ano, km, cor, cambio, preco, status, fotos or "")))
    conexao = conectar()
    try:
        novo_id = conexao.execute(
            "INSERT INTO estoque (loja_id, marca, modelo, ano, km, cor, cambio, preco, status, fotos) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (loja_id, *valores.values())).lastrowid
        registrar("cadastrar_carro", loja_id, None, valores, conexao=conexao,
                  alvo=f"carro:{novo_id}")
        conexao.commit()
    finally:
        conexao.close()
    return novo_id


def atualizar_carro(carro_id, marca, modelo, ano, km, cor, cambio, preco,
                    status, fotos="", *, loja_id, esperado=None):
    """Atualiza os campos editáveis de um carro existente.
    Carro já vendido: os dados (preço, fotos...) podem ser corrigidos, mas a
    situação continua 'vendido'. Nenhum carro vira 'vendido' por aqui."""
    from app.registro import conferir_ator, registrar   # aqui dentro: evita import circular
    conferir_ator(loja_id)
    conexao = conectar()
    try:
        linha = conexao.execute(
            f"SELECT {', '.join(CAMPOS_DO_CARRO)} FROM estoque WHERE id = ? AND loja_id = ?",
            (carro_id, loja_id)).fetchone()
        if linha is None:
            return "Carro não encontrado nesta loja."
        atual = valores_do_carro(linha)
        if atual["status"] == VENDIDO:
            if status != VENDIDO:
                raise StatusInvalido(MENSAGEM_JA_VENDIDO)
        else:
            _validar_status(status)
        if esperado is not None and any(atual[c] != esperado.get(c) for c in CAMPOS_DO_CARRO):
            raise CarroMudou("Outra pessoa mudou este carro enquanto você editava. "
                             "Nada foi gravado.")
        novos = dict(zip(CAMPOS_DO_CARRO,
                         (marca, modelo, ano, km, cor, cambio, preco, status, fotos or "")))
        mudou = [c for c in CAMPOS_DO_CARRO if atual[c] != novos[c]]
        if not mudou:
            return "Carro atualizado."
        conexao.execute(
            "UPDATE estoque SET marca = ?, modelo = ?, ano = ?, km = ?, cor = ?, cambio = ?, "
            "preco = ?, status = ?, fotos = ? WHERE id = ? AND loja_id = ?",
            (*novos.values(), carro_id, loja_id))
        registrar("alterar_carro", loja_id, {c: atual[c] for c in mudou},
                  {**{c: novos[c] for c in mudou}, "carro": f"{marca} {modelo} {ano}"},
                  conexao=conexao, alvo=f"carro:{carro_id}")
        conexao.commit()
    finally:
        conexao.close()
    return "Carro atualizado."


def marcar_status(carro_id, status, loja_id):
    """Muda só a situação: disponivel, reservado ou indisponivel.
    'vendido' é recusado: use registrar_venda (app/vendas.py)."""
    _validar_status(status)
    conexao = conectar()
    try:
        cursor = conexao.cursor()
        atual = _status_atual(cursor, carro_id, loja_id)
        if atual is None:
            return "Carro não encontrado nesta loja."
        if atual == VENDIDO:
            raise StatusInvalido(MENSAGEM_JA_VENDIDO)
        cursor.execute("UPDATE estoque SET status = ? WHERE id = ? AND loja_id = ?",
                       (status, carro_id, loja_id))
        conexao.commit()
    finally:
        conexao.close()
    return f"Status alterado para '{status}'."
