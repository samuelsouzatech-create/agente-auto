"""
Leitura do Registro (P6d; filtros no S3): uma lista só, da mais nova para a
mais antiga, juntando as três fontes de histórico:
- registro_acoes   (ações do P6b/P6c e do S2);
- pausas_envio     (pausar/retomar: já tinham histórico próprio);
- config_historico (salvar configuração: uma linha por campo mudado).

Só LÊ. Nada aqui grava. Sem Streamlit: a tela (S3) só mostra.
Cada loja vê só o que é dela. Eventos sem loja (mensagem de canal sem
cadastro) ficam em ler_eventos_de_sistema() e na leitura de todas as lojas,
que são só do operador.
Horários em UTC (formato do banco); a tela converte para o fuso da loja
(app/registro_tela.py).
Pausas e configuração antigas não guardam origem; a configuração também
não guarda o papel. Nesses casos o campo vem vazio (None), nunca inventado.

S3: filtros por pessoa, tipo de ação e período. O período é de dias
inteiros no fuso da loja (o dia final entra). Na leitura de todas as lojas,
o período usa o horário de Brasília (FUSO_GERAL), como o nível Geral.
"""
from __future__ import annotations

import json

from banco import conectar
from app.chaves import exigir_loja
from app.lojas import carregar_loja
from app.relogio import limites_do_dia_em_utc

MAX_LIMITE = 500
FUSO_GERAL = "America/Sao_Paulo"
ACAO_DA_PAUSA = {"pausar": "pausar_envios", "retomar": "retomar_envios"}
_PAUSA_DA_ACAO = {v: k for k, v in ACAO_DA_PAUSA.items()}
ACAO_DA_CONFIG = "salvar_configuracao"

# Como cada ação aparece na tela. Ação nova em ACOES_RELEVANTES ou em
# EVENTOS_DE_SISTEMA ganha rótulo aqui (um teste confere).
ROTULOS = {
    "pausar_envios": "Pausou os envios",
    "retomar_envios": "Retomou os envios",
    "bloquear_envio": "Bloqueou envio",
    "desfazer_bloqueio": "Desfez bloqueio",
    "registrar_venda": "Registrou venda",
    "importar_base": "Importou a base",
    "desfazer_importacao": "Desfez importação",
    "montar_fila_reativacao": "Montou fila de reativação",
    "cancelar_fila_reativacao": "Cancelou fila de reativação",
    "assumir_atendimento": "Assumiu atendimento",
    "assumir_conversa": "Assumiu conversa",
    "devolver_ao_agente": "Devolveu ao assistente",
    "salvar_configuracao": "Mudou configuração",
    "colocar_no_ar": "Colocou a loja no ar",
    "criar_acesso": "Criou acesso",
    "definir_email_acesso": "Mudou e-mail de acesso",
    "redefinir_senha": "Redefiniu senha",
    "criar_loja": "Criou a loja",
    "marcar_item_implantacao": "Marcou item da implantação",
    "desmarcar_item_implantacao": "Desmarcou item da implantação",
    "mensagem_canal_sem_cadastro": "Mensagem de canal sem cadastro",
    "mensagem_recusada_loja_em_teste": "Mensagem recusada (loja em teste)",
}


def rotulo(acao: str) -> str:
    return ROTULOS.get(acao, acao)


def _limite(limite) -> int:
    return max(1, min(int(limite), MAX_LIMITE))


def _json(texto):
    if texto is None:
        return None
    try:
        return json.loads(texto)
    except (TypeError, ValueError):
        return texto


def _item(quando, pessoa, papel, acao, alvo, antes, depois, origem, fonte,
          loja_id=None) -> dict:
    return {"quando": quando, "pessoa": pessoa, "papel": papel, "acao": acao,
            "rotulo": rotulo(acao), "alvo": alvo, "antes": antes, "depois": depois,
            "origem": origem, "fonte": fonte, "loja_id": loja_id}


# ------------------------------------------------------------ filtros

def _pessoa(pessoa) -> str | None:
    texto = " ".join(str(pessoa or "").split())
    return texto or None


def _faixa_utc(nome_fuso, inicio, fim) -> tuple[str | None, str | None]:
    """Dias locais (o dia final entra) -> começo e fim em UTC, formato do banco."""
    ini = limites_do_dia_em_utc(nome_fuso, inicio)[0] if inicio else None
    ate = limites_do_dia_em_utc(nome_fuso, fim)[1] if fim else None
    if ini and ate and ini >= ate:
        raise ValueError("O início do período precisa ser antes do fim.")
    return ini, ate


