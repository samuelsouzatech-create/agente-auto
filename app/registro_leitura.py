"""
Leitura do Registro (P6d): uma lista só, da mais nova para a mais antiga,
juntando as três fontes de histórico:
- registro_acoes   (ações do P6b/P6c);
- pausas_envio     (pausar/retomar: já tinham histórico próprio);
- config_historico (salvar configuração: uma linha por campo mudado).

Só LÊ. Nada aqui grava. Sem Streamlit: a tela (S3) só mostra.
Cada loja vê só o que é dela. Eventos sem loja (mensagem de canal sem
cadastro) ficam em ler_eventos_de_sistema(), que é só do operador.
Horários em UTC (formato do banco); a tela converte para o fuso da loja.
Pausas e configuração antigas não guardam origem; a configuração também
não guarda o papel. Nesses casos o campo vem vazio (None), nunca inventado.
"""
from __future__ import annotations

import json

from banco import conectar
from app.chaves import exigir_loja

MAX_LIMITE = 500
ACAO_DA_PAUSA = {"pausar": "pausar_envios", "retomar": "retomar_envios"}

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
    "salvar_configuracao": "Mudou configuração","colocar_no_ar": "Colocou a loja no ar",
    "criar_acesso": "Criou acesso",
    "definir_email_acesso": "Mudou e-mail de acesso",
    "redefinir_senha": "Redefiniu senha",
    "mensagem_canal_sem_cadastro": "Mensagem de canal sem cadastro", "mensagem_recusada_loja_em_teste": "Mensagem recusada (loja em teste)",
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


def _item(quando, pessoa, papel, acao, alvo, antes, depois, origem, fonte) -> dict:
    return {"quando": quando, "pessoa": pessoa, "papel": papel, "acao": acao,
            "rotulo": rotulo(acao), "alvo": alvo, "antes": antes, "depois": depois,
            "origem": origem, "fonte": fonte}


def ler_registro(loja_id, limite: int = 100) -> list[dict]:
    """Tudo o que foi feito na loja, da mais nova para a mais antiga."""
    loja_id = exigir_loja(loja_id)
    n = _limite(limite)
    conexao = conectar()
    try:
        acoes = conexao.execute(
            "SELECT quando, pessoa, papel, acao, alvo, antes, depois, origem "
            "FROM registro_acoes WHERE loja_id = ? ORDER BY quando DESC, id DESC LIMIT ?",
            (loja_id, n)).fetchall()
        pausas = conexao.execute(
            "SELECT criado_em, usuario, papel, acao, motivo FROM pausas_envio "
            "WHERE loja_id = ? ORDER BY criado_em DESC, id DESC LIMIT ?",
            (loja_id, n)).fetchall()
        configs = conexao.execute(
            "SELECT criado_em, usuario, chave, valor_antigo, valor_novo FROM config_historico "
            "WHERE loja_id = ? ORDER BY criado_em DESC, id DESC LIMIT ?",
            (loja_id, n)).fetchall()
    finally:
        conexao.close()

    itens = [_item(l["quando"], l["pessoa"], l["papel"], l["acao"], l["alvo"],
                   _json(l["antes"]), _json(l["depois"]), l["origem"], "registro_acoes")
             for l in acoes]
    itens += [_item(l["criado_em"], l["usuario"], l["papel"],
                    ACAO_DA_PAUSA.get(l["acao"], l["acao"]), "loja", None,
                    {"motivo": l["motivo"]} if l["motivo"] else None, None, "pausas_envio")
              for l in pausas]
    itens += [_item(l["criado_em"], l["usuario"], None, "salvar_configuracao",
                    f"config:{l['chave']}", _json(l["valor_antigo"]), _json(l["valor_novo"]),
                    None, "config_historico")
              for l in configs]
    itens.sort(key=lambda i: str(i["quando"] or ""), reverse=True)
    return itens[:n]


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
