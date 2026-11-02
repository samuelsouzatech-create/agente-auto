"""
Estado da loja (P7 do Plano Mestre): Em teste e No ar.

- 'em_teste': nada proativo sai de verdade (terceira trava em
  app/modo_envio.real_para) e o assistente só responde aos números de teste
  e ao simulador (a porta de entrada liga isso no P7b).
- 'no_ar': funciona normal.

O estado fica na tabela estado_lojas (migração 11). Loja sem linha lá conta
como em teste: toda loja nova nasce em teste. As que existiam antes da
migração 11 entraram no ar. Não se confunde com 'ativo' (loja desligada) nem
com o roteamento dos canais (app/canais.py): são três coisas separadas.

Só o operador coloca no ar, e isso vai para o Registro na mesma transação.
Só o operador cadastra números de teste. Sem Streamlit: as telas (S2 e S4b)
só mostram e chamam estas funções.
"""
from __future__ import annotations

from banco import conectar
from app.chaves import exigir_loja
from app.lojas import LojaNaoEncontrada
from app.relogio import agora_utc, para_banco
from app.telefone import normalizar_telefone_br

EM_TESTE = "em_teste"
NO_AR = "no_ar"
ESTADOS = (EM_TESTE, NO_AR)
ROTULOS = {EM_TESTE: "Em teste", NO_AR: "No ar"}
TIPOS_DE_CANAL = ("whatsapp", "telegram", "instagram")
CANAL_SIMULADOR = "simulador"
MAX_NOME = 80


class SoOperador(PermissionError):
    """Ação que só o operador pode fazer."""


class NumeroInvalido(ValueError):
    pass


def _exigir_operador(loja_id, mensagem: str):
    from app.registro import conferir_ator   # aqui dentro: evita import circular
    ator = conferir_ator(loja_id)
    if ator.papel != "operador":
        raise SoOperador(mensagem)
    return ator


# ------------------------------------------------------------ estado

def situacao_da_loja(loja_id) -> dict:
    """Estado, quando entrou no ar (UTC) e quem mudou por último."""
    loja_id = exigir_loja(loja_id)
    conexao = conectar()
    try:
        linha = conexao.execute(
            "SELECT l.id, e.estado, e.no_ar_em, e.alterado_por FROM lojas l "
            "LEFT JOIN estado_lojas e ON e.loja_id = l.id WHERE l.id = ?",
            (loja_id,)).fetchone()
    finally:
        conexao.close()
    if linha is None:
        raise LojaNaoEncontrada(f"Loja {loja_id} não existe.")
    estado = linha["estado"] or EM_TESTE
    return {"estado": estado, "rotulo": ROTULOS.get(estado, estado),
            "no_ar_em": linha["no_ar_em"], "alterado_por": linha["alterado_por"]}


def estado_da_loja(loja_id) -> str:
    return situacao_da_loja(loja_id)["estado"]


def esta_no_ar(loja_id) -> bool:
    """Para as travas: loja que não existe conta como em teste (nunca libera)."""
    try:
        return estado_da_loja(loja_id) == NO_AR
    except LojaNaoEncontrada:
        return False


def colocar_no_ar(loja_id, agora=None) -> bool:
    """Só o operador. Devolve True se mudou; False se a loja já estava no ar
    (nesse caso nada é gravado). Estado e Registro na mesma transação."""
    loja_id = exigir_loja(loja_id)
    ator = _exigir_operador(loja_id, "Só o operador coloca a loja no ar.")
    from app.registro import registrar      # aqui dentro: evita import circular
    momento = para_banco(agora or agora_utc())
    conexao = conectar()
    try:
        if not conexao.execute("SELECT 1 FROM lojas WHERE id = ?", (loja_id,)).fetchone():
            raise LojaNaoEncontrada(f"Loja {loja_id} não existe.")
        cursor = conexao.execute(
            "INSERT INTO estado_lojas (loja_id, estado, no_ar_em, alterado_por, atualizado_em) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT (loja_id) DO UPDATE SET estado = excluded.estado, "
            "no_ar_em = excluded.no_ar_em, alterado_por = excluded.alterado_por, "
            "atualizado_em = excluded.atualizado_em "
            "WHERE estado_lojas.estado != excluded.estado",
            (loja_id, NO_AR, momento, ator.pessoa, momento))
        if cursor.rowcount == 0:
            return False                         # já estava no ar: nada gravado
        registrar("colocar_no_ar", loja_id, {"estado": EM_TESTE},
                  {"estado": NO_AR, "no_ar_em": momento},
                  conexao=conexao, alvo="loja", agora=agora)
        conexao.commit()
    finally:
        conexao.close()
    return True