def _fontes(acao) -> set[str]:
    if not acao:
        return {"registro", "pausas", "config"}
    if acao in _PAUSA_DA_ACAO:
        return {"pausas"}
    if acao == ACAO_DA_CONFIG:
        return {"config"}
    return {"registro"}


def _onde(col_quando, col_pessoa, loja, pessoa, inicio, fim) -> tuple[list, list]:
    partes, valores = [], []
    if loja is not None:
        partes.append("loja_id = ?")
        valores.append(loja)
    if pessoa:
        partes.append(f"{col_pessoa} = ?")
        valores.append(pessoa)
    if inicio:
        partes.append(f"{col_quando} >= ?")
        valores.append(inicio)
    if fim:
        partes.append(f"{col_quando} < ?")
        valores.append(fim)
    return partes, valores


def _where(partes) -> str:
    return (" WHERE " + " AND ".join(partes)) if partes else ""


def _consultar(loja, pessoa, acao, inicio, fim, n) -> list[dict]:
    """loja None = todas as lojas e também os eventos sem loja."""
    fontes = _fontes(acao)
    itens = []
    conexao = conectar()
    try:
        if "registro" in fontes:
            partes, valores = _onde("quando", "pessoa", loja, pessoa, inicio, fim)
            if acao:
                partes.append("acao = ?")
                valores.append(acao)
            linhas = conexao.execute(
                "SELECT loja_id, quando, pessoa, papel, acao, alvo, antes, depois, origem "
                f"FROM registro_acoes{_where(partes)} ORDER BY quando DESC, id DESC LIMIT ?",
                (*valores, n)).fetchall()
            itens += [_item(l["quando"], l["pessoa"], l["papel"], l["acao"], l["alvo"],
                            _json(l["antes"]), _json(l["depois"]), l["origem"],
                            "registro_acoes", l["loja_id"])
                      for l in linhas]
        if "pausas" in fontes:
            partes, valores = _onde("criado_em", "usuario", loja, pessoa, inicio, fim)
            if acao:
                partes.append("acao = ?")
                valores.append(_PAUSA_DA_ACAO[acao])
            linhas = conexao.execute(
                "SELECT loja_id, criado_em, usuario, papel, acao, motivo FROM pausas_envio"
                f"{_where(partes)} ORDER BY criado_em DESC, id DESC LIMIT ?",
                (*valores, n)).fetchall()
            itens += [_item(l["criado_em"], l["usuario"], l["papel"],
                            ACAO_DA_PAUSA.get(l["acao"], l["acao"]), "loja", None,
                            {"motivo": l["motivo"]} if l["motivo"] else None, None,
                            "pausas_envio", l["loja_id"])
                      for l in linhas]
        if "config" in fontes:
            partes, valores = _onde("criado_em", "usuario", loja, pessoa, inicio, fim)
            linhas = conexao.execute(
                "SELECT loja_id, criado_em, usuario, chave, valor_antigo, valor_novo "
                f"FROM config_historico{_where(partes)} ORDER BY criado_em DESC, id DESC LIMIT ?",
                (*valores, n)).fetchall()
            itens += [_item(l["criado_em"], l["usuario"], None, ACAO_DA_CONFIG,
                            f"config:{l['chave']}", _json(l["valor_antigo"]),
                            _json(l["valor_novo"]), None, "config_historico", l["loja_id"])
                      for l in linhas]
    finally:
        conexao.close()
    itens.sort(key=lambda i: str(i["quando"] or ""), reverse=True)
    return itens[:n]


# ------------------------------------------------------------ leituras

def ler_registro(loja_id, limite: int = 100) -> list[dict]:
    """Tudo o que foi feito na loja, da mais nova para a mais antiga."""
    loja_id = exigir_loja(loja_id)
    return _consultar(loja_id, None, None, None, None, _limite(limite))


def filtrar_registro(loja_id, *, pessoa=None, acao=None, inicio=None, fim=None,
                     limite: int = 100) -> list[dict]:
    """S3: o Registro de UMA loja, com filtros. inicio/fim são dias no fuso da loja."""
    loja_id = exigir_loja(loja_id)
    loja = carregar_loja(loja_id)
    ini, ate = _faixa_utc(loja.get("fuso"), inicio, fim)
    return _consultar(loja_id, _pessoa(pessoa), acao or None, ini, ate, _limite(limite))


