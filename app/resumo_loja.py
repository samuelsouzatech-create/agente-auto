"""
Resumo de uma loja no ar (S2 da Fase 3): números de hoje e do mês, alertas
da loja e as últimas mudanças do Registro. Só LÊ; sem Streamlit.

Alertas do S2: só dois (nenhuma venda há 14 dias; envios pausados).
A lista completa de alertas, com as constantes num arquivo só, é do S9.
"""
from __future__ import annotations

from datetime import date

from banco import conectar
from app.apresentacao import horario_para_tela
from app.chaves import exigir_loja
from app.estado_loja import NO_AR, inicio_da_contagem, situacao_da_loja
from app.lojas import carregar_loja
from app.painel_leitura import resultado_do_periodo
from app.pausa import pausado
from app.registro_leitura import ler_registro
from app.relogio import agora_utc, do_banco, hora_local

from app.alertas_config import DIAS_SEM_VENDA  # noqa: E402  (S9: valor num arquivo só)
MAX_MUDANCAS = 10
ATENCAO = "atencao"


def resumo_hoje_e_mes(loja_id, agora=None) -> dict:
    """Resultado de hoje e do mês até hoje, no fuso da loja (funções do P4)."""
    loja_id = exigir_loja(loja_id)
    loja = carregar_loja(loja_id)
    hoje = hora_local(loja, agora or agora_utc()).date()
    return {"hoje": resultado_do_periodo(loja_id, hoje, hoje),
            "mes": resultado_do_periodo(loja_id, hoje.replace(day=1), hoje)}


def alertas_da_loja(loja_id, agora=None) -> list[dict]:
    loja_id = exigir_loja(loja_id)
    loja = carregar_loja(loja_id)
    agora = agora or agora_utc()
    alertas = []
    if pausado(loja_id):
        alertas.append({"nivel": ATENCAO,
                        "texto": "Os envios automáticos desta loja estão pausados."})

    situacao = situacao_da_loja(loja_id)
    if situacao["estado"] != NO_AR:
        return alertas
    desde = inicio_da_contagem(loja_id)      # P7c: venda do período de teste não conta
    conexao = conectar()
    try:
        ultima = conexao.execute(
            "SELECT MAX(data_venda) FROM vendas WHERE loja_id = ? "
            "AND (? IS NULL OR criado_em >= ?)", (loja_id, desde, desde)).fetchone()[0]
    finally:
        conexao.close()
    if ultima:
        referencia = date.fromisoformat(str(ultima)[:10])
    elif situacao["no_ar_em"]:
        referencia = hora_local(loja, do_banco(str(situacao["no_ar_em"])[:19])).date()
    else:
        referencia = None
    if referencia is not None:
        dias = (hora_local(loja, agora).date() - referencia).days
        if dias >= DIAS_SEM_VENDA:
            alertas.append({"nivel": ATENCAO,
                            "texto": f"Nenhuma venda registrada há {dias} dias."})
    return alertas


def ultimas_mudancas(loja_id, limite=MAX_MUDANCAS, agora=None) -> list[dict]:
    """As mudanças mais novas do Registro, já com o horário no fuso da loja."""
    loja_id = exigir_loja(loja_id)
    loja = carregar_loja(loja_id)
    return [{"quando": horario_para_tela(loja, i["quando"], agora=agora),
             "pessoa": i["pessoa"] or "—",
             "o_que": i["rotulo"]}
            for i in ler_registro(loja_id, limite)]
