"""
Bancada pelo INSTAGRAM (BA2, Maratona 5). Gemini real, pelo MESMO caminho do webhook.

Cada roteiro de bancada/roteiros_instagram/*.yaml vira pedidos HTTP assinados para
POST /webhook/instagram (e, na passagem para o WhatsApp, POST /webhook), no app de verdade
(app/api/webhook.py), com o SERVIDOR FALSO DA META (tests/meta_falsa.py, HTTP de verdade em
127.0.0.1) no lugar da Meta. O que o Léo manda sai pela CanalInstagram de verdade e chega ao
servidor falso: é isso que o relatório mostra. Nada sai do computador:
  - o banco é o temporário da bancada (nunca o de uso);
  - INSTAGRAM_API_URL aponta para 127.0.0.1; o bloqueio da bancada aborta qualquer pedido para
    facebook.com, instagram.com, whatsapp.com e telegram.org;
  - o WhatsApp da passagem é gravado (envio falso), nunca enviado.
Trocados por falsos (só o que não dá para usar fora do servidor): o Redis do debounce, da trava e
das mensagens repetidas (em memória, como nos testes do IG1/IG3) e a espera do eco (0 s).

Uso:  .venv-teste\\Scripts\\python scripts\\bancada_instagram.py            (todos)
      .venv-teste\\Scripts\\python scripts\\bancada_instagram.py --roteiro ig_pede_whatsapp
Teto: LEO_API_TETO_USD (o mesmo da bancada). Relatório: logs/bancada/instagram_<data>.md

Formato do roteiro (além de nome, falas, nao_contem, nao_pode e deve da bancada de sempre):
  comentario: {texto: "...", legenda: "..."}   comentário num post (sem legenda = post sem carro)
  acoes: [{depois_da_fala: 1, tipo: vendedor_assumiu}]   o vendedor responde pelo app (eco)
  whatsapp: ["oi, sou eu do insta"]          falas do MESMO cliente no WhatsApp da loja, do telefone
                                              que ele passou no direct
  confere: {privada_cita: "Civic", privada_texto_fixo: sim, mesmo_cliente: sim, link_whatsapp: sim}
Checagens do Instagram, em TODO roteiro: cada mensagem <= 1.000 bytes; no máximo UMA mensagem
privada por comentário e nada mais para a pessoa antes de ela responder; mensagem privada sem preço.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import scripts.rodar_bancada as rb  # noqa: E402

PASTA_ROTEIROS_IG = RAIZ / "bancada" / "roteiros_instagram"
PAYLOADS = RAIZ / "tests" / "payloads" / "instagram"
CONTA = "17841400000000001"             # a conta fictícia da loja (a mesma dos testes)
POST = "18100000000000001"
CLIENTE_IG = "9100000000000001"
TOKEN = "token-falso-bancada-instagram"
SEGREDO_IG = "segredo-falso-bancada-ig"
SEGREDO_WA = "segredo-falso-bancada-wa"
PHONE_ID = "phone-id-falso-bancada"
WHATSAPP_DA_LOJA = "81 98888-7777"
LIMITE_BYTES = 1000
CAMPOS_IG = {"comentario", "acoes", "whatsapp", "confere", "descricao", "contexto_inicial", "contem_algum"}


class RoteiroInstagramInvalido(ValueError):
    pass


def validar(dados: dict, origem: str) -> dict:
    """Separa o que é do Instagram e valida o resto com a validação da bancada de sempre."""
    if not isinstance(dados, dict):
        raise RoteiroInstagramInvalido(f"{origem}: o roteiro precisa ser um mapa YAML")
    extras = {k: dados[k] for k in CAMPOS_IG if k in dados}
    base = {k: v for k, v in dados.items() if k not in CAMPOS_IG}
    if "contem_algum" in extras:                    # formato antigo do IG3: vira deve.contem (qualquer um)
        base.setdefault("deve", {})
    base.setdefault("falas", [])
    base["canal"] = "instagram"
    if not base["falas"] and not extras.get("comentario"):
        raise RoteiroInstagramInvalido(f"{origem}: precisa de 'falas' ou de 'comentario'")
    try:
        roteiro = rb.validar_roteiro({**base, "falas": base["falas"] or ["(só o comentário)"]}, origem)
    except rb.RoteiroInvalido as erro:
        raise RoteiroInstagramInvalido(str(erro)) from None
    if not base["falas"]:
        roteiro["falas"] = []
    comentario = extras.get("comentario")
    if comentario is not None and (not isinstance(comentario, dict) or not str(comentario.get("texto") or "").strip()):
        raise RoteiroInstagramInvalido(f"{origem}: 'comentario' precisa de 'texto'")
    acoes = extras.get("acoes") or []
    for a in acoes:
        if not isinstance(a, dict) or a.get("tipo") != "vendedor_assumiu" or not isinstance(a.get("depois_da_fala"), int):
            raise RoteiroInstagramInvalido(f"{origem}: ação inválida {a!r} (só vendedor_assumiu com depois_da_fala)")
    whatsapp = extras.get("whatsapp") or []
    if not isinstance(whatsapp, list) or not all(isinstance(f, str) and f.strip() for f in whatsapp):
        raise RoteiroInstagramInvalido(f"{origem}: 'whatsapp' é uma lista de falas")
    confere = extras.get("confere") or {}
    if set(confere) - {"privada_cita", "privada_texto_fixo", "mesmo_cliente", "link_whatsapp", "silencio_depois_de"}:
        raise RoteiroInstagramInvalido(f"{origem}: 'confere' com campo desconhecido")
    roteiro["ig"] = {"comentario": comentario, "acoes": acoes, "whatsapp": [f.strip() for f in whatsapp],
                     "confere": confere, "contem_algum": [str(c) for c in (extras.get("contem_algum") or [])],
                     "contexto_inicial": extras.get("contexto_inicial")}
    return roteiro


def carregar(so: str | None = None) -> list[dict]:
    import yaml
    roteiros = []
    for caminho in sorted(PASTA_ROTEIROS_IG.glob("*.yaml")):
        roteiro = validar(yaml.safe_load(caminho.read_text(encoding="utf-8")), caminho.stem)
        if so and so not in (roteiro["nome"], caminho.stem):
            continue
        roteiros.append(roteiro)
    if so and not roteiros:
        raise RoteiroInstagramInvalido(f"roteiro {so!r} não encontrado")
    return roteiros


# ------------------------------------------------------------------ pedidos assinados
def _assinar(corpo: bytes, segredo: str) -> dict:
    return {"X-Hub-Signature-256": "sha256=" + hmac.new(segredo.encode(), corpo, hashlib.sha256).hexdigest(),
            "Content-Type": "application/json"}


def _payload(nome: str) -> dict:
    return json.loads((PAYLOADS / nome).read_text(encoding="utf-8"))


def _direct(texto: str, mid: str, remetente: str = CLIENTE_IG) -> bytes:
    dados = _payload("mensagem_texto.json")
    evento = dados["entry"][0]["messaging"][0]
    dados["entry"][0]["id"] = CONTA
    evento["sender"]["id"] = remetente
    evento["recipient"]["id"] = CONTA
    evento["message"] = {"mid": mid, "text": texto}
    return json.dumps(dados).encode()


def _eco_do_vendedor(texto: str, mid: str) -> bytes:
    dados = _payload("eco_vendedor.json")
    evento = dados["entry"][0]["messaging"][0]
    dados["entry"][0]["id"] = CONTA
    evento["sender"]["id"] = CONTA
    evento["recipient"]["id"] = CLIENTE_IG
    evento["message"]["mid"] = mid
    evento["message"]["text"] = texto
    return json.dumps(dados).encode()


def _comentario(texto: str, comment_id: str) -> bytes:
    dados = _payload("comentario_post.json")
    entrada = dados["entry"][0]
    entrada["id"] = CONTA
    entrada["time"] = int(datetime.now(timezone.utc).timestamp())
    valor = entrada["changes"][0]["value"]
    valor["id"] = comment_id
    valor["text"] = texto
    valor["from"]["id"] = CLIENTE_IG
    valor["media"]["id"] = POST
    return json.dumps(dados).encode()


def _whatsapp(numero: str, texto: str, wamid: str) -> bytes:
    agora = str(int(datetime.now(timezone.utc).timestamp()))
    return json.dumps({"object": "whatsapp_business_account", "entry": [{"id": "x", "changes": [{
        "field": "messages", "value": {"messaging_product": "whatsapp", "metadata": {"phone_number_id": PHONE_ID},
                                        "messages": [{"from": numero, "id": wamid, "timestamp": agora,
                                                      "type": "text", "text": {"body": texto}}]}}]}]}).encode()


# ------------------------------------------------------------------ o ambiente
class _Falsos:
    """Redis em memória (debounce, trava, repetidas) e o envio falso do WhatsApp."""

    def __init__(self):
        self.vistos: set = set()
        self.whatsapp: list = []

    async def aguardar_vez(self, loja_id, lead_id, texto):
        return texto, "token-bancada"

    async def liberar(self, *a, **k):
        return True

    async def nada(self, *a, **k):
        return None

    async def zero(self, *a, **k):
        return 0.0

    async def ja_processada(self, canal, mid):
        if (canal, mid) in self.vistos:
            return True
        self.vistos.add((canal, mid))
        return False

    async def enviar_wa(self, numero, texto, atraso=0, *, loja_id):
        self.whatsapp.append(texto)


def _trocar(alvo, nome, novo, trocas):
    trocas.append((alvo, nome, getattr(alvo, nome)))
    setattr(alvo, nome, novo)


def preparar_loja_instagram(roteiro: dict) -> None:
    from app import canais, lojas
    rb.apontar_banco_temporario()
    rb.preparar_loja(roteiro.get("loja"), roteiro.get("recados"))
    canais.cadastrar_canal(rb.LOJA_ID, "instagram", CONTA, "INSTAGRAM_TOKEN_BANCADA")
    canais.cadastrar_canal(rb.LOJA_ID, "whatsapp", PHONE_ID, "WA_TOKEN_BANCADA")
    lojas.salvar_config(rb.LOJA_ID, {"modulos.instagram": True, "instagram.responder_comentarios": True,
                                     "instagram.resposta_publica": True,
                                     "instagram.whatsapp_da_loja": WHATSAPP_DA_LOJA}, "bancada")
    lojas.limpar_cache()


# ------------------------------------------------------------------ um roteiro
async def rodar_roteiro_instagram(roteiro: dict, grafo, rodada) -> "rb.ResultadoRoteiro":
    from fastapi.testclient import TestClient
    import app.api.webhook as wa
    import app.api.webhook_instagram as wi
    from tests.meta_falsa import servidor_meta_falsa

    res = rb.ResultadoRoteiro(roteiro=roteiro)
    preparar_loja_instagram(roteiro)
    ig = roteiro["ig"]
    lead_id = f"ig:{CLIENTE_IG}"
    gravador = rb.GrafoGravador(grafo)
    rb._limpar_memoria(grafo, lead_id)
    falsos = _Falsos()
    trocas: list = []
    comentario = ig.get("comentario") or {}
    legendas = {POST: comentario["legenda"]} if comentario.get("legenda") else {}
    with servidor_meta_falsa(legendas, {TOKEN}) as meta:
        antes_env = {k: os.environ.get(k) for k in ("INSTAGRAM_API_URL", "INSTAGRAM_APP_SECRET", "INSTAGRAM_TOKEN_BANCADA")}
        os.environ.update({"INSTAGRAM_API_URL": meta.url, "INSTAGRAM_APP_SECRET": SEGREDO_IG,
                           "INSTAGRAM_TOKEN_BANCADA": TOKEN})
        try:
            _trocar(wi, "grafo_do_turno", lambda: gravador, trocas)
            _trocar(wi, "ESPERA_DO_ECO_S", 0, trocas)
            _trocar(wi, "ja_processada", falsos.ja_processada, trocas)
            import app.core.turno as turno_mod
            import app.redis_lock as trava
            _trocar(turno_mod, "aguardar_vez", falsos.aguardar_vez, trocas)
            _trocar(trava, "liberar_lock", falsos.liberar, trocas)
            for nome, novo in (("WHATSAPP_APP_SECRET", SEGREDO_WA), ("agente_grafo", gravador),
                               ("aguardar_vez", falsos.aguardar_vez), ("liberar_lock", falsos.liberar),
                               ("ja_processada", falsos.ja_processada), ("calcular_atraso", falsos.zero),
                               ("sinalizar_leitura", falsos.nada), ("enviar_resposta_humanizada", falsos.enviar_wa)):
                _trocar(wa, nome, novo, trocas)
            cliente = TestClient(wa.app)
            await _conversa(roteiro, res, cliente, meta, falsos, gravador, rodada, lead_id)
        finally:
            for alvo, nome, original in reversed(trocas):
                setattr(alvo, nome, original)
            for k, v in antes_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
    rb._limpar_memoria(grafo, lead_id)
    res.motivos_finais = [h["motivo"] or "" for h in rb.handoffs_abertos(lead_id)]
    res.chamados_gravados = len(rb.handoffs_abertos(lead_id))
    res.mensagens_gravadas = rb._ler("SELECT COUNT(*) n FROM mensagens WHERE loja_id = ? AND lead_id = ?",
                                     (rb.LOJA_ID, lead_id))[0]["n"]
    rb.checar(res)
    checar_instagram(res)
    return res


def _contar_tokens(res, rodada, gravador, turno):
    if gravador.ultimo is None:
        return
    do_turno = rb.mensagens_do_turno(gravador.ultimo)
    turno.tools = [c["name"] for m in do_turno for c in (getattr(m, "tool_calls", None) or [])]
    for m in do_turno:
        if m.__class__.__name__ == "ToolMessage":
            res.valores_tools |= rb.valores_em_reais(str(m.content))
    entrada, saida = rb.tokens_das(do_turno)
    res.tokens_entrada += entrada
    res.tokens_saida += saida
    rodada.tokens_entrada += entrada
    rodada.tokens_saida += saida
    turno.original = rb.resposta_do_turno(do_turno, gravador.ultimo["messages"][-1])
    turno.antes_da_tool = rb.textos_antes_da_tool(do_turno)
    turno.internos = rb.internos_do_turno(do_turno)
    turno.ficha = rb._fichas_do_turno(do_turno)
    if rb.resposta_tem_preco_inventado(turno.original, gravador.ultimo["messages"]):
        turno.barrado = turno.original


async def _conversa(roteiro, res, cliente, meta, falsos, gravador, rodada, lead_id):
    ig = roteiro["ig"]
    res.ig = {"privadas": [], "publicas": [], "mensagens": [], "whatsapp": [], "comentario_id": None}

    def _novos(desde):
        return [p for p in meta.pedidos[desde:] if p["tipo"] == "messages"]

    def _postar(caminho, corpo, segredo):
        r = cliente.post(caminho, content=corpo, headers=_assinar(corpo, segredo))
        if r.status_code != 200:
            res.falhas.append(f"o webhook respondeu {r.status_code} em {caminho}")
        if rodada.tentativas_reais:
            raise rb.EnvioRealBloqueado("; ".join(rodada.tentativas_reais))

    comentario = ig.get("comentario")
    if comentario:
        turno = rb.Turno(fala=f"[comentário no post] {comentario['texto']}"
                              + ("" if comentario.get("legenda") else " (post sem legenda de carro)"))
        desde = len(meta.pedidos)
        res.ig["comentario_id"] = "18000000000000099"
        _postar("/webhook/instagram", _comentario(comentario["texto"], res.ig["comentario_id"]), SEGREDO_IG)
        for p in meta.pedidos[desde:]:
            if p["tipo"] == "messages":
                texto = p["corpo"]["message"].get("text", "")
                turno.bolhas.append(texto)
                res.ig["mensagens"].append(texto)
                if "comment_id" in p["corpo"].get("recipient", {}):
                    res.ig["privadas"].append(texto)
            elif p["tipo"] == "replies":
                res.ig["publicas"].append(p["corpo"].get("message", ""))
        res.turnos.append(turno)

    acoes = {a["depois_da_fala"]: a for a in ig.get("acoes") or []}
    for n, fala in enumerate(roteiro["falas"], 1):
        if rodada.gasto_usd >= rodada.teto:
            res.parou_no_teto = rodada.parou_no_teto = True
            break
        turno = rb.Turno(fala=fala)
        gravador.ultimo = None
        desde = len(meta.pedidos)
        antes = len(rb.handoffs_abertos(lead_id))
        _postar("/webhook/instagram", _direct(fala, f"mid-cliente-{n}"), SEGREDO_IG)
        for p in _novos(desde):
            texto = p["corpo"]["message"].get("text", "")
            turno.bolhas.append(texto)
            res.ig["mensagens"].append(texto)
        for h in rb.handoffs_abertos(lead_id)[antes:]:
            turno.avisos_vendedor.append(h["motivo"])
        turno.silenciado = not turno.bolhas
        _contar_tokens(res, rodada, gravador, turno)
        res.turnos.append(turno)
        if n in acoes:
            _postar("/webhook/instagram", _eco_do_vendedor("Oi! Aqui é o vendedor, já te ajudo.", f"mid-vendedor-{n}"),
                    SEGREDO_IG)
            res.turnos.append(rb.Turno(fala="[o vendedor respondeu pelo app do Instagram]", silenciado=True))

    if ig.get("whatsapp"):
        from app.instagram_whatsapp import telefone_do_lead
        fone = telefone_do_lead(rb.LOJA_ID, lead_id)
        if not fone:
            res.falhas.append("o telefone dado no direct não ficou gravado (passagem para o WhatsApp)")
        else:
            for n, fala in enumerate(ig["whatsapp"], 1):
                turno = rb.Turno(fala=f"[WhatsApp, do telefone que passou] {fala}")
                gravador.ultimo = None
                desde = len(falsos.whatsapp)
                _postar("/webhook", _whatsapp(fone, fala, f"wamid.bancada{n}"), SEGREDO_WA)
                turno.bolhas = list(falsos.whatsapp[desde:])
                res.ig["whatsapp"].extend(turno.bolhas)
                _contar_tokens(res, rodada, gravador, turno)
                res.turnos.append(turno)
            from app.api_painel.leads import montar_leads
            meus = [i for i in montar_leads(rb.LOJA_ID)["itens"] if i["lead"] in (lead_id, fone)]
            res.ig["cartoes"] = meus


def checar_instagram(res) -> None:
    """As regras do Instagram (IG0/IG2/IG3), além das checagens de sempre da bancada."""
    ig, confere = res.ig, res.roteiro["ig"].get("confere") or {}
    grandes = [t for t in ig["mensagens"] if len(t.encode("utf-8")) > LIMITE_BYTES]
    if grandes:
        res.falhas.append(f"mensagem com mais de {LIMITE_BYTES} bytes ({len(grandes[0].encode('utf-8'))})")
    else:
        res.ok.append(f"todas as mensagens com até {LIMITE_BYTES} bytes")
    if res.roteiro["ig"].get("comentario"):
        if len(ig["privadas"]) > 1:
            res.falhas.append(f"{len(ig['privadas'])} mensagens privadas para um comentário só")
        elif len(ig["privadas"]) == 1:
            res.ok.append("uma mensagem privada só")
        else:
            res.falhas.append("o comentário não recebeu a mensagem privada")
        depois_da_privada = len(ig["mensagens"]) - len(ig["privadas"])
        primeiro_direct = next((t for t in res.turnos if not t.fala.startswith("[comentário")), None)
        if not res.roteiro["falas"] and depois_da_privada:
            res.falhas.append("mandou mais mensagem para a pessoa antes de ela responder")
        if primeiro_direct is None and depois_da_privada == 0:
            res.ok.append("nada mais antes de a pessoa responder")
        for texto in ig["privadas"]:
            if "R$" in texto or rb.cita_numero(texto) and "mil" in texto.lower():
                res.promessas.append(f"mensagem privada com preço: {texto!r}")
        if len(ig["publicas"]) > 1:
            res.falhas.append(f"{len(ig['publicas'])} respostas públicas para um comentário só")
    if confere.get("privada_cita"):
        alvo = confere["privada_cita"]
        if ig["privadas"] and alvo.lower() in ig["privadas"][0].lower():
            res.ok.append(f"a mensagem privada cita {alvo}")
        else:
            res.falhas.append(f"a mensagem privada não cita {alvo}")
    if confere.get("privada_texto_fixo"):
        from app.lojas import carregar_loja
        fixo = carregar_loja(rb.LOJA_ID).get("instagram.texto_private_reply") or ""
        if ig["privadas"] and ig["privadas"][0].strip() == fixo.strip():
            res.ok.append("post sem carro: texto fixo da loja")
        else:
            res.falhas.append("post sem carro: a mensagem privada não é o texto fixo da loja")
    if confere.get("link_whatsapp"):
        if any("https://wa.me/5581988887777" in t for t in ig["mensagens"]):
            res.ok.append("mandou o link do WhatsApp da loja")
        else:
            res.falhas.append("não mandou o link do WhatsApp da loja")
    if confere.get("mesmo_cliente"):
        cartoes = ig.get("cartoes") or []
        if len(cartoes) == 1 and cartoes[0]["canais"] == ["Instagram", "WhatsApp"]:
            res.ok.append("o painel mostra UM cliente com os dois canais")
        else:
            res.falhas.append(f"o painel não juntou o cliente: {[(c['lead'], c['canais']) for c in cartoes]}")
    if confere.get("silencio_depois_de"):
        n = int(confere["silencio_depois_de"])
        diretos = [t for t in res.turnos if not t.fala.startswith("[")]
        falaram = [t for t in diretos[n:] if t.bolhas]
        if falaram:
            res.falhas.append(f"o Léo falou depois de o vendedor assumir: {falaram[0].bolhas[0][:80]!r}")
        else:
            res.ok.append("silêncio depois de o vendedor assumir")
    algum = res.roteiro["ig"].get("contem_algum") or []
    if algum:
        texto = rb.normalizar(res.texto_do_leo)
        if any(rb.normalizar(a) in texto for a in algum):
            res.ok.append(f"cita {' ou '.join(algum)}")
        else:
            res.falhas.append(f"não cita {' nem '.join(algum)}")
    res.status, res.alerta = rb.decidir(res.promessas, res.falhas, res.avisos, res.roteiro.get("pendente"),
                                        res.corrigidos)


async def rodar(roteiros, grafo, teto=None):
    from app import ator
    rodada = rb.Rodada(teto=rb.teto_usd() if teto is None else teto)
    with rb.bloquear_envio_real(rodada.tentativas_reais), ator.como("Bancada", "sistema", "job"):
        for roteiro in roteiros:
            if rodada.parou_no_teto:
                rodada.resultados.append(rb.ResultadoRoteiro(roteiro=roteiro))
                continue
            try:
                rodada.resultados.append(await rodar_roteiro_instagram(roteiro, grafo, rodada))
            except rb.EnvioRealBloqueado as erro:
                rodada.abortada = str(erro)
                break
    return rodada


def main(argv=None) -> int:
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(description="Bancada do Léo pelo Instagram (Gemini real, Meta falsa).")
    parser.add_argument("--roteiro")
    args = parser.parse_args(argv)
    from dotenv import load_dotenv
    load_dotenv(RAIZ / ".env")
    chave = os.environ.get("GOOGLE_API_KEY", "")
    if not chave or chave.startswith("chave-falsa"):
        print("GOOGLE_API_KEY real não encontrada no .env. Nada foi gasto.")
        return 2
    try:
        roteiros = carregar(args.roteiro)
    except RoteiroInstagramInvalido as erro:
        print(f"Roteiro com problema: {erro}. Nada foi gasto.")
        return 2
    from app import logs
    logs.PASTA_LOGS = str(rb.pasta_temporaria() / "logs")
    rb.apontar_banco_temporario()
    import app.core.agent as agent
    from app.config import MODELO_LLM
    try:
        rodada = asyncio.run(rodar(roteiros, agent.agente_grafo))
    finally:
        shutil.rmtree(rb.pasta_temporaria(), ignore_errors=True)
        import banco
        banco.fechar_pools()                  # sem isso o Python espera as linhas do pool ao sair
    texto = rb.montar_relatorio(rodada, MODELO_LLM).replace("# Bancada do Léo", "# Bancada do Léo pelo INSTAGRAM", 1)
    texto += _anexo_instagram(rodada)
    caminho = rb.salvar_relatorio(texto)
    novo = caminho.with_name(caminho.name.replace("rodada_", "instagram_"))
    caminho.rename(novo)
    print(f"\nRelatório: {novo}")
    if rodada.abortada:
        print(f"BANCADA ABORTADA: {rodada.abortada}")
        return 3
    for res in rodada.resultados:
        print(f"  {rb._linha_status(res):<20} {res.roteiro['nome']}")
    print(f"Custo total: US$ {rodada.gasto_usd:.4f} (teto US$ {rodada.teto:.2f})")
    return 1 if any(r.status == rb.FALHOU for r in rodada.resultados) else 0


def _anexo_instagram(rodada) -> str:
    linhas = ["", "## O que a Meta (falsa) recebeu, por roteiro", ""]
    for res in rodada.resultados:
        ig = getattr(res, "ig", None)
        if not ig:
            continue
        linhas.append(f"### {res.roteiro['nome']}")
        for t in ig["privadas"]:
            linhas.append(f"- mensagem privada ({len(t.encode('utf-8'))} bytes): {t}")
        for t in ig["publicas"]:
            linhas.append(f"- resposta pública: {t}")
        for t in ig["whatsapp"]:
            linhas.append(f"- WhatsApp (envio falso): {t}")
        for c in ig.get("cartoes") or []:
            linhas.append(f"- painel: {c['lead']} canais={c['canais']} como_chegou={c.get('como_chegou')}")
        linhas.append("")
    return "\n".join(linhas)


if __name__ == "__main__":
    import banco as _banco                  # SE3: este programa vê todas as lojas (modo sistema)
    _banco.declarar_sistema("scripts/bancada_instagram.py")
    sys.exit(main())