# ------------------------------------------------------------ números de teste

def normalizar_id_externo(tipo_de_canal: str, id_externo) -> str:
    """WhatsApp: telefone normalizado (com ou sem o 9 vira o mesmo).
    Telegram e Instagram: o id como texto, sem espaços."""
    texto = str(id_externo or "").strip()
    if tipo_de_canal == "whatsapp":
        return normalizar_telefone_br(texto)
    return texto


def cadastrar_numero_de_teste(loja_id, tipo_de_canal: str, id_externo, nome: str = "") -> int:
    """Só o operador. Se o número já existia nesta loja, reativa. Devolve o id."""
    loja_id = exigir_loja(loja_id)
    _exigir_operador(loja_id, "Só o operador cadastra números de teste.")
    if tipo_de_canal not in TIPOS_DE_CANAL:
        raise NumeroInvalido(f"Canal '{tipo_de_canal}' não existe "
                             f"(válidos: {', '.join(TIPOS_DE_CANAL)}).")
    numero = normalizar_id_externo(tipo_de_canal, id_externo)
    if not numero:
        raise NumeroInvalido("Número ou id vazio ou inválido.")
    nome_limpo = " ".join(str(nome or "").split())
    if len(nome_limpo) > MAX_NOME:
        raise NumeroInvalido(f"Nome com mais de {MAX_NOME} caracteres.")
    conexao = conectar()
    try:
        if not conexao.execute("SELECT 1 FROM lojas WHERE id = ?", (loja_id,)).fetchone():
            raise LojaNaoEncontrada(f"Loja {loja_id} não existe.")
        conexao.execute(
            """INSERT INTO numeros_de_teste (loja_id, tipo_de_canal, id_externo, nome, ativo)
               VALUES (?, ?, ?, ?, 1)
               ON CONFLICT (loja_id, tipo_de_canal, id_externo) DO UPDATE SET
                   nome = excluded.nome, ativo = 1""",
            (loja_id, tipo_de_canal, numero, nome_limpo or None))
        novo_id = conexao.execute(
            "SELECT id FROM numeros_de_teste WHERE loja_id = ? AND tipo_de_canal = ? "
            "AND id_externo = ?", (loja_id, tipo_de_canal, numero)).fetchone()["id"]
        conexao.commit()
    finally:
        conexao.close()
    return novo_id


def desativar_numero_de_teste(loja_id, numero_id: int) -> bool:
    """Só o operador. True se desativou; False se não existe nesta loja ou já estava desativado."""
    loja_id = exigir_loja(loja_id)
    _exigir_operador(loja_id, "Só o operador desativa números de teste.")
    conexao = conectar()
    try:
        cursor = conexao.execute(
            "UPDATE numeros_de_teste SET ativo = 0 WHERE id = ? AND loja_id = ? AND ativo = 1",
            (numero_id, loja_id))
        conexao.commit()
        return cursor.rowcount > 0
    finally:
        conexao.close()


def listar_numeros_de_teste(loja_id, so_ativos: bool = True) -> list[dict]:
    loja_id = exigir_loja(loja_id)
    sql = "SELECT * FROM numeros_de_teste WHERE loja_id = ?"
    if so_ativos:
        sql += " AND ativo = 1"
    conexao = conectar()
    try:
        linhas = conexao.execute(sql + " ORDER BY tipo_de_canal, id", (loja_id,)).fetchall()
    finally:
        conexao.close()
    return [dict(l) for l in linhas]


def pode_responder(loja_id, tipo_de_canal: str, id_externo) -> bool:
    """O assistente pode responder a quem escreveu? Simulador: sempre.
    Loja no ar: sempre. Loja em teste: só número de teste ativo DESTA loja."""
    loja_id = exigir_loja(loja_id)
    if tipo_de_canal == CANAL_SIMULADOR:
        return True
    if esta_no_ar(loja_id):
        return True
    numero = normalizar_id_externo(tipo_de_canal, id_externo)
    if not numero:
        return False
    conexao = conectar()
    try:
        return conexao.execute(
            "SELECT 1 FROM numeros_de_teste WHERE loja_id = ? AND tipo_de_canal = ? "
            "AND id_externo = ? AND ativo = 1", (loja_id, tipo_de_canal, numero)).fetchone() is not None
    finally:
        conexao.close()
