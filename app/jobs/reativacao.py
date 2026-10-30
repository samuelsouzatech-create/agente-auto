"""
Job de reativação (Etapa 2, Bloco 6C). Roda no relógio (python -m app.jobs.runner), a cada 5 min.

Para cada loja com remarketing ligado, dentro do horário de envio, pega a fila
montada no painel, CONFERE DE NOVO cada contato e manda o modelo aprovado
(reativacao_cliente se há compra registrada, senão reativacao_contato).
Conta no mesmo limite mensal do remarketing.

SIMULAÇÃO é o padrão. Envio de verdade só com REATIVACAO_ENVIO_REAL=1 e só pelo runner.

Ver o que sairia, sem enviar nada:
    python -m app.jobs.reativacao --loja 1
    python -m app.jobs.reativacao --loja 1 --agora 2026-11-02T10:00
"""
from __future__ import annotations

import argparse
import asyncio
import os
import time
import uuid
from datetime import datetime, timedelta, timezone

import banco
from banco import conectar
from app import config  # noqa: F401  (carrega o .env)
from app import reativacao as rv
from app.base_pos_venda import lead_da_base
from app.custos import Uso, registrar_uso
from app.elegibilidade import no_horario_de_envio, vagas_no_mes
from app.jobs.remarketing import EnviadorReal, _ler_agora
from app.lojas import Loja, carregar_loja, modulo_ativo
from app.pausa import pausado
from app.modo_envio import real_para
from app.relogio import agora_utc, para_banco
from app.templates import (
    ModeloInexistente, ModeloInvalido, ValoresFaltando, categoria_para_custo,
    modelo_aprovado, modelo_do_segmento, preencher,
)

INTERVALO_S = 300
MAX_POR_RODADA = 10
PAUSA_ENTRE_ENVIOS_S = 3
MAX_TENTATIVAS = 3
REPETIR_FALHA_APOS = timedelta(hours=6)
ADIAR = {"com_vendedor"}               # volta a tentar depois
ESTADOS = ("enviado", "simulado", "falhou", "bloqueado", "cancelado", "adiado", "erro")
_ROTULO = {"enviado": "ENVIADO", "simulado": "SIMULADO (nada saiu)", "falhou": "FALHOU",
           "bloqueado": "BLOQUEADO", "cancelado": "CANCELADO"}


def envio_real_ligado() -> bool:
    return (os.getenv("REATIVACAO_ENVIO_REAL") or "").strip().lower() in ("1", "true", "sim", "yes")


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _ids_lojas_ativas() -> list[int]:
    from app.lojas_admin import listar_lojas
    return [l["id"] for l in listar_lojas() if l["ativo"]]


def _fila(loja_id, agora: datetime, real: bool) -> list[dict]:
    conexao = conectar()
    try:
        linhas = conexao.execute(
            "SELECT r.*, c.nome AS nome_contato, c.consentimento AS consentimento "
            "FROM reativacao r LEFT JOIN contatos c ON c.loja_id = r.loja_id AND c.telefone = r.telefone "
            "WHERE r.loja_id = ? AND (r.estado = 'na_fila' "
            "OR (? = 1 AND r.estado = 'simulado') "
            "OR (? = 1 AND r.estado = 'falhou' AND r.atualizado_em <= ?)) ORDER BY r.id",
            (loja_id, int(real), int(real), para_banco(agora - REPETIR_FALHA_APOS))).fetchall()
    finally:
        conexao.close()
    return [dict(l) for l in linhas]


def _atualizar(loja_id, id_linha: int, agora: datetime, **campos) -> None:
    campos["atualizado_em"] = para_banco(agora)
    nomes = ", ".join(f"{k} = ?" for k in campos)
    conexao = conectar()
    try:
        conexao.execute(f"UPDATE reativacao SET {nomes} WHERE id = ? AND loja_id = ?",
                        (*campos.values(), id_linha, loja_id))
        conexao.commit()
    finally:
        conexao.close()


def _gravar_na_conversa(loja_id, lead_id: str, texto: str, agora: datetime) -> None:
    """Aparece no painel e na memória do assistente, como fala da loja."""
    conexao = conectar()
    try:
        conexao.execute(
            "INSERT INTO mensagens (lead_id, loja_id, canal, direcao, tipo, conteudo, autor, criado_em) "
            "VALUES (?, ?, 'whatsapp', 'leo', 'texto', ?, 'reativacao', ?)",
            (lead_id, loja_id, texto, para_banco(agora)))
        conexao.commit()
    finally:
        conexao.close()


def _marcar(loja: Loja, linha: dict, agora: datetime, estado: str, **campos) -> str:
    _atualizar(loja.id, linha["id"], agora, estado=estado, **campos)
    motivo = campos.get("motivo")
    print(f"[Reativação][loja {loja.id}] {_ROTULO[estado]} -> {linha['telefone']}"
          + (f" | {rv.MOTIVOS.get(motivo, motivo)}" if motivo else ""))
    if campos.get("texto") and estado in ("simulado", "enviado"):
        print(f'    "{campos["texto"]}"')
    return estado


