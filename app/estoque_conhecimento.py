"""
Estoque e Conhecimento da Configuração do operador (S4c da Fase 3).
Leitura pronta para a tela, texto do Registro e o Desfazer (que chama as
escritas de app/estoque.py e app/conhecimento.py: mesmas regras e Registro).
Sem Streamlit.

Desfazer = voltar a ÚLTIMA ação do assunto nesta loja:
- Estoque: a última edição de carro. Cadastro não se desfaz (marque o carro
  como Indisponível). Nunca mexe na situação de carro vendido.
- Conhecimento: a última edição (volta o texto) ou o último apagar (traz de
  volta). Criação não se desfaz (apague o documento).
Se o valor mudou depois da ação, recusa e nada muda.
"""
from __future__ import annotations

import json

from banco import conectar
from app import conhecimento, estoque
from app.apresentacao import horario_para_tela
from app.chaves import exigir_loja
from app.config_assunto import DesfazerRecusado, NadaParaDesfazer
from app.lojas import carregar_loja

ACOES_ESTOQUE = ("cadastrar_carro", "alterar_carro")
ACOES_CONHECIMENTO = conhecimento.ACOES
ACOES_DO_ASSUNTO = {"Estoque": ACOES_ESTOQUE, "Conhecimento": ACOES_CONHECIMENTO}
ACOES_S4C = ACOES_ESTOQUE + ACOES_CONHECIMENTO

FONTE_DO_ESTOQUE = "cadastro feito neste painel"
NOTA_ESTOQUE = ("Os carros que o assistente oferece: só os Disponíveis. A venda é registrada "
                "na conversa do cliente, em \"Registrar venda\".")
NOTA_CONHECIMENTO = ("Políticas que o assistente consulta: financiamento, troca, garantia, "
                     "test-drive, horário. Escreva como explicaria a um vendedor novo. "
                     "O texto salvo vale na próxima mensagem do cliente.")
AJUDA_FOTOS = "Links das fotos, separados por vírgula."
ROTULOS_STATUS = {"disponivel": "Disponível", "reservado": "Reservado",
                  "indisponivel": "Indisponível", "vendido": "Vendido"}
ROTULOS_CAMPO_CARRO = {"marca": "Marca", "modelo": "Modelo", "ano": "Ano", "km": "Km",
                       "cor": "Cor", "cambio": "Câmbio", "preco": "Preço",
                       "status": "Situação", "fotos": "Fotos"}


def _brl(valor) -> str:
    try:
        return "R$ " + f"{float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "R$ —"


def rotulo_status(status) -> str:
    return ROTULOS_STATUS.get(status, str(status))


def _titulo_carro(d: dict) -> str:
    return " ".join(str(d[k]) for k in ("marca", "modelo", "ano") if d.get(k) not in (None, ""))


def _json(texto):
    if texto is None:
        return None
    try:
        return json.loads(texto)
    except (TypeError, ValueError):
        return None


def _acoes(assunto):
    if assunto not in ACOES_DO_ASSUNTO:
        raise ValueError(f"Assunto sem registro próprio: {assunto}")
    return ACOES_DO_ASSUNTO[assunto]


def _ultima(loja_id, acoes):
    marcas = ",".join("?" * len(acoes))
    conexao = conectar()
    try:
        return conexao.execute(
            f"SELECT id, quando, pessoa, acao, alvo, antes, depois FROM registro_acoes "
            f"WHERE loja_id = ? AND acao IN ({marcas}) ORDER BY id DESC LIMIT 1",
            (loja_id, *acoes)).fetchone()
    finally:
        conexao.close()


def _id(alvo, prefixo):
    texto = str(alvo or "")
    if not texto.startswith(prefixo + ":"):
        return None
    try:
        return int(texto.split(":", 1)[1])
    except ValueError:
        return None


# ------------------------------------------------------------ leituras

def ultima_alteracao(loja_id, assunto, agora=None) -> dict | None:
    loja_id = exigir_loja(loja_id)
    l = _ultima(loja_id, _acoes(assunto))
    if l is None:
        return None
    return {"quem": l["pessoa"],
            "quando": horario_para_tela(carregar_loja(loja_id), l["quando"], agora=agora)}


def estoque_da_loja(loja_id, incluir_vendidos=True) -> list[dict]:
    loja_id = exigir_loja(loja_id)
    saida = []
    for c in estoque.listar_estoque(loja_id, incluir_vendidos=incluir_vendidos):
        v = estoque.valores_do_carro(c)
        saida.append({
            "id": c["id"], "titulo": _titulo_carro(v), "rotulo_status": rotulo_status(v["status"]),
            "preco_tela": _brl(v["preco"]), "vendido": v["status"] == estoque.VENDIDO,
            "fotos": [u.strip() for u in v["fotos"].split(",") if u.strip()], "versao": v,
        })
    return saida


def documentos_da_loja(loja_id) -> list[dict]:
    loja_id = exigir_loja(loja_id)
    loja = carregar_loja(loja_id)
    return [{"id": d["id"], "titulo": d["titulo"],
             "atualizado": horario_para_tela(loja, d["atualizado_em"]),
             "versao": {"titulo": d["titulo"], "texto": d["texto"]}}
            for d in conhecimento.listar_documentos(loja_id)]


# ------------------------------------------------------------ Registro

