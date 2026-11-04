"""
Configuração por assunto (S4a da Fase 3): "última alteração por quem e
quando" e o Desfazer de cada assunto. Sem Streamlit; a tela só mostra e chama.

Fonte: config_historico (uma linha por campo salvo, gravada pelo salvar_config).
É a mesma fonte que o Registro lê, então os dois sempre batem.

Desfazer = voltar os valores do ÚLTIMO Salvar que mudou algum campo do
assunto, chamando o próprio salvar_config. Assim valem a mesma validação,
a permissão por dono, a proteção de versão e o histórico (que aparece no
Registro como "Mudou configuração"). Nada novo no banco, sem migração.

Como achar "o último Salvar" sem um número de salvamento no histórico:
linhas da mesma loja com ids seguidos, da mesma pessoa e no máximo 1 s
depois da primeira. Um mesmo campo aparecendo de novo = outro Salvar.
Linhas que só confirmaram (valor igual ao de antes) não contam como alteração.
Desfazer duas vezes refaz. Desfazer não devolve a marca "a confirmar".
"""
from __future__ import annotations

import json
from datetime import timedelta

from banco import conectar
from app.apresentacao import horario_para_tela
from app.chaves import exigir_loja
from app.config_tela import campo, campos_do_assunto, formatar
from app.lojas import Loja, carregar_loja, salvar_config
from app.relogio import do_banco

MESMO_SALVAR = timedelta(seconds=1)
MAX_LINHAS = 200
VAZIO = "—"
_COLUNAS = "id, usuario, chave, valor_antigo, valor_novo, criado_em"


class NadaParaDesfazer(LookupError):
    """O assunto não tem alteração para desfazer."""


class DesfazerRecusado(RuntimeError):
    """O valor mudou depois da última alteração: desfazer passaria por cima."""


def _valor(texto):
    if texto is None:
        return None
    try:
        return json.loads(texto)
    except (TypeError, ValueError):
        return texto


def _instante(texto):
    try:
        return do_banco(str(texto).strip().replace("T", " "))
    except (TypeError, ValueError):
        return None


def _mudou(linha) -> bool:
    return _valor(linha["valor_antigo"]) != _valor(linha["valor_novo"])


def _chaves(assunto) -> list[str]:
    return [c.chave for c in campos_do_assunto(assunto)]


def _linhas_do_assunto(loja_id, chaves) -> list[dict]:
    if not chaves:
        return []
    marcas = ",".join("?" * len(chaves))
    conexao = conectar()
    try:
        linhas = conexao.execute(
            f"SELECT {_COLUNAS} FROM config_historico "
            f"WHERE loja_id = ? AND chave IN ({marcas}) ORDER BY id DESC LIMIT ?",
            (loja_id, *chaves, MAX_LINHAS)).fetchall()
    finally:
        conexao.close()
    return [dict(l) for l in linhas]


def _linhas_ate(loja_id, ate_id) -> list[dict]:
    conexao = conectar()
    try:
        linhas = conexao.execute(
            f"SELECT {_COLUNAS} FROM config_historico "
            "WHERE loja_id = ? AND id <= ? ORDER BY id DESC LIMIT ?",
            (loja_id, ate_id, MAX_LINHAS)).fetchall()
    finally:
        conexao.close()
    return [dict(l) for l in linhas]


def _mesmo_salvar(loja_id, primeira) -> list[dict]:
    """A primeira linha e as que foram gravadas junto com ela (mesmo Salvar)."""
    inicio = _instante(primeira["criado_em"])
    grupo, vistas, anterior = [], set(), None
    for l in _linhas_ate(loja_id, primeira["id"]):
        if anterior is not None:
            quando = _instante(l["criado_em"])
            if (l["id"] != anterior["id"] - 1 or l["usuario"] != primeira["usuario"]
                    or inicio is None or quando is None or abs(inicio - quando) > MESMO_SALVAR):
                break
        if l["chave"] in vistas:
            break
        vistas.add(l["chave"])
        grupo.append(l)
        anterior = l
    return grupo


# ------------------------------------------------------------ leituras

def ultima_alteracao(loja_id, assunto, agora=None) -> dict | None:
    """Quem salvou por último algum campo do assunto e quando (fuso da loja)."""
    loja_id = exigir_loja(loja_id)
    linhas = _linhas_do_assunto(loja_id, _chaves(assunto))
    if not linhas:
        return None
    ultima = linhas[0]
    return {"quem": ultima["usuario"] or VAZIO,
            "quando": horario_para_tela(carregar_loja(loja_id), ultima["criado_em"], agora=agora)}


def o_que_desfazer(loja_id, assunto, agora=None) -> dict | None:
    """O que o Desfazer faria agora, já em texto de tela. None = nada a desfazer."""
    loja_id = exigir_loja(loja_id)
    chaves = _chaves(assunto)
    primeira = next((l for l in _linhas_do_assunto(loja_id, chaves) if _mudou(l)), None)
    if primeira is None:
        return None
    ordem = {chave: i for i, chave in enumerate(chaves)}
    grupo = sorted((l for l in _mesmo_salvar(loja_id, primeira)
                    if l["chave"] in ordem and _mudou(l)),
                   key=lambda l: ordem[l["chave"]])
    itens, valores, esperado = [], {}, {}
    for l in grupo:
        c = campo(l["chave"])
        antigo, novo = _valor(l["valor_antigo"]), _valor(l["valor_novo"])
        valores[c.chave], esperado[c.chave] = antigo, novo
        itens.append({"chave": c.chave, "rotulo": c.rotulo,
                      "agora": formatar(c, novo), "volta_para": formatar(c, antigo)})
    return {"quem": primeira["usuario"] or VAZIO,
            "quando": horario_para_tela(carregar_loja(loja_id), primeira["criado_em"],
                                        agora=agora),
            "itens": itens, "valores": valores, "esperado": esperado}


# ------------------------------------------------------------ ação

def desfazer_ultima(loja_id, assunto, usuario, papel, versao_esperada=None) -> Loja:
    """Volta a última alteração do assunto pelo salvar_config (mesmas regras)."""
    loja_id = exigir_loja(loja_id)
    plano = o_que_desfazer(loja_id, assunto)
    if plano is None:
        raise NadaParaDesfazer("Não há alteração para desfazer neste assunto.")
    loja = carregar_loja(loja_id)
    mudaram = [campo(chave).rotulo for chave, valor in plano["esperado"].items()
               if loja.get(chave) != valor]
    if mudaram:
        raise DesfazerRecusado("Estes campos mudaram depois da última alteração: "
                               + ", ".join(mudaram) + ". Nada foi desfeito.")
    return salvar_config(loja_id, plano["valores"], usuario, papel=papel,
                         versao_esperada=versao_esperada)
