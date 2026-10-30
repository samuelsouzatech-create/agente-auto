"""
Job de pós-venda (Etapa 2, Bloco 5A): manda os passos da régua na data certa.
Roda no relógio (python -m app.jobs.runner), a cada 5 minutos.

Antes de cada passo vencido, confere de novo:
  - pediu para não ser procurado / sem interesse -> cancelado
  - pediu um tempo -> reagendado para a data que ele pediu
  - atendimento aberto com vendedor:
        motivo "PÓS-VENDA: ..." (problema com a compra) -> cancela os passos futuros
        outro motivo -> espera e tenta no próximo ciclo
  - fora do horário de envio -> espera
Como manda:
  - Telegram, ou WhatsApp com a janela de 24 h aberta: o texto do modelo como mensagem normal.
  - WhatsApp com a janela fechada: o modelo aprovado pela Meta. Sem aprovação, não sai.

SIMULAÇÃO é o padrão e não grava envio. Envio real só com POS_VENDA_ENVIO_REAL=1.
Cancelamentos e reagendamentos são gravados nos dois modos.

Ver o que sairia, sem enviar:
    python -m app.jobs.pos_venda --loja 1
    python -m app.jobs.pos_venda --loja 1 --agora 2026-12-01T10:00
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import unicodedata
import uuid
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import banco
from banco import conectar
from app import config  # noqa: F401  (carrega o .env)
from app import base_pos_venda, regua, vendas
from app.pausa import pausado
from app.custos import Uso, registrar_uso
from app.elegibilidade import no_horario_de_envio, proxima_abertura
from app.interesse import pode_contatar, situacao_do_lead
from app.janela import janela_aberta
from app.lojas import PADROES, Loja, carregar_loja, modulo_ativo
from app.relogio import agora_utc, dia_local, do_banco, fuso, hora_local, para_banco
from app.templates import (
    ModeloInexistente, ModeloInvalido, ValoresFaltando, categoria_para_custo,
    modelo_aprovado, modelo_do_segmento, preencher,
)

INTERVALO_S = 300
MAX_POR_RODADA = 20
MAX_TENTATIVAS = 3
REPETIR_FALHA_APOS = timedelta(hours=6)
CANAIS = ("whatsapp", "telegram")
CANAIS_COBRADOS = {"whatsapp"}
MODELO_REVISAO = "pos_venda_revisao"
MODELO_REVISAO_OFICINA = "pos_venda_revisao_oficina"
ESTADOS = ("enviado", "avisado", "simulado", "adiado", "cancelado", "bloqueado", "falhou", "erro")

MOTIVOS = {
    **regua.MOTIVOS,
    **base_pos_venda.MOTIVOS,
    "sem_canal": "O cliente nunca conversou pelo WhatsApp ou Telegram",
    "sem_modelo": "O segmento não tem o modelo deste passo",
    "faltam_dados": "Falta o nome do cliente para o modelo",
    "modelo_nao_aprovado": "Modelo ainda não aprovado pela Meta nesta loja",
    "erro_no_envio": "O canal recusou o envio (tenta de novo em 6 h)",
    "falhas_repetidas": "Falhou 3 vezes; precisa de alguém olhar",
    "pediu_tempo": "Pediu um tempo; reagendado",
}
ROTULOS = {"enviado": "ENVIADO", "avisado": "AVISADO", "simulado": "SIMULADO (nada saiu)",
           "cancelado": "CANCELADO", "bloqueado": "BLOQUEADO", "falhou": "FALHOU"}


def envio_real_ligado() -> bool:
    return (os.getenv("POS_VENDA_ENVIO_REAL") or "").strip().lower() in ("1", "true", "sim", "yes")


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def e_pos_venda(motivo) -> bool:
    """O handoff foi aberto por problema com a compra? (motivo começa com PÓS-VENDA)"""
    texto = unicodedata.normalize("NFD", str(motivo or ""))
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn").upper().strip()
    return texto.startswith(("POS-VENDA", "POS VENDA", "POSVENDA"))


# ------------------------------------------------------------ banco

def _um(sql: str, parametros: tuple):
    conexao = conectar()
    try:
        return conexao.execute(sql, parametros).fetchone()
    finally:
        conexao.close()


def _canal_do_lead(loja_id: int, lead_id: str) -> str | None:
    linha = _um("SELECT canal FROM mensagens WHERE loja_id = ? AND lead_id = ? "
                "AND canal IN ('whatsapp', 'telegram') ORDER BY id DESC LIMIT 1", (loja_id, lead_id))
    return linha["canal"] if linha else None


def _handoff_aberto(loja_id: int, lead_id: str):
    return _um("SELECT motivo FROM handoffs WHERE loja_id = ? AND lead_id = ? "
               "AND estado != 'encerrado' ORDER BY id DESC LIMIT 1", (loja_id, lead_id))


def _contexto(e: dict) -> dict:
    try:
        dados = json.loads(e.get("contexto") or "{}")
        return dados if isinstance(dados, dict) else {}
    except (TypeError, ValueError):
        return {}


def _atualizar(loja_id: int, execucao_id: int, estado: str, agora: datetime, *, motivo=None,
               modelo=None, categoria=None, contexto=None, custo_meta=None, id_custo=None,
               agendado_para=None) -> None:
    final = estado != "agendado"
    conexao = conectar()
    try:
        conexao.execute(
            """UPDATE regua_execucoes SET estado = ?, motivo = ?,
                   modelo = COALESCE(?, modelo), categoria = COALESCE(?, categoria),
                   contexto = COALESCE(?, contexto), custo_meta = COALESCE(?, custo_meta),
                   execucao_id = COALESCE(?, execucao_id),
                   agendado_para = COALESCE(?, agendado_para), executado_em = ?
               WHERE id = ? AND loja_id = ? AND estado = 'agendado'""",
            (estado, motivo, modelo, categoria,
             json.dumps(contexto, ensure_ascii=False) if contexto is not None else None,
             custo_meta, id_custo, para_banco(agendado_para) if agendado_para else None,
             para_banco(agora) if final else None, execucao_id, loja_id))
        conexao.commit()
    finally:
        conexao.close()


def _gravar_na_conversa(loja_id: int, lead_id: str, canal: str, texto: str, agora: datetime) -> None:
    conexao = conectar()
    try:
        conexao.execute(
            "INSERT INTO mensagens (lead_id, loja_id, canal, direcao, tipo, conteudo, autor, criado_em) "
            "VALUES (?, ?, ?, 'leo', 'texto', ?, 'pos_venda', ?)",
            (lead_id, loja_id, canal, texto, para_banco(agora)))
        conexao.commit()
    finally:
        conexao.close()


# ------------------------------------------------------------ texto

def _primeiro_nome(nome) -> str:
    partes = str(nome or "").split()
    return partes[0] if partes else ""


def _valores(loja: Loja, e: dict) -> dict:
    lead = _um("SELECT nome FROM leads WHERE loja_id = ? AND lead_id = ?", (loja.id, e["lead_id"]))
    nome = (lead["nome"] if lead else "") or base_pos_venda.nome_do_contato(loja.id, e["lead_id"])
    valores = {
        "nome": _primeiro_nome(nome),
        "agente": loja.get("nome_agente") or "Léo",
        "loja": loja.nome,
        "oficina": str(loja.get("pos_venda.oficina_parceira") or "").strip(),
    }
    if e["evento_tipo"] == vendas.EVENTO:
        valores.update(vendas.valores_da_venda(loja.id, e["evento_id"]))
    elif e["evento_tipo"] == base_pos_venda.EVENTO:
        valores.update(base_pos_venda.valores_da_compra(loja.id, e["evento_id"]))
    return valores


def _escolher_modelo(loja: Loja, nome: str, valores: dict):
    if nome == MODELO_REVISAO and valores.get("oficina"):
        nome = MODELO_REVISAO_OFICINA
    return modelo_do_segmento(loja.segmento, nome)


def _texto_livre(modelo, valores: dict) -> str:
    """Texto do modelo como mensagem normal. Sem nome, cumprimenta sem nome."""
    texto = modelo.texto
    if not (valores.get("nome") or "").strip():
        texto = texto.replace("Oi, {nome}!", "Oi!").replace(", {nome}", "")
    variaveis = tuple(v for v in modelo.variaveis if "{" + v + "}" in texto)
    return preencher(replace(modelo, texto=texto, variaveis=variaveis), valores)


# ------------------------------------------------------------ um passo

def _avisar_vendedor(loja: Loja, e: dict, valores: dict, *, real: bool, registrar) -> str:
    texto = (f"📅 {loja.nome}: hora do passo '{e['passo_nome']}' do pós-venda.\n"
             f"Cliente: {valores.get('nome') or e['lead_id']}"
             + (f" ({valores['carro']})" if valores.get("carro") else ""))
    if not real:
        return registrar("simulado", texto=texto)
    from app import avisos
    from app.usuarios import contatos_para_aviso
    chats = ([u["contato_telegram"] for u in contatos_para_aviso(loja.id, "vendedor")]
             or [u["contato_telegram"] for u in contatos_para_aviso(loja.id, "gestor")])
    r = avisos.avisar_uma_vez(loja.id, "pos_venda", f"regua:{e['id']}", chats, texto)
    if r.get("concluido"):
        return registrar("avisado", contexto={"texto": texto})
    return registrar("falhou", "erro_no_envio", contexto={"texto": texto})


def processar(loja: Loja, e: dict, agora: datetime, *, real: bool, enviador) -> str:
    if e["evento_tipo"] == base_pos_venda.EVENTO:          # Bloco 6B
        e = base_pos_venda.sincronizar_lead(loja.id, e)
    lead_id, passo = e["lead_id"], e["passo_nome"]


    def registrar(estado, motivo=None, texto="", **extra) -> str:
        if real or estado == "cancelado":
            _atualizar(loja.id, e["id"], estado, agora, motivo=motivo, **extra)
        print(f"[Pós-venda][loja {loja.id}] {ROTULOS.get(estado, estado)} {passo} -> {lead_id}"
              + (f" | {MOTIVOS.get(motivo, motivo)}" if motivo else ""))
        if texto:
            print(f'    "{texto}"')
        return estado

    def adiar(quando, motivo, contexto=None) -> str:
        _atualizar(loja.id, e["id"], "agendado", agora, motivo=motivo,
                   agendado_para=quando, contexto=contexto)
        print(f"[Pós-venda][loja {loja.id}] REAGENDADO {passo} -> {lead_id} "
              f"para {hora_local(loja, quando):%d/%m %H:%M} | {MOTIVOS.get(motivo, motivo)}")
        return "adiado"

    if not e["passo_ativo"]:
        return registrar("cancelado", "passo_desligado")
    if e["evento_tipo"] == base_pos_venda.EVENTO:          # Bloco 6B: autorização conferida de novo
        barrado = base_pos_venda.motivo_para_nao_enviar(loja.id, e["evento_id"])
        if barrado:
            return registrar("cancelado", barrado)
    if not pode_contatar(loja.id, lead_id, dia_local(loja, agora)):
        s = situacao_do_lead(loja.id, lead_id)
        if s and s["situacao"] == "pediu_tempo" and s.get("retomar_em"):
            volta = datetime.combine(date.fromisoformat(s["retomar_em"]), regua.HORA_DO_ENVIO,
                                     tzinfo=fuso(loja))
            return adiar(proxima_abertura(loja, volta), "pediu_tempo")
        return registrar("cancelado", s["situacao"] if s else "nao_contatar")
    aberto = _handoff_aberto(loja.id, lead_id)
    if aberto:
        if e_pos_venda(aberto["motivo"]):
            n = regua.cancelar_futuros(loja.id, lead_id, "problema")
            print(f"[Pós-venda][loja {loja.id}] {lead_id} relatou problema: {n} passo(s) cancelado(s).")
            return "cancelado"
        return "adiado"                    # vendedor no meio: tenta no próximo ciclo
    if not no_horario_de_envio(loja, agora):
        return "adiado"

    valores = _valores(loja, e)
    if e["acao"] == "avisar_vendedor":
        return _avisar_vendedor(loja, e, valores, real=real, registrar=registrar)

    canal = _canal_do_lead(loja.id, lead_id)
    if canal is None and e["evento_tipo"] == base_pos_venda.EVENTO:
        canal = "whatsapp"          # contato da base: só por modelo aprovado da Meta
    if canal is None:
        return registrar("bloqueado", "sem_canal")
    try:
        modelo = _escolher_modelo(loja, e["modelo"], valores)
    except (ModeloInexistente, ModeloInvalido):
        return registrar("bloqueado", "sem_modelo")
    aberta = janela_aberta(loja.id, lead_id, canal, agora)
    try:
        texto = _texto_livre(modelo, valores) if aberta else preencher(modelo, valores)
    except ValoresFaltando:
        return registrar("bloqueado", "faltam_dados", modelo=modelo.nome)
    categoria = "livre" if aberta else categoria_para_custo(loja.id, modelo)
    contexto = {"texto": texto, "canal": canal, "janela_aberta": bool(aberta),
                "modo": "real" if real else "simulacao"}
    comum = dict(modelo=modelo.nome, categoria=categoria)
    if not real:
        return registrar("simulado", texto=texto, contexto=contexto, **comum)
    if not aberta and not modelo_aprovado(loja.id, modelo.nome, modelo.idioma):
        return registrar("bloqueado", "modelo_nao_aprovado", contexto=contexto, **comum)
    if aberta:
        resultado = asyncio.run(enviador.texto(loja.id, canal, lead_id, texto))
    else:
        resultado = asyncio.run(enviador.modelo(loja.id, lead_id, modelo, valores))

    if resultado.ok:
        id_custo = uuid.uuid4().hex
        registro = registrar_uso(
            loja.id, lead_id, canal, Uso(), tipo="pos_venda",
            msgs_servico=1 if categoria == "livre" and canal in CANAIS_COBRADOS else 0,
            msgs_utilidade=1 if categoria == "utilidade" else 0,
            msgs_marketing=1 if categoria == "marketing" else 0,
            execucao_id=id_custo, agora=agora)
        _gravar_na_conversa(loja.id, lead_id, canal, texto, agora)
        return registrar("enviado", texto=texto, contexto=contexto, id_custo=id_custo,
                         custo_meta=registro["custo_meta"] if registro else None, **comum)

    tentativas = int(_contexto(e).get("tentativas") or 0) + 1
    contexto.update(tentativas=tentativas, detalhe=(resultado.detalhe or "")[:300])
    if tentativas >= MAX_TENTATIVAS:
        return registrar("falhou", "falhas_repetidas", contexto=contexto, **comum)
    return adiar(agora + REPETIR_FALHA_APOS, "erro_no_envio", contexto)


# ------------------------------------------------------------ rodada

def _ids_lojas_ativas() -> list[int]:
    from app.lojas_admin import listar_lojas
    return [l["id"] for l in listar_lojas() if l["ativo"]]


def rodar_pos_venda(agora: datetime | None = None, *, envio_real: bool | None = None,
                    enviador=None, lojas: list[int] | None = None,
                    max_por_loja: int = MAX_POR_RODADA) -> dict:
    agora = _utc(agora or agora_utc())
    real = envio_real_ligado() if envio_real is None else bool(envio_real)
    if enviador is None:
        from app.jobs.remarketing import EnviadorReal
        enviador = EnviadorReal()
    totais = dict.fromkeys(ESTADOS, 0)
    for loja_id in (lojas or _ids_lojas_ativas()):
        try:
            loja = carregar_loja(loja_id)
            if not loja.ativo or not modulo_ativo(loja, "pos_venda") or pausado(loja_id):
                continue
            fila = regua.vencidas(loja_id, agora, max_por_loja)
        except Exception as erro:          # uma loja com problema não trava as outras
            print(f"[Pós-venda] Erro na loja {loja_id}: {erro!r}")
            continue
        for e in fila:
            try:
                estado = processar(loja, e, agora, real=real, enviador=enviador)
            except Exception as erro:
                print(f"[Pós-venda][loja {loja_id}] Erro com {e['lead_id']}: {erro!r}")
                estado = "erro"
            totais[estado] += 1
    return totais


# ------------------------------------------------------------ linha de comando (só simulação)

def _ler_agora(texto: str | None) -> datetime:
    if not texto:
        return agora_utc()
    dt = datetime.fromisoformat(texto)
    if dt.tzinfo is None:                  # horário da loja
        dt = dt.replace(tzinfo=ZoneInfo(PADROES["fuso"]))
    return _utc(dt)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Pós-venda em SIMULAÇÃO (não envia nada).")
    parser.add_argument("--loja", type=int, help="só esta loja")
    parser.add_argument("--agora", help='fingir outra hora, no horário da loja: "2026-12-01T10:00"')
    args = parser.parse_args(argv)

    banco.criar_tabelas()
    agora = _ler_agora(args.agora)
    ids = [args.loja] if args.loja else _ids_lojas_ativas()
    print(f"[Pós-venda] SIMULAÇÃO: nada é enviado. Hora usada (UTC): {agora:%Y-%m-%d %H:%M}")
    for loja_id in ids:
        loja = carregar_loja(loja_id)
        if not modulo_ativo(loja, "pos_venda"):
            print(f"\nLoja {loja_id}: pós-venda DESLIGADO (ligue em Plano e limites).")
            continue
        print(f"\nLoja {loja_id} - passos agendados (horário da loja):")
        lista = regua.agendados(loja_id, 50)
        if not lista:
            print("  (nenhum)")
        for p in lista:
            quando = hora_local(loja, do_banco(p["agendado_para"]))
            print(f"  {quando:%d/%m/%Y %H:%M}  {p['passo_nome']:<17} {p['lead_id']}")
    print()
    totais = rodar_pos_venda(agora, envio_real=False, lojas=ids)
    print(f"\n[Pós-venda] Resultado: {totais}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
