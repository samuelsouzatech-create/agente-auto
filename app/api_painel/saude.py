"""
A luz "Léo atendendo" do topo (GET /saude, C2b; item 14 e decisão D4).

Olha só o cadastro, sem testar o canal ao vivo:
  vermelha  nenhum canal ativo                     "Léo fora do ar"
  amarela   loja em teste, ou envios pausados       "Léo com atenção"
  verde     tudo certo                              "Léo atendendo"
Nunca verde com pausa, loja em teste ou sem canal ativo.
Faixa do topo: azul se em teste; laranja se pausado; senão nenhuma.
Só lê: nada aqui grava no banco.
"""
from __future__ import annotations

from app.apresentacao import nome_do_canal
from app.api_painel.formato import horario
from app.canais import listar_canais
from app.estado_loja import EM_TESTE, situacao_da_loja
from app.lojas import carregar_loja
from app.pausa import situacao as situacao_da_pausa
from app.relogio import agora_utc

TIPOS = ("whatsapp", "telegram", "instagram")
FAIXA_EM_TESTE = "Sua loja está em teste: o Léo só responde aos números de teste."


def _juntar(rotulos) -> str:
    nomes = [f"o {r}" for r in rotulos]
    if len(nomes) == 1:
        return nomes[0]
    return ", ".join(nomes[:-1]) + " e " + nomes[-1]


def montar_saude(loja_id: int, agora=None) -> dict:
    agora = agora or agora_utc()
    loja = carregar_loja(loja_id)
    situacao = situacao_da_loja(loja_id)
    estado = {"codigo": situacao["estado"], "rotulo": situacao["rotulo"]}
    em_teste = estado["codigo"] == EM_TESTE

    p = situacao_da_pausa(loja_id)
    desde = horario(loja, p["em"], agora) if p["pausado"] else None
    pausa = {"ativa": p["pausado"],
             "por": p["usuario"] if p["pausado"] else None,
             "desde": desde,
             "motivo": (p["motivo"] or None) if p["pausado"] else None}

    ativos = {}
    for canal in listar_canais(loja_id):
        ativos[canal["tipo"]] = ativos.get(canal["tipo"], False) or bool(canal["ativo"])
    canais = [{"tipo": t, "rotulo": nome_do_canal(t), "ativo": ativos[t]}
              for t in TIPOS if t in ativos]
    ligados = [c["rotulo"] for c in canais if c["ativo"]]

    faixa = None
    if em_teste:
        faixa = {"tipo": "azul", "texto": FAIXA_EM_TESTE}
    elif pausa["ativa"]:
        quem = f" por {pausa['por']}" if pausa["por"] else ""
        quando = f" desde {desde['texto']}" if desde else ""
        faixa = {"tipo": "laranja", "texto": f"Envios automáticos pausados{quem}{quando}."}

    if not ligados:
        luz, titulo, detalhe = "vermelha", "Léo fora do ar", "Nenhum canal está ativo."
    elif em_teste:
        luz, titulo, detalhe = "amarela", "Léo com atenção", "Sua loja está em teste."
    elif pausa["ativa"]:
        luz, titulo, detalhe = "amarela", "Léo com atenção", "Os envios automáticos estão pausados."
    else:
        luz, titulo, detalhe = "verde", "Léo atendendo", f"Atendendo {_juntar(ligados)}."

    return {"luz": luz, "titulo": titulo, "detalhe": detalhe, "estado": estado,
            "pausa": pausa, "canais": canais, "faixa": faixa}