def processar(loja: Loja, linha: dict, agora: datetime, foto: rv.Fotografia, *,
              real: bool, enviador) -> str:
    if linha["consentimento"] is None:
        return _marcar(loja, linha, agora, "cancelado", motivo="sem_contato")
    contato = {"telefone": linha["telefone"], "consentimento": linha["consentimento"]}
    motivo = rv.motivo_para_nao_reativar(foto, contato, agora, int(linha["meses_inativo"]))
    if motivo in ADIAR:
        return "adiado"
    if motivo:
        return _marcar(loja, linha, agora, "cancelado", motivo=motivo)

    lead_id = lead_da_base(loja.id, linha["telefone"])
    partes = (linha["nome_contato"] or "").split()
    compra = rv.ultima_compra(loja.id, linha["telefone"])
    nome_modelo = rv.MODELO_CLIENTE if compra and compra["descricao"] else rv.MODELO_CONTATO
    try:
        modelo = modelo_do_segmento(loja.segmento, nome_modelo)
    except (ModeloInexistente, ModeloInvalido):
        return _marcar(loja, linha, agora, "bloqueado", motivo="sem_modelo", modelo=nome_modelo)
    valores = {"nome": partes[0] if partes else "", "agente": loja.get("nome_agente") or "Léo",
               "loja": loja.nome, "carro": compra["descricao"] if compra else ""}
    try:
        texto = preencher(modelo, valores)
    except ValoresFaltando:
        return _marcar(loja, linha, agora, "bloqueado", motivo="faltam_dados", modelo=modelo.nome)
    categoria = categoria_para_custo(loja.id, modelo)
    base = dict(lead_id=lead_id, modelo=modelo.nome, categoria=categoria, texto=texto)

    if not real:
        return _marcar(loja, linha, agora, "simulado", motivo=None, **base)
    if not modelo_aprovado(loja.id, modelo.nome, modelo.idioma):
        return _marcar(loja, linha, agora, "bloqueado", motivo="modelo_nao_aprovado", **base)

    resultado = asyncio.run(enviador.modelo(loja.id, lead_id, modelo, valores))
    if resultado.ok:
        execucao_id = uuid.uuid4().hex
        registro = registrar_uso(
            loja.id, lead_id, "whatsapp", Uso(), tipo="reativacao",
            msgs_utilidade=1 if categoria == "utilidade" else 0,
            msgs_marketing=1 if categoria == "marketing" else 0,
            execucao_id=execucao_id, agora=agora)
        _gravar_na_conversa(loja.id, lead_id, texto, agora)
        return _marcar(loja, linha, agora, "enviado", motivo=None, detalhe=None,
                       enviado_em=para_banco(agora), execucao_id=execucao_id,
                       custo_meta=registro["custo_meta"] if registro else None, **base)
    tentativas = int(linha["tentativas"] or 0) + 1
    detalhe = str(getattr(resultado, "detalhe", "") or "")[:300]
    if tentativas >= MAX_TENTATIVAS:
        return _marcar(loja, linha, agora, "bloqueado", motivo="falhas_repetidas",
                       tentativas=tentativas, detalhe=detalhe, **base)
    return _marcar(loja, linha, agora, "falhou", motivo="erro_no_envio",
                   tentativas=tentativas, detalhe=detalhe, **base)


def rodar_reativacao(agora: datetime | None = None, *, envio_real: bool | None = None,
                     enviador=None, pausa_s: float | None = None,
                     max_por_loja: int = MAX_POR_RODADA, lojas: list[int] | None = None) -> dict:
    agora = _utc(agora or agora_utc())
    enviador = enviador or EnviadorReal()
    pausa = PAUSA_ENTRE_ENVIOS_S if pausa_s is None else pausa_s
    totais = dict.fromkeys(ESTADOS, 0)

    for loja_id in (lojas or _ids_lojas_ativas()):
        try:
            loja = carregar_loja(loja_id)
            if not loja.ativo or not modulo_ativo(loja, "remarketing") or pausado(loja_id):
                continue
            if not no_horario_de_envio(loja, agora):
                continue
            real = real_para(loja, "reativacao", envio_real)
            fila = _fila(loja_id, agora, real)
            if not fila:
                continue
            foto = rv.fotografia(loja_id, agora)
            vagas = min(max_por_loja, vagas_no_mes(loja_id, agora))
        except Exception as erro:          # uma loja com problema não trava as outras
            print(f"[Reativação] Erro na loja {loja_id}: {erro!r}")
            continue
        feitos = 0
        for linha in fila:
            if feitos >= vagas:
                break
            try:
                estado = processar(loja, linha, agora, foto, real=real, enviador=enviador)
            except Exception as erro:
                print(f"[Reativação][loja {loja_id}] Erro com {linha['telefone']}: {erro!r}")
                estado = "erro"
            totais[estado] += 1
            if estado not in ("cancelado", "adiado"):
                feitos += 1
            if estado == "enviado" and pausa:
                time.sleep(pausa)
    return totais


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Reativação em SIMULAÇÃO (não envia nada).")
    parser.add_argument("--loja", type=int, help="só esta loja")
    parser.add_argument("--agora", help='fingir outra hora, no horário da loja: "2026-11-02T10:00"')
    args = parser.parse_args(argv)

    banco.criar_tabelas()
    agora = _ler_agora(args.agora)
    ids = [args.loja] if args.loja else _ids_lojas_ativas()
    print(f"[Reativação] SIMULAÇÃO: nada é enviado. Hora usada (UTC): {agora:%Y-%m-%d %H:%M}")
    for loja_id in ids:
        print(f"Loja {loja_id}: {rv.resumo(loja_id)}")
    totais = rodar_reativacao(agora, envio_real=False, lojas=ids, pausa_s=0)
    print(f"\n[Reativação] Resultado: {totais}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