def filtrar_registro_de_todas(*, pessoa=None, acao=None, inicio=None, fim=None,
                              limite: int = 100) -> list[dict]:
    """S3: todas as lojas (e os eventos sem loja). Só para o operador.
    inicio/fim são dias no horário de Brasília."""
    ini, ate = _faixa_utc(FUSO_GERAL, inicio, fim)
    return _consultar(None, _pessoa(pessoa), acao or None, ini, ate, _limite(limite))


def _pessoas(loja) -> list[str]:
    onde = "" if loja is None else " WHERE loja_id = ?"
    valores = () if loja is None else (loja, loja, loja)
    conexao = conectar()
    try:
        linhas = conexao.execute(
            f"SELECT pessoa AS nome FROM registro_acoes{onde} "
            f"UNION SELECT usuario FROM pausas_envio{onde} "
            f"UNION SELECT usuario FROM config_historico{onde}", valores).fetchall()
    finally:
        conexao.close()
    nomes = {str(l["nome"]).strip() for l in linhas if l["nome"] and str(l["nome"]).strip()}
    return sorted(nomes, key=str.casefold)


def pessoas_no_registro(loja_id) -> list[str]:
    """Quem já aparece no Registro desta loja (para o filtro da tela)."""
    return _pessoas(exigir_loja(loja_id))


def pessoas_no_registro_de_todas() -> list[str]:
    return _pessoas(None)


def _acoes(loja) -> list[str]:
    onde = "" if loja is None else " WHERE loja_id = ?"
    valores = () if loja is None else (loja,)
    conexao = conectar()
    try:
        do_registro = {l["acao"] for l in conexao.execute(
            f"SELECT DISTINCT acao FROM registro_acoes{onde}", valores)}
        das_pausas = {ACAO_DA_PAUSA.get(l["acao"], l["acao"]) for l in conexao.execute(
            f"SELECT DISTINCT acao FROM pausas_envio{onde}", valores)}
        tem_config = conexao.execute(
            f"SELECT 1 FROM config_historico{onde} LIMIT 1", valores).fetchone() is not None
    finally:
        conexao.close()
    acoes = do_registro | das_pausas | ({ACAO_DA_CONFIG} if tem_config else set())
    return sorted(acoes, key=lambda a: rotulo(a).casefold())


def acoes_no_registro(loja_id) -> list[str]:
    """Tipos de ação que já aparecem no Registro desta loja (para o filtro)."""
    return _acoes(exigir_loja(loja_id))


def acoes_no_registro_de_todas() -> list[str]:
    return _acoes(None)


def ler_eventos_de_sistema(limite: int = 100) -> list[dict]:
    """Eventos sem loja (ex.: mensagem de canal sem cadastro). Só para o operador."""
    n = _limite(limite)
    conexao = conectar()
    try:
        linhas = conexao.execute(
            "SELECT quando, pessoa, papel, acao, alvo, antes, depois, origem "
            "FROM registro_acoes WHERE loja_id IS NULL ORDER BY quando DESC, id DESC LIMIT ?",
            (n,)).fetchall()
    finally:
        conexao.close()
    return [_item(l["quando"], l["pessoa"], l["papel"], l["acao"], l["alvo"],
                  _json(l["antes"]), _json(l["depois"]), l["origem"], "registro_acoes")
            for l in linhas]


# S4b
ROTULOS.update({
    "criar_pessoa_equipe": "Cadastrou pessoa na equipe",
    "alterar_pessoa_equipe": "Mudou cadastro da equipe",
    "desativar_pessoa_equipe": "Desativou pessoa da equipe",
    "reativar_pessoa_equipe": "Reativou pessoa da equipe",
    "cadastrar_canal": "Ligou canal",
    "desativar_canal": "Desativou canal",
    "cadastrar_numero_teste": "Cadastrou número de teste",
    "desativar_numero_teste": "Desativou número de teste",
})


# S4c: Estoque e Conhecimento.
ROTULOS.update({
    "cadastrar_carro": "Cadastrou carro",
    "alterar_carro": "Mudou carro",
    "criar_documento": "Criou texto do conhecimento",
    "alterar_documento": "Mudou texto do conhecimento",
    "apagar_documento": "Apagou texto do conhecimento",
})


# S8: Custos e preços.
ROTULOS.update({
    "cadastrar_preco": "Cadastrou preço",
    "apagar_preco": "Apagou preço",
    "recalcular_custos": "Recalculou custos",
})


# C2a: troca de senha pela própria pessoa.
ROTULOS.update({
    "trocar_senha": "Trocou a própria senha",
})