def _valor_carro(campo, valor) -> str:
    if valor in (None, ""):
        return "vazio"
    if campo == "preco":
        return _brl(valor)
    if campo == "status":
        return rotulo_status(valor)
    return str(valor)


def _mudancas_carro(de: dict, para: dict) -> str:
    partes = []
    for c, rotulo in ROTULOS_CAMPO_CARRO.items():
        if c in de and c in para and de[c] != para[c]:
            partes.append("Fotos alteradas" if c == "fotos" else
                          f"{rotulo}: {_valor_carro(c, de[c])} → {_valor_carro(c, para[c])}")
    return ", ".join(partes)


def detalhe_do_registro(acao: str, antes, depois) -> str:
    """Texto da coluna Detalhe do Registro para as ações do S4c. Sem ids, sem texto inteiro."""
    a = antes if isinstance(antes, dict) else {}
    d = depois if isinstance(depois, dict) else {}
    if acao == "cadastrar_carro":
        partes = (_titulo_carro(d), rotulo_status(d["status"]) if d.get("status") else "",
                  _brl(d["preco"]) if d.get("preco") is not None else "")
        return " · ".join(p for p in partes if p)
    if acao == "alterar_carro":
        return " · ".join(p for p in (str(d.get("carro") or ""), _mudancas_carro(a, d)) if p)
    if acao == "criar_documento":
        return f"{d.get('titulo', '')} · criado"
    if acao == "alterar_documento":
        if a.get("titulo") != d.get("titulo"):
            extra = " · texto alterado" if a.get("texto") != d.get("texto") else ""
            return f"Título: {a.get('titulo')} → {d.get('titulo')}{extra}"
        return f"{d.get('titulo', '')} · texto alterado"
    if acao == "apagar_documento":
        return f"{a.get('titulo') or d.get('titulo') or ''} · apagado"
    return ""


# ------------------------------------------------------------ desfazer

def o_que_desfazer(loja_id, assunto, agora=None) -> dict | None:
    loja_id = exigir_loja(loja_id)
    l = _ultima(loja_id, _acoes(assunto))
    if l is None or l["acao"] in ("cadastrar_carro", "criar_documento"):
        return None
    a, d = _json(l["antes"]) or {}, _json(l["depois"]) or {}
    if l["acao"] == "alterar_carro":
        alvo = _id(l["alvo"], "carro")
        texto = f"{d.get('carro') or 'Carro'}: volta {_mudancas_carro(d, a)}"
    elif l["acao"] == "alterar_documento":
        alvo = _id(l["alvo"], "documento")
        texto = f"Documento \"{a.get('titulo')}\": volta ao texto anterior"
    else:
        alvo = None
        texto = f"Traz de volta o documento apagado \"{a.get('titulo')}\""
    return {"acao": l["acao"], "alvo_id": alvo, "antes": a, "depois": d, "quem": l["pessoa"],
            "quando": horario_para_tela(carregar_loja(loja_id), l["quando"], agora=agora),
            "texto": texto}


def desfazer_ultima(loja_id, assunto) -> str:
    """Desfaz e devolve a mensagem para a tela. Pode levantar NadaParaDesfazer,
    DesfazerRecusado ou conhecimento.ErroIndexacao (texto salvo, índice não)."""
    loja_id = exigir_loja(loja_id)
    plano = o_que_desfazer(loja_id, assunto)
    if plano is None:
        raise NadaParaDesfazer("Não há alteração para desfazer neste assunto.")
    a, d = plano["antes"], plano["depois"]
    if plano["acao"] == "alterar_carro":
        carro = estoque.buscar_carro(plano["alvo_id"], loja_id)
        if carro is None:
            raise DesfazerRecusado("Este carro não está mais nesta loja. Nada foi desfeito.")
        atual = estoque.valores_do_carro(carro)
        campos = [c for c in a if c in estoque.CAMPOS_DO_CARRO]
        if any(atual[c] != d.get(c) for c in campos):
            raise DesfazerRecusado("O carro mudou depois da última alteração. Nada foi desfeito.")
        try:
            estoque.atualizar_carro(plano["alvo_id"], loja_id=loja_id, esperado=atual,
                                    **{**atual, **{c: a[c] for c in campos}})
        except (estoque.StatusInvalido, estoque.CarroMudou) as erro:
            raise DesfazerRecusado(f"{erro} Nada foi desfeito.") from erro
        return f"{_titulo_carro(atual)}: alteração desfeita."
    if plano["acao"] == "alterar_documento":
        try:
            conhecimento.salvar_documento(loja_id, a["titulo"], a["texto"], plano["alvo_id"],
                                          esperado={"titulo": d.get("titulo"),
                                                    "texto": d.get("texto")})
        except (conhecimento.DocumentoMudou, conhecimento.DocumentoNaoEncontrado) as erro:
            raise DesfazerRecusado("O documento mudou ou foi apagado depois da última "
                                   "alteração. Nada foi desfeito.") from erro
        return f"{a['titulo']}: texto anterior de volta."
    if conhecimento.existe_titulo(loja_id, a.get("titulo")):
        raise DesfazerRecusado(f"Já existe um documento chamado \"{a.get('titulo')}\". "
                               "Nada foi desfeito.")
    conhecimento.salvar_documento(loja_id, a["titulo"], a["texto"])
    return f"{a['titulo']}: documento de volta."
