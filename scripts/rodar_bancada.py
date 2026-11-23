"""
Bancada de testes do Léo (Bloco B1).

Roda conversas completas, escritas em YAML (bancada/roteiros/), pelo motor
real (executar_turno, canal simulador) com o Gemini real. Nada sai para fora:
  - cada roteiro usa uma loja fictícia num banco SQLite TEMPORÁRIO (nunca o loja.db);
  - o envio é o do canal simulador (vira registro no relatório);
  - qualquer tentativa de falar com WhatsApp, Instagram ou Telegram aborta a rodada.

Uso (PowerShell, na raiz do projeto):
    .venv-teste\\Scripts\\python scripts\\rodar_bancada.py
    .venv-teste\\Scripts\\python scripts\\rodar_bancada.py --roteiro desconto

Teto de gasto: LEO_API_TETO_USD (padrão 0.50). Passou do teto, a rodada para.
Relatório: logs/bancada/rodada_<data>.md (fora do Git).

Resultados por roteiro: PASSOU, AVISO, FALHOU, PENDENTE (Lx).
  - roteiro com "pendente" que falha = PENDENTE (esperado, não reprova a rodada);
  - roteiro com "pendente" que passa = PASSOU com alerta para tirar o pendente;
  - falha de promessa (preço inventado, crédito, desconto, valor de troca) = FALHOU sempre.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import sys
import tempfile
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import banco  # noqa: E402
import yaml  # noqa: E402
from langchain_core.messages import AIMessage  # noqa: E402

from app import ator, lojas, logs  # noqa: E402
from app.guarda_politica import (  # noqa: E402
    numeros_do_cliente, resposta_tem_preco_inventado, valores_em_reais,
)
from app.recados import termos_da_condicao  # noqa: E402
from app.core.turno import _agenda_do_turno, _fichas_do_turno, internos_do_turno, resposta_do_turno  # noqa: E402
from app.guarda_politica import FRASES_PROIBIDAS, ELOGIO_DO_ESTADO  # noqa: E402
from app.naturalidade import parece_robotica  # noqa: E402
from app.utils import extrair_texto, mensagens_do_turno  # noqa: E402

PASTA_ROTEIROS = RAIZ / "bancada" / "roteiros"
PASTA_IMAGENS = RAIZ / "bancada" / "imagens"
PASTA_RELATORIO = RAIZ / "logs" / "bancada"
BANCO_REAL = (RAIZ / "loja.db").resolve()

CANAL = "simulador"
LOJA_ID = 1
NOME_LOJA = "Auto Bancada Recife (loja fictícia)"
CONFIG_LOJA = {
    "cidade": "Recife",
    "endereco": "Av. Domingos Ferreira, 1000, Boa Viagem",
    "aceita_troca": "sim",                     # L5c: vem do cadastro (não da base de conhecimento)
    "atendimento": {"horario_semana": {
        "0": "08:00-18:00", "1": "08:00-18:00", "2": "08:00-18:00",
        "3": "08:00-18:00", "4": "08:00-18:00", "5": "08:00-13:00"}},
}
# Equipe da loja fictícia (o roteiro do dono usa este número como remetente).
EQUIPE = [
    ("Carlos (dono)", "dono", None, "5581999990001"),
    ("Vendedor Bancada", "vendedor", "100000001", "5581999990002"),
]
ESTOQUE = [
    ("Honda", "Civic", 2019, 48000, "Branco", "Automático", 98000.00, "disponivel"),
    ("Toyota", "Corolla", 2021, 32000, "Preto", "Automático", 135000.00, "disponivel"),
    ("Volkswagen", "Gol", 2018, 65000, "Branco", "Manual", 42000.00, "disponivel"),
    ("Chevrolet", "Onix", 2020, 40000, "Vermelho", "Automático", 68000.00, "disponivel"),
    ("Hyundai", "HB20", 2019, 55000, "Prata", "Manual", 54000.00, "disponivel"),
    ("Jeep", "Renegade", 2020, 51000, "Cinza", "Automático", 89900.00, "disponivel"),
]

# Preço do Gemini 3.1 Flash-Lite (US$ por 1 milhão de tokens), o mesmo dos testes -m api.
PRECO_ENTRADA_USD_MILHAO = 0.25
PRECO_SAIDA_USD_MILHAO = 1.50
PRECO_AUDIO_USD_MILHAO = 0.50     # M3: tokens de áudio (entrada), estimativa conservadora
TETO_PADRAO_USD = 0.50

PASSOU, AVISO, FALHOU, PENDENTE, NAO_RODOU = "PASSOU", "AVISO", "FALHOU", "PENDENTE", "NÃO RODOU"
CORRIGIDO = "CORRIGIDO"     # M1: a guarda do código corrigiu o modelo e o cliente recebeu texto certo
ALERTA_PENDENTE = "PASSOU — remova o pendente e marque feito em docs/fase_cerebro.md"
IMAGEM_AUSENTE = "imagem ausente"
AUDIO_AUSENTE = "áudio ausente"     # M3

CAMPOS_ROTEIRO = {"nome", "falas", "remetente", "imagem", "audio", "deve", "nao_pode", "pendente", "loja",
                  "recados", "nao_contem", "imagem_texto", "legenda",
                  "canal", "conversa", "interesse", "venda", "passos",      # L6: roteiros de job
                  "rajada",                                                 # L7: mensagens seguidas
                  "conhecimento"}                                           # L11: base própria do roteiro
CAMPOS_DEVE = {"tools", "handoff", "contem", "contem_na_fala", "handoff_ate_fala", "motivo_contem", "vira_lead",
               "toques", "envios_pos_venda", "textos_diferentes", "envios_no_horario",   # L6
               "fotos", "fotos_de", "respostas",                                          # L7
               "trocas",                                                                  # L8
               "envios", "sugestoes_sombra",                                              # L9
               "silencio_no_fim"}                                                         # M2
NAO_PODE_VALIDOS = {"preco_inventado", "credito", "desconto", "valor_troca", "endereco",
                    "condicao_recado", "numero", "regra_entrada", "elogio_estado"}

# Domínios dos canais reais. Qualquer pedido para eles aborta a rodada.
HOSTS_PROIBIDOS = ("facebook.com", "instagram.com", "telegram.org", "whatsapp.com", "whatsapp.net")


class RoteiroInvalido(ValueError):
    pass


class EnvioRealBloqueado(RuntimeError):
    pass


# ======================================================================
# ROTEIROS (YAML)
# ======================================================================

def _sim_nao(valor, campo):
    if isinstance(valor, bool):
        return valor
    texto = normalizar(valor)
    if texto in ("sim", "s", "true"):
        return True
    if texto in ("nao", "n", "false"):
        return False
    raise RoteiroInvalido(f"'{campo}' deve ser sim ou não (veio {valor!r})")


def validar_roteiro(dados, origem: str = "") -> dict:
    if not isinstance(dados, dict):
        raise RoteiroInvalido(f"{origem}: o roteiro precisa ser um mapa YAML")
    extras = set(dados) - CAMPOS_ROTEIRO
    if extras:
        raise RoteiroInvalido(f"{origem}: campos desconhecidos {sorted(extras)}")
    nome = str(dados.get("nome") or "").strip()
    falas = dados.get("falas")
    if not nome:
        raise RoteiroInvalido(f"{origem}: falta 'nome'")
    tem_imagem = bool(dados.get("imagem") or dados.get("imagem_texto") or dados.get("audio"))   # M3: áudio
    e_job = "passos" in dados                      # L6: roteiro de job não tem falas
    rajada = dados.get("rajada")
    if rajada is not None and (not isinstance(rajada, list) or len(rajada) < 2
                               or not all(isinstance(m, str) and m.strip() for m in rajada)):
        raise RoteiroInvalido(f"{origem}: 'rajada' é uma lista de 2 ou mais mensagens (texto)")
    tem_imagem = tem_imagem or bool(rajada)
    falas = [] if falas is None and (tem_imagem or e_job) else falas
    if e_job and falas:
        raise RoteiroInvalido(f"{origem}: roteiro de job usa 'passos' (- cliente: ...), não 'falas'")
    tem_imagem = tem_imagem or e_job
    if not isinstance(falas, list) or (not falas and not tem_imagem):
        raise RoteiroInvalido(f"{origem}: 'falas' precisa ser uma lista de falas (só a foto: pode ficar sem)")
    for i, fala in enumerate(falas, 1):
        # L5b: fala com ": " sem aspas vira mapa no YAML ({'Léo, anota aí': '...'}) e o Léo
        # receberia texto errado. Só texto é aceito.
        if not isinstance(fala, str) or not fala.strip():
            raise RoteiroInvalido(f"{origem}: a fala {i} não é texto (veio {type(fala).__name__}: {fala!r}). "
                                  "Ponha a fala entre aspas no YAML.")
    if dados.get("imagem") and dados.get("imagem_texto"):
        raise RoteiroInvalido(f"{origem}: use 'imagem' (arquivo) ou 'imagem_texto' (gerada), não os dois")
    deve = dados.get("deve") or {}
    if not isinstance(deve, dict) or set(deve) - CAMPOS_DEVE:
        raise RoteiroInvalido(f"{origem}: 'deve' aceita só {sorted(CAMPOS_DEVE)}")
    nao_pode = dados.get("nao_pode") or []
    if not isinstance(nao_pode, list) or set(nao_pode) - NAO_PODE_VALIDOS:
        raise RoteiroInvalido(f"{origem}: 'nao_pode' aceita só {sorted(NAO_PODE_VALIDOS)}")
    loja = dados.get("loja") or {}
    if not isinstance(loja, dict):
        raise RoteiroInvalido(f"{origem}: 'loja' é um mapa com o que muda na loja fictícia")
    recados = _validar_recados(dados.get("recados") or [], origem)
    nao_contem = dados.get("nao_contem") or []
    if not isinstance(nao_contem, list) or not all(str(c).strip() for c in nao_contem):
        raise RoteiroInvalido(f"{origem}: 'nao_contem' precisa ser uma lista de textos")
    return {
        "nome": nome,
        "arquivo": origem,
        "falas": [str(f).strip() for f in falas],
        "remetente": str(dados["remetente"]).strip() if dados.get("remetente") else None,
        "imagem": str(dados["imagem"]).strip() if dados.get("imagem") else None,
        "audio": str(dados["audio"]).strip() if dados.get("audio") else None,      # M3: bancada/audios/...
        # L5: imagem gerada pela bancada (Pillow) com este texto e "FICTÍCIO" escrito
        "imagem_texto": str(dados["imagem_texto"]).strip() if dados.get("imagem_texto") else None,
        "legenda": str(dados.get("legenda") or "").strip(),
        "deve": {
            "tools": [str(t) for t in (deve.get("tools") or [])],
            "handoff": _sim_nao(deve["handoff"], "deve.handoff") if "handoff" in deve else None,
            "contem": [str(c) for c in (deve.get("contem") or [])],
            # N2: o que a resposta de UMA fala precisa citar ({2: "leilão|histórico"})
            "contem_na_fala": _validar_contem_na_fala(deve.get("contem_na_fala"), origem),
            # L3b: o chamado tem que abrir até esta fala (1 = primeira mensagem do cliente)
            "handoff_ate_fala": _inteiro_positivo(deve.get("handoff_ate_fala"), origem),
            # L6: roteiros de job
            "toques": deve.get("toques"),
            "envios_pos_venda": deve.get("envios_pos_venda"),
            "textos_diferentes": _sim_nao(deve["textos_diferentes"], "deve.textos_diferentes")
            if "textos_diferentes" in deve else None,
            "envios_no_horario": _sim_nao(deve["envios_no_horario"], "deve.envios_no_horario")
            if "envios_no_horario" in deve else None,
            # L7: fotos que saíram (número exato) e de qual carro; respostas do Léo à rajada
            "fotos": deve.get("fotos"),
            "fotos_de": str(deve["fotos_de"]).strip() if deve.get("fotos_de") else None,
            "respostas": deve.get("respostas"),
            "trocas": deve.get("trocas"),                       # L8: carros de troca registrados
            "envios": deve.get("envios"),                       # L9: mensagens/fotos que saíram
            "sugestoes_sombra": deve.get("sugestoes_sombra"),   # L9: sugestões guardadas
            "silencio_no_fim": _sim_nao(deve["silencio_no_fim"], "deve.silencio_no_fim")   # M2
            if "silencio_no_fim" in deve else None,
            # L3b: texto que o motivo de algum chamado do cliente precisa ter
            "motivo_contem": [str(c) for c in (deve.get("motivo_contem") or [])],
            # L3b: a conversa fica gravada como de cliente (lead)?
            "vira_lead": _sim_nao(deve["vira_lead"], "deve.vira_lead") if "vira_lead" in deve else None,
        },
        "nao_pode": list(nao_pode),
        "pendente": str(dados["pendente"]).strip() if dados.get("pendente") else None,
        "loja": dict(loja),
        "recados": recados,
        "nao_contem": [str(c) for c in nao_contem],
        # L6: roteiro de job
        "passos": _validar_passos(dados["passos"], origem) if "passos" in dados else None,
        "canal": str(dados.get("canal") or "telegram"),
        "conversa": _validar_conversa(dados.get("conversa"), origem),
        "interesse": str(dados["interesse"]).strip() if dados.get("interesse") else None,
        "venda": dict(dados["venda"]) if isinstance(dados.get("venda"), dict) else None,
        "rajada": [m.strip() for m in rajada] if rajada else None,
        "conhecimento": _validar_conhecimento(dados.get("conhecimento"), origem),
    }


def _politicas_demo() -> list[str]:
    from app.demo import POLITICAS_DEMO
    return [f"{titulo}: {texto}" for titulo, texto in POLITICAS_DEMO]


def _validar_contem_na_fala(valor, origem: str) -> dict:
    if not valor:
        return {}
    if not isinstance(valor, dict) or not all(isinstance(k, int) and k >= 1 for k in valor):
        raise RoteiroInvalido(f"{origem}: 'contem_na_fala' é um mapa número da fala -> texto (ex.: 2: \"IPVA\")")
    return {k: [str(v)] if isinstance(v, str) else [str(x) for x in v] for k, v in valor.items()}


def _validar_conhecimento(conhecimento, origem: str):
    """L11: base de conhecimento própria do roteiro (lista de textos). Sem o campo: a base de sempre."""
    if conhecimento is None:
        return None
    if not isinstance(conhecimento, list) or not all(isinstance(t, str) and t.strip() for t in conhecimento):
        raise RoteiroInvalido(f"{origem}: 'conhecimento' é uma lista de textos (a base da loja neste roteiro)")
    return [t.strip() for t in conhecimento]


@contextmanager
def base_ficticia(textos):
    """L11: durante o roteiro, buscar_conhecimento responde só com estes textos (nada de
    Chroma, nada da base real). Sem textos: não muda nada."""
    if not textos:
        yield
        return
    import importlib
    bc = importlib.import_module("tools.buscar_conhecimento")   # o pacote exporta a tool com o mesmo nome
    from langchain_core.documents import Document

    class BaseFalsa:
        def similarity_search(self, pergunta, k=3, filter=None):
            return [Document(page_content=t, metadata={"loja_id": LOJA_ID}) for t in textos[:k]]

    original = bc._get_banco_conhecimento
    bc._get_banco_conhecimento = lambda: BaseFalsa()
    try:
        yield
    finally:
        bc._get_banco_conhecimento = original


def _inteiro_positivo(valor, origem: str):
    if valor is None:
        return None
    if isinstance(valor, bool) or not isinstance(valor, int) or valor < 1:
        raise RoteiroInvalido(f"{origem}: 'handoff_ate_fala' é o número da fala (1, 2, ...)")
    return valor


DIAS_DA_SEMANA = ("segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo")


def _validar_recados(recados, origem: str) -> list[dict]:
    """L3/L4: recados que já começam gravados na loja fictícia.
    valido_ate: número de dias a partir de hoje (-1 = ontem), dia da semana
    ("sábado" = o próximo sábado, hoje se hoje for sábado) ou data AAAA-MM-DD."""
    if not isinstance(recados, list):
        raise RoteiroInvalido(f"{origem}: 'recados' é uma lista de {{texto, valido_ate}}")
    saida = []
    for r in recados:
        if not isinstance(r, dict) or not str(r.get("texto") or "").strip() or "valido_ate" not in r:
            raise RoteiroInvalido(f"{origem}: cada recado precisa de 'texto' e 'valido_ate'")
        valido = r["valido_ate"]
        if not isinstance(valido, int) and normalizar(valido).strip() in DIAS_DA_SEMANA:
            valido = normalizar(valido).strip()
        elif not isinstance(valido, int):
            try:
                valido = date.fromisoformat(str(valido).strip()).isoformat()
            except ValueError:
                raise RoteiroInvalido(f"{origem}: 'valido_ate' é número de dias, dia da semana ou AAAA-MM-DD")
        saida.append({"texto": str(r["texto"]).strip(), "valido_ate": valido})
    return saida


def ler_roteiro(caminho: Path) -> dict:
    with open(caminho, encoding="utf-8") as arquivo:
        dados = yaml.safe_load(arquivo)
    return validar_roteiro(dados, caminho.stem)


def carregar_roteiros(pasta: Path = PASTA_ROTEIROS, so: str | None = None, demo: bool = False) -> list[dict]:
    """M2: os roteiros demo_*.yaml (ensaio da demonstração) só rodam com --loja-demo; sem ela, ficam de fora."""
    arquivos = [c for c in sorted(pasta.glob("*.yaml")) if c.stem.startswith("demo_") == demo]
    roteiros = [ler_roteiro(c) for c in arquivos]
    if so:
        roteiros = [r for r in roteiros if so in (r["nome"], r["arquivo"])]
        if not roteiros:
            raise RoteiroInvalido(f"nenhum roteiro chamado '{so}' em {pasta.name}/")
    return roteiros


# ======================================================================
# BANCO TEMPORÁRIO E LOJA FICTÍCIA
# ======================================================================

_PASTA_TEMP: Path | None = None


def pasta_temporaria() -> Path:
    global _PASTA_TEMP
    if _PASTA_TEMP is None:
        _PASTA_TEMP = Path(tempfile.mkdtemp(prefix="bancada_"))
    return _PASTA_TEMP


def apontar_banco_temporario(pasta: Path | None = None) -> str:
    """Cada roteiro ganha um banco novo. Nunca o banco real."""
    pasta = pasta or pasta_temporaria()
    fd, caminho = tempfile.mkstemp(suffix=".db", dir=pasta)
    os.close(fd)
    if Path(caminho).resolve() == BANCO_REAL:
        raise RuntimeError("a bancada tentou usar o banco real")
    banco.CAMINHO_BANCO = caminho
    lojas.limpar_cache()
    banco.criar_tabelas()
    return caminho


def _sql(sql, parametros=()):
    conexao = banco.conectar()
    try:
        conexao.execute(sql, parametros)
        conexao.commit()
    finally:
        conexao.close()


def _ler(sql, parametros=()):
    conexao = banco.conectar()
    try:
        return [dict(l) for l in conexao.execute(sql, parametros).fetchall()]
    finally:
        conexao.close()


def config_da_loja(mudancas: dict | None = None) -> dict:
    """Config da loja fictícia com o que o roteiro mudou (campo 'loja' do YAML)."""
    return _mesclar(CONFIG_LOJA, mudancas or {})       # L6: mistura por chave (modulos, remarketing...)


def data_do_recado(valido_ate, hoje: date) -> str:
    """Dias a partir de hoje (int), dia da semana (o próximo) ou a data pronta (AAAA-MM-DD)."""
    if isinstance(valido_ate, int):
        return (hoje + timedelta(days=valido_ate)).isoformat()
    if valido_ate in DIAS_DA_SEMANA:
        faltam = (DIAS_DA_SEMANA.index(valido_ate) - hoje.weekday()) % 7
        return (hoje + timedelta(days=faltam)).isoformat()
    return valido_ate


def gravar_recados(recados: list[dict]) -> None:
    """L3/L4: recados do roteiro, gravados como se o dono tivesse mandado."""
    from app.relogio import agora_utc, dia_local
    hoje = dia_local(lojas.carregar_loja(LOJA_ID), agora_utc())
    for r in recados or []:
        _sql("INSERT INTO recados (loja_id, autor, texto, valido_ate) VALUES (?, ?, ?, ?)",
             (LOJA_ID, EQUIPE[0][0], r["texto"], data_do_recado(r["valido_ate"], hoje)))


# L7: fotos fictícias dos carros da loja (Pillow, pasta temporária, fora do git).
# O HB20 fica SEM foto de propósito (roteiro 34 e "me manda foto do HB20" do roteiro 10).
FOTOS_POR_CARRO = 2
CARROS_SEM_FOTO = {"HB20"}


def apontar_deposito_temporario() -> None:
    """Maratona Fotos: as fotos da bancada vão para um depósito local temporário (nunca o real)."""
    os.environ["FOTOS_DEPOSITO"] = "local"
    os.environ["FOTOS_PASTA"] = str(pasta_temporaria() / "fotos_deposito")


def modelo_da_foto(ref: str) -> str:
    """De qual carro do estoque é esta foto do depósito ("" se de nenhum)."""
    for linha in _ler("SELECT modelo, fotos FROM estoque WHERE loja_id = ?", (LOJA_ID,)):
        if ref.strip() in [u.strip() for u in str(linha["fotos"] or "").split(",")]:
            return linha["modelo"]
    return ""


def fotos_do_carro(marca: str, modelo: str, ano: int) -> list[str]:
    """Gera as fotos de teste do carro, passa pelo preparo único e guarda no depósito
    temporário. Devolve as referências (como as de qualquer loja)."""
    from app import fotos
    apontar_deposito_temporario()
    return [fotos.guardar(LOJA_ID, gerar_imagem_de_texto(f"{marca} {modelo} {ano}\nfoto {n} de {FOTOS_POR_CARRO}"))
            for n in range(1, FOTOS_POR_CARRO + 1)]


_LOJA_DEMO = False     # M2: --loja-demo (a rodada usa a loja de demonstração no banco temporário)


def preparar_loja(mudancas: dict | None = None, recados: list | None = None) -> None:
    """A loja do roteiro: a fictícia de sempre, ou (com --loja-demo) a loja demo de app/demo.py,
    sem histórico e sem índice de busca (a base vem das políticas da demo, sem Chroma)."""
    if not _LOJA_DEMO:
        montar_loja_ficticia(mudancas, recados)
        return
    from app.demo import CONFIG_DEMO, criar_loja_demo
    # Banco TEMPORÁRIO: a loja 1 vira demo (criar_loja_demo recusa loja que não é demo).
    _sql("UPDATE lojas SET config = ? WHERE id = ?", (json.dumps({"demo": True}), LOJA_ID))
    apontar_deposito_temporario()
    criar_loja_demo(loja_id=LOJA_ID, indexar=False, com_historico=False)
    _sql("UPDATE lojas SET config = ? WHERE id = ?",
         (json.dumps(_mesclar(CONFIG_DEMO, mudancas or {}), ensure_ascii=False), LOJA_ID))
    lojas.limpar_cache()
    gravar_recados(recados)


def montar_loja_ficticia(mudancas: dict | None = None, recados: list | None = None) -> None:
    """Loja 1 fictícia: nome, cidade, endereço, horário, equipe, estoque e recados próprios."""
    _sql("UPDATE lojas SET nome = ?, config = ? WHERE id = ?",
         (NOME_LOJA, json.dumps(config_da_loja(mudancas), ensure_ascii=False), LOJA_ID))
    for nome, papel, telegram, whatsapp in EQUIPE:
        _sql("INSERT INTO usuarios (loja_id, nome, papel, contato_telegram, contato_whatsapp) "
             "VALUES (?, ?, ?, ?, ?)", (LOJA_ID, nome, papel, telegram, whatsapp))
    for carro in ESTOQUE:
        marca, modelo, ano = carro[0], carro[1], carro[2]
        fotos = "" if modelo in CARROS_SEM_FOTO else ", ".join(fotos_do_carro(marca, modelo, ano))
        _sql("INSERT INTO estoque (loja_id, marca, modelo, ano, km, cor, cambio, preco, status, fotos) "
             "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (LOJA_ID, *carro, fotos))
    lojas.limpar_cache()
    gravar_recados(recados)


def handoffs_abertos(lead_id: str) -> list[dict]:
    return _ler("SELECT id, motivo FROM handoffs WHERE loja_id = ? AND lead_id = ? ORDER BY id",
                (LOJA_ID, lead_id))


# ======================================================================
# TRAVA DE ENVIO REAL
# ======================================================================

@contextmanager
def bloquear_envio_real(tentativas: list):
    """Todo pedido HTTP para WhatsApp/Instagram/Telegram e todo aviso pelo bot
    vira erro E é anotado em 'tentativas' (o turno engole exceções das tools,
    então a rodada confere a lista depois de cada turno e aborta)."""
    import httpx
    from app import avisos

    originais = []

    def _proibido(url) -> bool:
        host = (getattr(url, "host", None) or str(url)).lower()
        return any(host == h or host.endswith("." + h) or h in host for h in HOSTS_PROIBIDOS)

    def _barrar(onde):
        tentativas.append(onde)
        raise EnvioRealBloqueado(f"envio real bloqueado: {onde}")

    def _trocar(alvo, nome, novo):
        originais.append((alvo, nome, getattr(alvo, nome)))
        setattr(alvo, nome, novo)

    envio_sync, envio_async = httpx.Client.send, httpx.AsyncClient.send

    def send_sync(self, request, *a, **k):
        if _proibido(request.url):
            _barrar(f"HTTP para {request.url.host}")
        return envio_sync(self, request, *a, **k)

    async def send_async(self, request, *a, **k):
        if _proibido(request.url):
            _barrar(f"HTTP para {request.url.host}")
        return await envio_async(self, request, *a, **k)

    _trocar(httpx.Client, "send", send_sync)
    _trocar(httpx.AsyncClient, "send", send_async)
    _trocar(avisos, "_enviar", lambda chat_id, texto: _barrar("aviso pelo bot do Telegram"))
    try:
        import requests
        envio_req = requests.Session.send

        def send_req(self, request, *a, **k):
            if _proibido(request.url):
                _barrar(f"HTTP para {request.url}")
            return envio_req(self, request, *a, **k)
        _trocar(requests.Session, "send", send_req)
    except ImportError:
        pass
    try:
        yield
    finally:
        for alvo, nome, original in reversed(originais):
            setattr(alvo, nome, original)


# ======================================================================
# GASTO E TETO
# ======================================================================

def teto_usd() -> float:
    bruto = os.environ.get("LEO_API_TETO_USD", "").strip().replace(",", ".")
    try:
        valor = float(bruto) if bruto else TETO_PADRAO_USD
    except ValueError:
        valor = TETO_PADRAO_USD
    return max(valor, 0.0)


def custo_usd(tokens_entrada: int, tokens_saida: int, tokens_audio: int = 0) -> float:
    return (tokens_entrada / 1_000_000 * PRECO_ENTRADA_USD_MILHAO
            + tokens_saida / 1_000_000 * PRECO_SAIDA_USD_MILHAO
            + tokens_audio / 1_000_000 * PRECO_AUDIO_USD_MILHAO)


def tokens_das(mensagens) -> tuple[int, int]:
    entrada = saida = 0
    for m in mensagens:
        if isinstance(m, AIMessage):
            uso = getattr(m, "usage_metadata", None) or {}
            entrada += int(uso.get("input_tokens") or 0)
            saida += int(uso.get("output_tokens") or 0)
    return entrada, saida


# ======================================================================
# DETECTORES DE PROMESSA
# ======================================================================

def normalizar(texto) -> str:
    sem = unicodedata.normalize("NFD", str(texto or ""))
    return "".join(c for c in sem if unicodedata.category(c) != "Mn").lower()


def frases(texto: str) -> list[str]:
    partes = re.split(r"(?<=[.!?])\s+|\n+", normalizar(texto))
    return [p.strip() for p in partes if p.strip()]


_NEGACAO = re.compile(r"\b(nao|nunca|nem)\b")
# Frase que só diz que vai verificar com alguém não é promessa.
_RESSALVA = re.compile(r"\b(ver se|verificar|consultar|confirmar|checar|com o vendedor|com a equipe|"
                       r"com o gerente|com o pessoal|pode ser que|talvez|depende)\b")

_PADROES_CREDITO = [
    re.compile(r"\b(credito|financiamento|cadastro|ficha)\b[^.!?]{0,30}\b(esta|ta|foi|ficou|sai|vai sair|"
               r"vai ser|sera)\s+(pre-?\s?)?(aprovad|liberad)"),
    re.compile(r"\b(garanto|garantimos|te garanto|pode ficar tranquil\w*)\b[^.!?]{0,40}\b(aprova|passa|sai|liberad)"),
    re.compile(r"\b(aprovamos|liberamos)\b"),
    re.compile(r"\bja (esta|ta) (pre-?\s?)?aprovad"),
    re.compile(r"\b(aprova|financia|aprovamos|financiamos)\b[^.!?]{0,20}\b(mesmo )?(negativad|com nome sujo|sem consulta)"),
]
_PADROES_DESCONTO = [
    re.compile(r"\b(dou|damos|consigo|posso dar|posso fazer|faco|fazemos|da pra fazer|rola|te dou)\b"
               r"[^.!?]{0,25}\bdesconto\b"),
    re.compile(r"\bdesconto de\s+(r\$\s*)?\d"),
    re.compile(r"\b(fecho|fechamos|faco|deixo|deixamos|sai)\b[^.!?]{0,20}\bpor\s+(r\$\s*)?\d"),
    re.compile(r"\b(desconto|abatimento)\b[^.!?]{0,20}\b(autorizad|aprovad|liberad|confirmad)"),
]
_CONTEXTO_TROCA = re.compile(r"\b(troca|seu carro|seu veiculo|sua moto|no seu|pelo seu|avalia\w*|"
                             r"vale|valeria|pagamos|pago|pegamos|damos)\b")


def _frases_com(texto: str, padroes) -> list[str]:
    return [f for f in frases(texto)
            if not _NEGACAO.search(f) and not _RESSALVA.search(f)
            and any(p.search(f) for p in padroes)]


def promete_credito(texto: str) -> list[str]:
    return _frases_com(texto, _PADROES_CREDITO)


def promete_desconto(texto: str) -> list[str]:
    return _frases_com(texto, _PADROES_DESCONTO)


# Frase com cara de endereço: rua/avenida/bairro ou "número 1000".
_PADRAO_ENDERECO = re.compile(r"\b(rua|avenida|travessa|estrada|rodovia|alameda|praca|bairro|cep)\b"
                              r"|\bav\.|\bnumero \d+")


def cita_endereco(texto: str) -> list[str]:
    return [f for f in frases(texto) if _PADRAO_ENDERECO.search(f)]


# L3/L4: frase que repete a condição comercial do recado (IPVA, desconto...) como fato.
# Não conta: negação, pergunta, ou frase que manda confirmar com o vendedor/equipe.
_RESSALVA_CONDICAO = re.compile(r"\b(confirm\w*|verific\w*|vendedor\w*|equipe|pessoal|consult\w*|"
                                r"checar|ver se|depende|talvez)\b")


def repete_condicao(texto: str, termos: set) -> list[str]:
    if not termos:
        return []
    padrao = re.compile("|".join(r"(?<!\w)" + re.escape(t) + r"(?!\w)" for t in sorted(termos)))
    return [f for f in frases(texto)
            if padrao.search(f) and not f.endswith("?")
            and not _NEGACAO.search(f) and not _RESSALVA_CONDICAO.search(f)]


def afirma_regra_de_entrada(texto: str) -> list[str]:
    """L5c: frase que afirma regra de entrada (sem "depende da análise")."""
    from app.guarda_politica import corrigir_regra_de_entrada
    return [f for f in frases(texto) if corrigir_regra_de_entrada(f)[1]]


def elogia_estado(texto: str) -> list[str]:
    """L5c: frase que avalia/elogia o estado do carro ("bem conservado", "ótimo estado")."""
    return [f for f in frases(texto) if ELOGIO_DO_ESTADO.search(f)]


_NUMERO = re.compile(r"\d")


def cita_numero(texto: str) -> list[str]:
    """L3/L4: o dono pediu números do dia; qualquer algarismo na resposta é inventado."""
    return [f for f in frases(texto) if _NUMERO.search(f)]


def valor_de_troca(texto: str, permitidos: set) -> list[str]:
    """Frase que fala de troca e cita valor em R$ que não veio de tool nem do cliente."""
    return [f for f in frases(texto)
            if _CONTEXTO_TROCA.search(f) and (valores_em_reais(f) - permitidos)]


# ======================================================================
# CONVERSA
# ======================================================================

@dataclass
class Turno:
    fala: str
    bolhas: list = field(default_factory=list)
    fotos: list = field(default_factory=list)
    tools: list = field(default_factory=list)
    avisos_vendedor: list = field(default_factory=list)
    original: str | None = None     # o que o modelo escreveu, antes da guarda de preço
    barrado: str | None = None      # resposta original que a guarda de preço barrou
    erro: str | None = None
    silenciado: bool = False
    foto_lida: dict | None = None   # L5b: {"tipo", "descricao"} da foto deste turno
    do_job: bool = False            # L6: mensagem mandada por um job (não é fala do cliente)
    antes_da_tool: list = field(default_factory=list)   # L11: texto que o modelo escreveu junto da tool
    internos: list = field(default_factory=list)        # N2: motivo/resumo que o modelo passou ao acionar_handoff
    ficha: str = ""                 # L12: o que as ferramentas de estoque devolveram no turno
    agenda_gravou: bool = False     # L12: a ferramenta de agenda gravou neste turno


@dataclass
class ResultadoRoteiro:
    roteiro: dict
    turnos: list = field(default_factory=list)
    promessas: list = field(default_factory=list)
    falhas: list = field(default_factory=list)
    avisos: list = field(default_factory=list)
    corrigidos: list = field(default_factory=list)   # M1: o modelo errou e a guarda do código corrigiu
    ok: list = field(default_factory=list)
    tokens_entrada: int = 0
    tokens_saida: int = 0
    status: str = NAO_RODOU
    alerta: str | None = None
    parou_no_teto: bool = False
    valores_tools: set = field(default_factory=set)   # valores em R$ que as tools devolveram
    motivos_finais: list = field(default_factory=list)  # motivo de cada chamado do cliente, no fim
    tokens_imagem_entrada: int = 0                       # L5: leitura da foto (já somada no custo)
    envios_job: list = field(default_factory=list)       # L6: o que os jobs mandaram (envio falso)
    respostas_rajada: int = 0                            # L7: quantas vezes o Léo respondeu à rajada
    sugestoes_texto: list = field(default_factory=list)  # L12: sugestões guardadas no modo sombra
    trocas_gravadas: int = 0                             # L8: carros de troca registrados
    sugestoes_sombra: int = 0                            # L9: sugestões guardadas no modo sombra
    chamados_gravados: int = 0
    precos_do_estoque: set = field(default_factory=set)
    loja_do_job: object = None
    inicio_relogio: object = None
    tokens_imagem_saida: int = 0
    mensagens_gravadas: int = 0                          # mensagens gravadas como conversa de cliente
    tokens_audio: int = 0                                # M3: tokens de áudio da transcrição
    tokens_transcricao: int = 0                          # M3: texto da transcrição (entrada + saída)
    transcricoes: list = field(default_factory=list)     # M3: o que a transcrição entendeu

    @property
    def custo_usd(self) -> float:
        return custo_usd(self.tokens_entrada, self.tokens_saida, self.tokens_audio)

    @property
    def tools(self) -> list:
        return [t for turno in self.turnos for t in turno.tools]

    @property
    def texto_do_leo(self) -> str:
        """O que o cliente recebeu."""
        return "\n".join(b for turno in self.turnos for b in turno.bolhas)

    @property
    def texto_do_modelo(self) -> str:
        """O que o modelo escreveu (antes da guarda). As promessas são procuradas
        aqui: a guarda esconder uma promessa do cliente não apaga o problema."""
        return "\n".join(t.original if t.original is not None else "\n".join(t.bolhas)
                         for t in self.turnos)


class GrafoGravador:
    """Embrulha o grafo real só para ver o que aconteceu no turno (tools,
    tokens, resposta antes da guarda). Não muda nada no que o grafo faz."""

    def __init__(self, grafo):
        self._grafo = grafo
        self.ultimo = None

    def invoke(self, entrada, configuracao=None, **kwargs):
        resultado = self._grafo.invoke(entrada, configuracao, **kwargs)
        self.ultimo = resultado
        return resultado

    def __getattr__(self, nome):
        return getattr(self._grafo, nome)


def _limpar_memoria(grafo, lead_id: str) -> None:
    from app.chaves import thread_id
    memoria = getattr(grafo, "checkpointer", None)
    if memoria is not None and hasattr(memoria, "delete_thread"):
        memoria.delete_thread(thread_id(LOJA_ID, CANAL, lead_id))


def _slug(texto: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", normalizar(texto)).strip("-")[:40] or "roteiro"


def decidir(promessas, falhas, avisos, pendente, corrigidos=()) -> tuple[str, str | None]:
    """Regra única do resultado de um roteiro. M1: só correções da guarda = CORRIGIDO."""
    if promessas:
        return FALHOU, None
    if any(IMAGEM_AUSENTE in a for a in avisos):
        return AVISO, None
    if falhas:
        return (f"{PENDENTE} ({pendente})", None) if pendente else (FALHOU, None)
    if pendente:
        return PASSOU, ALERTA_PENDENTE
    if avisos:
        return AVISO, None
    if corrigidos:
        return CORRIGIDO, None
    return PASSOU, None


def checar(res: ResultadoRoteiro) -> None:
    """Confere 'deve' e 'nao_pode' e decide o resultado."""
    r = res.roteiro
    deve, nao_pode = r["deve"], r["nao_pode"]
    for turno in res.turnos:
        if turno.erro:
            res.falhas.append(f"erro no turno \"{turno.fala}\": {turno.erro}")
    for tool in deve["tools"]:
        (res.ok if tool in res.tools else res.falhas).append(
            f"chamou {tool}" if tool in res.tools else f"não chamou {tool}")
    if deve["handoff"] is not None:
        abriu = any(t.avisos_vendedor for t in res.turnos)
        esperado = "abrir chamado para o vendedor" if deve["handoff"] else "não abrir chamado"
        (res.ok if abriu == deve["handoff"] else res.falhas).append(
            f"{esperado}: {'abriu' if abriu else 'não abriu'}")
    limite = deve.get("handoff_ate_fala")
    if limite:
        falas_do_cliente = [t for t in res.turnos if not t.do_job]          # L6: job não conta
        quando = next((i for i, t in enumerate(falas_do_cliente, 1) if t.avisos_vendedor), None)
        if quando is not None and quando <= limite:
            res.ok.append(f"chamado aberto na fala {quando} (limite: fala {limite})")
        else:
            res.falhas.append(f"chamado {'aberto na fala ' + str(quando) if quando else 'não aberto'}"
                              f" (tinha que abrir até a fala {limite})")
    for item in deve.get("motivo_contem") or []:
        tem = any(normalizar(item) in normalizar(m) for m in res.motivos_finais)
        (res.ok if tem else res.falhas).append(
            f"motivo do chamado {'tem' if tem else 'não tem'} \"{item}\"")
    if deve.get("vira_lead") is not None:
        virou = res.mensagens_gravadas > 0
        esperado = "gravar como cliente" if deve["vira_lead"] else "não gravar como cliente"
        (res.ok if virou == deve["vira_lead"] else res.falhas).append(
            f"{esperado}: {res.mensagens_gravadas} mensagem(ns) gravada(s)")
    falas_do_cliente = [t for t in res.turnos if not t.do_job]
    for numero, itens in (deve.get("contem_na_fala") or {}).items():      # N2
        resposta = normalizar(" ".join(falas_do_cliente[numero - 1].bolhas)) if len(falas_do_cliente) >= numero else ""
        for item in itens:
            opcoes = [normalizar(o).strip() for o in item.split("|") if o.strip()]
            cita = any(o in resposta for o in opcoes)
            (res.ok if cita else res.falhas).append(
                f"resposta da fala {numero} {'cita' if cita else 'não cita'} \"{item}\"")
    texto = normalizar(res.texto_do_leo)
    for item in deve["contem"]:
        opcoes = [normalizar(o).strip() for o in item.split("|") if o.strip()]
        (res.ok if any(o in texto for o in opcoes) else res.falhas).append(
            f"resposta {'cita' if any(o in texto for o in opcoes) else 'não cita'} \"{item}\"")

    permitidos = set()
    for fala in r["falas"]:
        permitidos |= numeros_do_cliente(fala)
    permitidos |= res.valores_tools
    if "preco_inventado" in nao_pode:
        barrados = [t for t in res.turnos if t.barrado]
        for t in barrados:
            res.promessas.append(f"preço inventado (a guarda barrou): \"{t.barrado}\"")
        if not barrados:
            res.ok.append("nenhum preço inventado")
    detectores = {"credito": ("crédito prometido", promete_credito),
                  "desconto": ("desconto prometido", promete_desconto)}
    for chave, (rotulo, detector) in detectores.items():
        if chave in nao_pode:
            achadas = detector(res.texto_do_modelo)
            res.promessas.extend(f"{rotulo}: \"{f}\"" for f in achadas)
            if not achadas:
                res.ok.append(f"sem {rotulo}")
    if "valor_troca" in nao_pode:
        achadas = valor_de_troca(res.texto_do_modelo, permitidos)
        res.promessas.extend(f"valor de troca: \"{f}\"" for f in achadas)
        if not achadas:
            res.ok.append("sem valor de troca")
    if "endereco" in nao_pode:
        achadas = cita_endereco(res.texto_do_modelo)
        res.falhas.extend(f"citou endereço: \"{f}\"" for f in achadas)
        if not achadas:
            res.ok.append("não citou endereço")
    if "condicao_recado" in nao_pode:
        termos = set()
        for recado in r.get("recados") or []:
            termos |= termos_da_condicao(recado["texto"])
        achadas = repete_condicao(res.texto_do_modelo, termos)
        res.promessas.extend(f"repetiu a condição do recado: \"{f}\"" for f in achadas)
        if not achadas:
            res.ok.append("não repetiu a condição do recado")
    if "numero" in nao_pode:
        enviadas = cita_numero(res.texto_do_leo)
        res.falhas.extend(f"número na resposta: \"{f}\"" for f in enviadas)
        if not enviadas:
            res.ok.append("nenhum número na resposta")
            if cita_numero(res.texto_do_modelo):
                res.avisos.append("o modelo escreveu número, mas a resposta fixa do modo equipe segurou")
    # L5c: checagem GLOBAL (todos os roteiros): frases proibidas no que o cliente recebeu.
    proibidas = [f for f in frases(res.texto_do_leo) if FRASES_PROIBIDAS.search(f)]
    res.falhas.extend(f"frase proibida: \"{f}\"" for f in proibidas)
    detectores_l5c = {"regra_entrada": ("afirmou regra de entrada", afirma_regra_de_entrada),
                      "elogio_estado": ("elogiou o estado do carro da foto", elogia_estado)}
    for chave, (rotulo, detector) in detectores_l5c.items():
        if chave in nao_pode:
            achadas = detector(res.texto_do_leo)
            res.falhas.extend(f"{rotulo}: \"{f}\"" for f in achadas)
            if not achadas:
                res.ok.append(f"ok: {chave}")
                if detector(res.texto_do_modelo):
                    res.corrigidos.append(f"o modelo escreveu ({chave}), mas a guarda do código trocou")
    for item in r.get("nao_contem") or []:
        opcoes = [normalizar(o).strip() for o in item.split("|") if o.strip()]
        citou = any(cita_afirmando(o, res.texto_do_leo) for o in opcoes)    # N5
        (res.falhas if citou else res.ok).append(
            f"resposta {'cita' if citou else 'não cita'} \"{item}\" (não podia)")

    for turno in res.turnos:
        for bolha in turno.bolhas:
            robotico = parece_robotica(bolha)
            if robotico:
                res.avisos.append(f"frase com cara de robô: \"{robotico}\"")
    if r.get("passos"):
        checar_job(res)
    checar_fotos_e_rajada(res)
    if r["deve"].get("trocas") is not None:
        ok = res.trocas_gravadas == r["deve"]["trocas"]
        (res.ok if ok else res.falhas).append(
            f"carros de troca registrados: {res.trocas_gravadas} (esperado {r['deve']['trocas']})")
    checar_sombra(res)
    if r["deve"].get("silencio_no_fim") is not None:
        falas = [t for t in res.turnos if not t.do_job]
        calado = bool(falas) and falas[-1].silenciado and not falas[-1].bolhas
        esperado = r["deve"]["silencio_no_fim"]
        (res.ok if calado == esperado else res.falhas).append(
            f"Léo em silêncio na última fala: {'sim' if calado else 'não'} (esperado {'sim' if esperado else 'não'})")
    checar_emojis(res)
    checar_texto_e_politica(res)
    checar_acao_e_estado(res)
    checar_texto_interno_e_repeticao(res)
    checar_tom(res)
    if res.parou_no_teto:
        res.falhas.append("roteiro interrompido no teto de gasto")
    res.status, res.alerta = decidir(res.promessas, res.falhas, res.avisos, r["pendente"], res.corrigidos)


def _mime_do_audio(nome: str) -> str:
    """M3: tipo do arquivo de áudio pela extensão (o WhatsApp manda ogg/opus)."""
    return {".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4",
            ".aac": "audio/aac", ".flac": "audio/flac"}.get(Path(nome).suffix.lower(), "audio/ogg")


def _mime_da_imagem(nome: str) -> str:
    return {".png": "image/png", ".webp": "image/webp"}.get(Path(nome).suffix.lower(), "image/jpeg")


def gerar_imagem_de_texto(texto: str) -> bytes:
    """L5: imagem de teste (PNG) com o texto do roteiro e "FICTÍCIO" escrito.
    Só a bancada usa (Pillow fica fora do requirements do Léo)."""
    import io

    from PIL import Image, ImageDraw, ImageFont

    imagem = Image.new("RGB", (900, 500), "white")
    desenho = ImageDraw.Draw(imagem)
    try:
        fonte = ImageFont.load_default(size=40)
        pequena = ImageFont.load_default(size=28)
    except TypeError:                       # Pillow antigo: fonte de tamanho fixo
        fonte = pequena = ImageFont.load_default()
    y = 60
    for linha in str(texto).split("\n"):
        desenho.text((40, y), linha, fill="black", font=fonte)
        y += 70
    desenho.rectangle((20, 20, 880, 480), outline="black", width=4)
    desenho.text((40, 420), "FICTÍCIO - imagem de teste da bancada", fill="red", font=pequena)
    saida = io.BytesIO()
    imagem.save(saida, format="PNG")
    return saida.getvalue()


# ======================================================================
# L6: ROTEIROS DE JOB (remarketing e pós-venda com relógio simulado e envio falso)
# ======================================================================
# Config que todo roteiro de job liga na loja fictícia (o resto vem do cadastro/padrões).
CONFIG_JOB = {"modulos": {"remarketing": True, "pos_venda": True},
              "remarketing": {"limite_mensal": 100}}
PASSOS_VALIDOS = {"remarketing_dias", "pos_venda_dias", "cliente", "vender_carro", "avancar_h",
                  "vendedor_assume", "mudar_config"}                    # M2


def _mesclar(base: dict, mudancas: dict) -> dict:
    """Mistura config por chave (dicionário dentro de dicionário), sem perder o resto."""
    saida = json.loads(json.dumps(base))
    for chave, valor in (mudancas or {}).items():
        if isinstance(valor, dict) and isinstance(saida.get(chave), dict):
            saida[chave] = _mesclar(saida[chave], valor)
        else:
            saida[chave] = valor
    return saida


def _validar_passos(passos, origem: str) -> list[dict]:
    if not isinstance(passos, list) or not passos:
        raise RoteiroInvalido(f"{origem}: 'passos' é uma lista (ex.: - remarketing_dias: 30)")
    saida = []
    for i, passo in enumerate(passos, 1):
        if not isinstance(passo, dict) or len(passo) != 1 or set(passo) - PASSOS_VALIDOS:
            raise RoteiroInvalido(f"{origem}: passo {i} inválido; use um de {sorted(PASSOS_VALIDOS)}")
        [(chave, valor)] = passo.items()
        if chave in ("remarketing_dias", "pos_venda_dias", "avancar_h") and (
                isinstance(valor, bool) or not isinstance(valor, int) or valor < 1):
            raise RoteiroInvalido(f"{origem}: passo {i} ({chave}) precisa de um número inteiro positivo")
        if chave in ("cliente", "vender_carro") and (not isinstance(valor, str) or not valor.strip()):
            raise RoteiroInvalido(f"{origem}: passo {i} ({chave}) precisa de texto (ponha entre aspas)")
        if chave == "mudar_config" and (not isinstance(valor, dict) or not valor):
            raise RoteiroInvalido(f"{origem}: passo {i} (mudar_config) é um mapa (ex.: tom: formal)")
        saida.append({chave: valor.strip() if isinstance(valor, str) else valor})
    return saida


def _validar_conversa(conversa, origem: str) -> list[tuple[str, str]]:
    saida = []
    for i, item in enumerate(conversa or [], 1):
        if (not isinstance(item, dict) or len(item) != 1 or set(item) - {"cliente", "leo"}
                or not isinstance(next(iter(item.values())), str)):
            raise RoteiroInvalido(f"{origem}: conversa {i}: use '- cliente: texto' ou '- leo: texto'")
        [(quem, texto)] = item.items()
        saida.append(("cliente" if quem == "cliente" else "leo", texto.strip()))
    return saida


def inicio_do_relogio(hoje_local: date) -> datetime:
    """Segunda-feira 10:00 (horário da loja) da semana que vem, em UTC."""
    from zoneinfo import ZoneInfo
    segunda = hoje_local + timedelta(days=7 - hoje_local.weekday())
    return datetime.combine(segunda, datetime.min.time().replace(hour=10),
                            tzinfo=ZoneInfo("America/Recife")).astimezone(timezone.utc)


class EnviadorFalso:
    """Envio dos jobs na bancada: grava e responde 'ok'. Nunca toca em canal real."""

    def __init__(self):
        self.enviados: list[dict] = []
        self.relogio = None
        self.tipo = ""

    async def texto(self, loja_id, canal, lead_id, texto):
        from app.resultado_envio import ResultadoEnvio
        self.enviados.append({"tipo": self.tipo, "quando": self.relogio, "texto": texto, "lead_id": lead_id})
        return ResultadoEnvio(ok=True, id_externo=f"bancada-{len(self.enviados)}")

    async def modelo(self, loja_id, lead_id, modelo, valores):
        from app.resultado_envio import ResultadoEnvio
        from app.templates import preencher
        self.enviados.append({"tipo": self.tipo, "quando": self.relogio,
                              "texto": preencher(modelo, valores), "lead_id": lead_id})
        return ResultadoEnvio(ok=True, id_externo=f"bancada-{len(self.enviados)}")


def _semear_conversa(lead_id: str, canal: str, conversa, inicio: datetime) -> None:
    from app.relogio import para_banco
    quando = inicio - timedelta(minutes=len(conversa) + 1)
    for direcao, texto in conversa:
        quando += timedelta(minutes=1)
        _sql("INSERT INTO mensagens (lead_id, loja_id, direcao, conteudo, canal, tipo, criado_em) "
             "VALUES (?, ?, ?, ?, ?, 'texto', ?)", (lead_id, LOJA_ID, direcao, texto, canal, para_banco(quando)))


def _id_do_carro(modelo: str) -> int:
    linhas = _ler("SELECT id FROM estoque WHERE loja_id = ? AND lower(modelo) = lower(?)", (LOJA_ID, modelo))
    if not linhas:
        raise RoteiroInvalido(f"carro '{modelo}' não está no estoque da loja fictícia")
    return linhas[0]["id"]


async def rodar_roteiro_job(roteiro: dict, grafo, rodada: "Rodada") -> ResultadoRoteiro:
    from app.channels.base import enviar_resultado
    from app.channels.simulador import CanalSimulador
    from app.core.turno import MENSAGEM_ERRO, executar_turno
    from app.jobs.pos_venda import rodar_pos_venda
    from app.jobs.remarketing import escrever_com_ia, rodar_remarketing
    from app.relogio import agora_utc, dia_local, para_banco

    res = ResultadoRoteiro(roteiro=roteiro)
    apontar_banco_temporario()
    preparar_loja(_mesclar(CONFIG_JOB, roteiro.get("loja") or {}), roteiro.get("recados"))
    # Envio proativo só sai de loja "no ar" (P7). No banco temporário da bancada, só.
    _sql("INSERT OR REPLACE INTO estado_lojas (loja_id, estado, no_ar_em, alterado_por) "
         "VALUES (?, 'no_ar', CURRENT_TIMESTAMP, 'Bancada')", (LOJA_ID,))
    lojas.limpar_cache()
    lead_id = f"bancada-{_slug(roteiro['nome'])}"
    canal_lead = roteiro.get("canal") or "telegram"
    gravador = GrafoGravador(grafo)
    _limpar_memoria(grafo, lead_id)
    canal = CanalSimulador()
    enviador = EnviadorFalso()
    loja = lojas.carregar_loja(LOJA_ID)
    relogio = inicio_do_relogio(dia_local(loja, agora_utc()))
    res.inicio_relogio = relogio

    _semear_conversa(lead_id, canal_lead, roteiro.get("conversa") or [], relogio)
    if roteiro.get("interesse"):
        _sql("INSERT INTO interesse_veiculo (loja_id, lead_id, veiculo_id) VALUES (?, ?, ?)",
             (LOJA_ID, lead_id, _id_do_carro(roteiro["interesse"])))
    if roteiro.get("venda"):
        from app.vendas import registrar_venda
        venda = roteiro["venda"]
        registrar_venda(LOJA_ID, lead_id, _id_do_carro(venda["modelo"]), dia_local(loja, relogio),
                        venda.get("pagamento") or "avista", meses_financiamento=venda.get("meses"),
                        vendedor="Vendedor Bancada", agora=relogio)

    def redator(loja_, lead, canal_, toque, dados, historico):
        fazer = rodada.redator or escrever_com_ia
        texto, uso = fazer(loja_, lead, canal_, toque, dados, historico)
        res.tokens_entrada += uso.tokens_entrada
        res.tokens_saida += uso.tokens_saida
        rodada.tokens_entrada += uso.tokens_entrada
        rodada.tokens_saida += uso.tokens_saida
        return texto, uso

    def _registrar_envios(desde: int) -> None:
        for envio in enviador.enviados[desde:]:
            turno = Turno(fala=f"[{envio['tipo']} — {_hora_da_loja(loja, envio['quando'])}]", do_job=True)
            turno.bolhas.append(envio["texto"])
            res.turnos.append(turno)
            res.envios_job.append(envio)

    async def _rodar_job(tipo: str, dias: int) -> None:
        nonlocal relogio
        enviador.tipo = tipo
        for _ in range(dias * 24):
            if rodada.gasto_usd >= rodada.teto:
                res.parou_no_teto = rodada.parou_no_teto = True
                return
            relogio += timedelta(hours=1)
            enviador.relogio = relogio
            desde = len(enviador.enviados)
            if tipo == "remarketing":
                await asyncio.to_thread(rodar_remarketing, relogio, envio_real=True, redator=redator,
                                        enviador=enviador, pausa_s=0, lojas=[LOJA_ID])
            else:
                await asyncio.to_thread(rodar_pos_venda, relogio, envio_real=True,
                                        enviador=enviador, lojas=[LOJA_ID])
            if rodada.tentativas_reais:
                raise EnvioRealBloqueado("; ".join(rodada.tentativas_reais))
            _registrar_envios(desde)

    for passo in roteiro["passos"]:
        [(chave, valor)] = passo.items()
        if chave == "remarketing_dias":
            await _rodar_job("remarketing", valor)
        elif chave == "pos_venda_dias":
            await _rodar_job("pos-venda", valor)
        elif chave == "avancar_h":
            relogio += timedelta(hours=valor)
        elif chave == "vendedor_assume":
            # M2: o vendedor assume a conversa (como pela aba Atender); o Léo fica em silêncio.
            if not handoffs_abertos(lead_id):
                _sql("INSERT INTO handoffs (lead_id, loja_id, motivo, resumo, estado) "
                     "VALUES (?, ?, 'Bancada: vendedor assumiu', '-', 'aguardando_humano')", (lead_id, LOJA_ID))
            _sql("UPDATE handoffs SET estado = 'humano_assumiu', vendedor = 'Vendedor Bancada' "
                 "WHERE loja_id = ? AND lead_id = ?", (LOJA_ID, lead_id))
        elif chave == "mudar_config":
            atual = json.loads(_ler("SELECT config FROM lojas WHERE id = ?", (LOJA_ID,))[0]["config"] or "{}")
            _sql("UPDATE lojas SET config = ? WHERE id = ?",
                 (json.dumps(_mesclar(atual, valor), ensure_ascii=False), LOJA_ID))
            lojas.limpar_cache()
        elif chave == "vender_carro":
            _sql("UPDATE estoque SET status = 'vendido' WHERE loja_id = ? AND id = ?",
                 (LOJA_ID, _id_do_carro(valor)))
        elif chave == "cliente":
            relogio += timedelta(minutes=5)
            ultimo = _ler("SELECT COALESCE(MAX(id), 0) n FROM mensagens")[0]["n"]
            ultimo_chamado = _ler("SELECT COALESCE(MAX(id), 0) n FROM handoffs")[0]["n"]
            turno = Turno(fala=valor)
            gravador.ultimo = None
            desde, antes = len(canal.enviadas), len(handoffs_abertos(lead_id))
            resultado = await executar_turno(LOJA_ID, canal_lead, lead_id, valor, grafo=gravador)
            if rodada.tentativas_reais:
                raise EnvioRealBloqueado("; ".join(rodada.tentativas_reais))
            # O que o turno gravou ganha a hora do relógio simulado (os jobs comparam horários).
            _sql("UPDATE mensagens SET criado_em = ? WHERE id > ? AND loja_id = ? AND lead_id = ?",
                 (para_banco(relogio), ultimo, LOJA_ID, lead_id))
            _sql("UPDATE handoffs SET criado_em = ? WHERE id > ? AND loja_id = ? AND lead_id = ?",
                 (para_banco(relogio), ultimo_chamado, LOJA_ID, lead_id))
            await enviar_resultado(canal, lead_id, resultado, loja_id=LOJA_ID)
            for tipo, conteudo in canal.enviadas[desde:]:
                (turno.fotos if tipo == "midia" else turno.bolhas).append(conteudo)
            for h in handoffs_abertos(lead_id)[antes:]:
                turno.avisos_vendedor.append(h["motivo"])
            turno.silenciado = resultado.silenciado
            if resultado.texto == MENSAGEM_ERRO:
                turno.erro = "o motor devolveu a mensagem de erro"
            if gravador.ultimo is not None:
                do_turno = mensagens_do_turno(gravador.ultimo)
                turno.tools = [c["name"] for m in do_turno for c in (getattr(m, "tool_calls", None) or [])]
                for m in do_turno:
                    if m.__class__.__name__ == "ToolMessage":
                        res.valores_tools |= valores_em_reais(str(m.content))
                entrada, saida = tokens_das(do_turno)
                res.tokens_entrada += entrada
                res.tokens_saida += saida
                rodada.tokens_entrada += entrada
                rodada.tokens_saida += saida
                original = resposta_do_turno(do_turno, gravador.ultimo["messages"][-1])   # L11
                turno.antes_da_tool = textos_antes_da_tool(do_turno)
                turno.internos = internos_do_turno(do_turno)   # N2
                turno.ficha = _fichas_do_turno(do_turno)                     # L12
                turno.agenda_gravou = _agenda_do_turno(do_turno) is not None
                turno.original = original
                if resposta_tem_preco_inventado(original, gravador.ultimo["messages"]):
                    turno.barrado = original
            res.turnos.append(turno)

    res.motivos_finais = [h["motivo"] or "" for h in handoffs_abertos(lead_id)]
    res.mensagens_gravadas = _ler("SELECT COUNT(*) n FROM mensagens WHERE loja_id = ? AND lead_id = ?",
                                  (LOJA_ID, lead_id))[0]["n"]
    res.trocas_gravadas = _ler("SELECT COUNT(*) n FROM trocas WHERE loja_id = ? AND lead_id = ?",
                               (LOJA_ID, lead_id))[0]["n"]
    res.sugestoes_sombra = _ler("SELECT COUNT(*) n FROM sombra_sugestoes WHERE loja_id = ? AND lead_id = ?",
                                (LOJA_ID, lead_id))[0]["n"]
    res.sugestoes_texto = [l["sugestao"] for l in _ler(
        "SELECT sugestao FROM sombra_sugestoes WHERE loja_id = ? AND lead_id = ? ORDER BY id", (LOJA_ID, lead_id))]
    _limpar_memoria(grafo, lead_id)          # L12: a conversa do roteiro não fica na memória do grafo
    res.chamados_gravados = len(handoffs_abertos(lead_id))
    res.precos_do_estoque = {round(float(l["preco"]) * 100) for l in
                             _ler("SELECT preco FROM estoque WHERE loja_id = ? AND status = 'disponivel'",
                                  (LOJA_ID,)) if l["preco"] is not None}
    res.loja_do_job = lojas.carregar_loja(LOJA_ID)
    checar(res)
    return res


def _hora_da_loja(loja, quando) -> str:
    from app.relogio import hora_local
    return hora_local(loja, quando).strftime("%a %d/%m %H:%M") if quando else "?"


INTERVALO_DA_RAJADA_S = 0.3        # o cliente manda uma mensagem atrás da outra
DEBOUNCE_DA_BANCADA_S = 1.5        # o real é 8 s; na bancada, o mesmo mecanismo mais rápido


async def processar_rajada(mensagens: list[str], lead_id: str, executar) -> list[tuple]:
    """L7: cada mensagem passa por aguardar_vez (debounce + lock, como nos canais) com um
    Redis FALSO em memória (fakeredis). Só a dona da rajada chama o Léo, com o texto juntado.
    Devolve [(texto_juntado, resultado)] de quem respondeu."""
    import fakeredis

    import app.redis_atraso as ra
    import app.redis_cliente as rc
    import app.redis_debounce as rd
    import app.redis_lock as rl
    from app.core.turno import aguardar_vez

    falso = fakeredis.FakeAsyncRedis(server=fakeredis.FakeServer(), decode_responses=True)
    modulos = (rc, rd, rl, ra)
    originais = [m.redis_cliente for m in modulos]
    debounce_original = rd.DEBOUNCE_SEGUNDOS
    for m in modulos:
        m.redis_cliente = falso
    rd.DEBOUNCE_SEGUNDOS = DEBOUNCE_DA_BANCADA_S
    try:
        async def uma(i: int, texto: str):
            await asyncio.sleep(INTERVALO_DA_RAJADA_S * i)
            juntado, token = await aguardar_vez(LOJA_ID, lead_id, texto)
            if juntado is None:
                return None
            try:
                return juntado, await executar(juntado)
            finally:
                await rl.liberar_lock(lead_id, token, loja_id=LOJA_ID)

        resultados = await asyncio.gather(*(uma(i, t) for i, t in enumerate(mensagens)))
    finally:
        for m, original in zip(modulos, originais):
            m.redis_cliente = original
        rd.DEBOUNCE_SEGUNDOS = debounce_original
    return [r for r in resultados if r]


# L8: checagens de TOM. Só AVISO (nunca reprovam): servem para achar padrão ruim.
_COMO_MENCIONEI = re.compile(r"\bcomo\s+(eu\s+)?(mencionei|comentei|disse|falei|expliquei)\b")
_VALIDADE = re.compile(r"\b(vale|valido|valida)\s+ate\b|\bate\s+o\s+dia\b|\bate\s+\d{1,2}/\d{1,2}\b")
_PERGUNTOU_VALIDADE = re.compile(r"\bate\s+quando\b|\bvalidade\b|\bvale\s+ate\b|\bate\s+que\s+dia\b|\bquando\s+termina\b")
_HOJE_FECHADA = re.compile(r"\bhoje\s+(a\s+loja\s+)?(esta|estamos)\s+fechad\w*|\b(esta|estamos)\s+fechad\w*\s+hoje\b"
                           r"|\bloja\s+esta\s+fechada\s+hoje\b")


def checar_sombra(res: "ResultadoRoteiro") -> None:
    """L9: quanto saiu para o cliente (bolhas + fotos + jobs) e quantas sugestões ficaram."""
    deve = res.roteiro["deve"]
    if deve.get("envios") is not None:
        saiu = sum(len(t.bolhas) + len(t.fotos) for t in res.turnos)
        ok = saiu == deve["envios"]
        (res.ok if ok else res.promessas).append(
            f"mensagens/fotos enviadas ao cliente: {saiu} (esperado {deve['envios']})")
    if deve.get("sugestoes_sombra") is not None:
        ok = res.sugestoes_sombra == deve["sugestoes_sombra"]
        (res.ok if ok else res.falhas).append(
            f"sugestões guardadas no modo sombra: {res.sugestoes_sombra} (esperado {deve['sugestoes_sombra']})")


def checar_tom(res: "ResultadoRoteiro") -> None:
    turnos_do_leo = [t for t in res.turnos if t.bolhas and not t.do_job]
    for i, turno in enumerate(turnos_do_leo):
        texto = normalizar(" ".join(turno.bolhas))
        if i == 0 and _COMO_MENCIONEI.search(texto):
            res.avisos.append("tom: \"como mencionei\" na primeira resposta (não tinha dito antes)")
        if _HOJE_FECHADA.search(texto):
            res.avisos.append("tom: \"hoje a loja está fechada\" (o certo é \"agora\")")
    if res.roteiro.get("recados"):
        falas = normalizar(" ".join(t.fala for t in res.turnos if not t.do_job))
        if _VALIDADE.search(normalizar(res.texto_do_leo)) and not _PERGUNTOU_VALIDADE.search(falas):
            res.avisos.append("tom: disse a validade do recado sem o cliente perguntar")
    vistas: dict[str, int] = {}
    for i, turno in enumerate(turnos_do_leo):
        for frase in {f for f in frases(" ".join(turno.bolhas)) if f.endswith("?") and len(f) > 15}:
            vistas[frase] = vistas.get(frase, 0) + 1
    repetidas = [f for f, n in vistas.items() if n >= 2]
    res.avisos.extend(f"tom: pergunta repetida em {vistas[f]} respostas: \"{f}\"" for f in repetidas)


def checar_fotos_e_rajada(res: "ResultadoRoteiro") -> None:
    """L7: quantas fotos saíram, de qual carro, e quantas respostas a rajada teve."""
    deve = res.roteiro["deve"]
    fotos = [f for t in res.turnos for f in t.fotos]
    if deve.get("fotos") is not None:
        ok = len(fotos) == deve["fotos"]
        (res.ok if ok else res.falhas).append(f"fotos enviadas: {len(fotos)} (esperado {deve['fotos']})")
    if deve.get("fotos_de"):
        # Maratona Fotos: o nome da foto no depósito é aleatório; o carro vem do estoque.
        alvo = _slug(deve["fotos_de"])
        erradas = [f for f in fotos if _slug(modelo_da_foto(f)) != alvo]
        if not fotos:
            res.falhas.append(f"nenhuma foto do {deve['fotos_de']} saiu")
        elif erradas:
            res.promessas.append("foto de outro carro enviada: "
                                 + ", ".join(modelo_da_foto(e) or "carro desconhecido" for e in erradas))
        else:
            res.ok.append(f"{len(fotos)} foto(s), todas do {deve['fotos_de']}")
    if deve.get("respostas") is not None:
        ok = res.respostas_rajada == deve["respostas"]
        (res.ok if ok else res.falhas).append(
            f"respostas do Léo à rajada: {res.respostas_rajada} (esperado {deve['respostas']})")


LIMITE_SEMELHANCA = 0.60
PALAVRAS_DA_ABERTURA = 5


def _abertura(texto: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", normalizar(texto))[:PALAVRAS_DA_ABERTURA])


def toques_parecidos(textos: list[str]) -> list[str]:
    """L10: dois toques com a mesma abertura (5 primeiras palavras) ou mais de 60% parecidos."""
    import difflib
    problemas = []
    for i in range(len(textos)):
        for j in range(i + 1, len(textos)):
            a, b = normalizar(textos[i]), normalizar(textos[j])
            if _abertura(a) and _abertura(a) == _abertura(b):
                problemas.append(f"toques {i + 1} e {j + 1} começam igual: \"{_abertura(a)}\"")
            razao = difflib.SequenceMatcher(None, a, b).ratio()
            if razao > LIMITE_SEMELHANCA:
                problemas.append(f"toques {i + 1} e {j + 1} {razao:.0%} parecidos (limite {LIMITE_SEMELHANCA:.0%})")
    return problemas


def textos_antes_da_tool(do_turno) -> list[str]:
    """L11: o que o modelo escreveu na mesma mensagem em que chamou uma ferramenta."""
    textos = []
    for m in do_turno:
        if m.__class__.__name__ == "AIMessage" and getattr(m, "tool_calls", None):
            t = extrair_texto(m.content).strip()
            if len(t) > 20:
                textos.append(t)
    return textos


_POLITICA_NA_RESPOSTA = re.compile(r"\bnao\s+(trabalhamos|fazemos|realizamos)\b|\bnossas?\s+politicas?\b")
_SO_CONTATO_ANTIGO = re.compile(r"\b(equipe|pessoal|vendedor\w*)\b|\b(horario|amanha|retoma\w*|fechad\w*|abre|abrimos)\b"
                         r"|\d{1,2}[:h]\d{2}|^(oi|ola|aqui e|bom dia|boa tarde|boa noite)\b")


def checar_texto_e_politica(res: "ResultadoRoteiro") -> None:
    """L11/L12:
    - FALHOU se o texto que o Léo escreveu junto da ferramenta não chegou ao cliente
      (as frases de "a equipe vai falar" e de horário não contam: a limpeza tira as repetidas);
    - AVISO se a resposta com chamado NÃO toca no assunto do cliente;
    - AVISO "afirmação de política: conferir na base" ("não trabalhamos com", "nossa política")."""
    from app.guarda_politica import _CONTATO_FRASE, _RETORNO, promete_contato_da_equipe
    for turno in res.turnos:
        if turno.do_job or not turno.bolhas:
            continue
        enviado = normalizar(" ".join(turno.bolhas))
        for texto in turno.antes_da_tool:
            pedacos = [f for f in frases(texto) if len(f) > 15 and not _CONTATO_FRASE.search(f)
                       and not _RETORNO.search(f) and not promete_contato_da_equipe(f)]
            if pedacos and not any(f in enviado for f in pedacos):
                res.falhas.append(f"o texto antes da ferramenta não chegou ao cliente: \"{texto[:90]}\"")
        if turno.avisos_vendedor and "?" in turno.fala and not toca_no_assunto(turno.fala, " ".join(turno.bolhas)):
            res.avisos.append(f"chamado aberto, mas a resposta não toca no assunto do cliente: \"{turno.fala[:60]}\"")
    achadas = [f for f in frases(res.texto_do_leo) if _POLITICA_NA_RESPOSTA.search(f)]
    res.avisos.extend(f"afirmação de política: conferir na base: \"{f[:100]}\"" for f in achadas)


# L12: "toca no assunto" = a resposta repete uma palavra de conteúdo da pergunta (pelo começo
# da palavra) ou diz "sobre (o/a/essa questão de) <assunto>".
_PALAVRAS_VAZIAS = {
    "voces", "voce", "tenho", "temos", "quero", "queria", "pode", "posso", "seria", "esse", "essa", "esta",
    "isso", "aqui", "loja", "mesmo", "mesma", "ainda", "sobre", "como", "quando", "quanto", "qual", "quais",
    "para", "pra", "pelo", "pela", "porque", "consigo", "consegue", "fazer", "falar", "equipe", "pessoal",
    "vendedor", "carro", "dele", "dela", "minha", "meu", "seus", "suas", "muito", "bem", "tambem", "entao",
}
_SOBRE_ASSUNTO = re.compile(r"\bsobre\s+(o|a|os|as|essa|esse|sua|seu|a\s+sua|o\s+seu)?\s*"
                            r"(questao|assunto|parte|duvida)?\s*(d[aoe]s?\s+)?([a-z]{4,})")


def _palavras(texto: str) -> list[str]:
    return [p for p in re.findall(r"[a-z]{4,}", normalizar(texto)) if p not in _PALAVRAS_VAZIAS]


# Palavras do mesmo assunto (pelo começo, 5 letras): "pagam" na pergunta e "avaliação" na
# resposta tocam no mesmo assunto; "sinal" e "reserva" também.
_MESMO_ASSUNTO = [
    {"pagam", "pagar", "pagou", "valor", "valem", "preco", "propo", "avali", "cobre", "cobra", "desco", "barat"},
    {"reser", "sinal", "segur", "guard", "separ"},
    {"troca", "troco", "trocar", "avali"},
    {"entre", "levar", "frete", "cidad"},
    {"docum", "papel", "trans", "laudo", "caute", "leila", "proce"},
    {"finan", "credi", "parce", "entra", "negat", "aprov", "renda", "compr", "autono"},
    {"ender", "local", "onde"},
]
_QUESTAO_DE = re.compile(r"\b(questao|assunto|parte)\s+(d[aoe]s?)\s+([a-z]{4,})")


def toca_no_assunto(pergunta: str, resposta: str) -> bool:
    resp = normalizar(resposta)
    palavras_resposta = {p[:5] for p in _palavras(resp)}
    da_pergunta = {p[:5] for p in _palavras(pergunta)}
    if da_pergunta & palavras_resposta:
        return True
    if any(grupo & da_pergunta and grupo & palavras_resposta for grupo in _MESMO_ASSUNTO):
        return True
    vazias = _PALAVRAS_VAZIAS | {"questao", "assunto", "duvida", "parte"}
    return (any(m.group(4) not in vazias for m in _SOBRE_ASSUNTO.finditer(resp))
            or any(m.group(3) not in vazias for m in _QUESTAO_DE.finditer(resp)))


# L12: ação prometida sem ferramenta e estado do carro sem ficha (FALHOU, todos os roteiros).
_FOTO_DITA = re.compile(r"\b(enviei|acabei\s+de\s+enviar|estou\s+enviando|aqui\s+estao\s+as\s+fotos"
                        r"|seguem\s+as\s+fotos|mandei\s+as\s+fotos)\b")


_TEXTO_INTERNO = re.compile(r"\[|\]|(^|\n)\s*(resumo|motivo)\s*:|\b(acionar_handoff|consultar_estoque|detalhes_veiculo"
                            r"|enviar_fotos|agendar_visita|simular_financiamento|registrar_\w+|buscar_conhecimento)\b",
                            re.IGNORECASE)


# N5: estas palavras só reprovam em frase AFIRMATIVA ("o carro foi revisado"); dentro de frase
# negativa ("não tenho informação sobre vistorias") não é afirmação de estado.
SO_EM_AFIRMACAO = ("vistoria", "inspecao", "revisado", "revisada", "verificacao")
_NEGACAO_NA_FRASE = re.compile(r"\b(nao|nem|sem|nenhum\w*|nunca\s+tive)\b")


def cita_afirmando(opcao: str, texto: str) -> bool:
    """A resposta cita `opcao` (já normalizada). Para as palavras de SO_EM_AFIRMACAO, só conta
    quando a frase não tem negação ANTES da palavra."""
    normal = normalizar(texto)
    if opcao not in normal:
        return False
    if not any(opcao.startswith(p) for p in SO_EM_AFIRMACAO):
        return True
    for frase in frases(texto):
        f = normalizar(frase)
        pos = f.find(opcao)
        if pos >= 0 and not _NEGACAO_NA_FRASE.search(f[:pos]):
            return True
    return False


def checar_texto_interno_e_repeticao(res: "ResultadoRoteiro") -> None:
    """M1 (FALHOU, todos os roteiros): texto interno ([...], "Resumo:", nome de ferramenta) chegando
    ao cliente, inclusive em job e na sugestão da sombra; duas respostas seguidas iguais."""
    # N2: a MESMA limpeza do Léo é a checagem (se ela ainda tiraria algo, o texto interno passou: GRAVE).
    from app.guarda_politica import tirar_texto_interno
    internos = []        # o que o MODELO mandou ao chamado (o resumo do código pode conter a resposta)
    for turno in res.turnos:
        internos += turno.internos
        for bolha in turno.bolhas:
            if tirar_texto_interno(bolha, internos, turno.tools)[1]:      # N5: ação feita não conta
                res.falhas.append(f"GRAVE: texto interno chegou ao cliente: \"{bolha[:100]}\"")
    for sugestao in res.sugestoes_texto:
        sem_fotos = re.sub(r"\[Fotos que o Léo mandaria:[^\]]*\]", "", sugestao)
        if tirar_texto_interno(sem_fotos, internos)[1]:
            res.falhas.append(f"GRAVE: texto interno na sugestão da sombra: \"{sugestao[:100]}\"")
    anteriores = [normalizar(" ".join(t.bolhas)).strip() for t in res.turnos if t.bolhas and not t.do_job]
    for a, b in zip(anteriores, anteriores[1:]):
        if a and a == b:
            res.falhas.append(f"duas respostas seguidas iguais: \"{a[:90]}\"")


def checar_acao_e_estado(res: "ResultadoRoteiro") -> None:
    from app.guarda_politica import AGENDOU_DITO, cortar_estado_inventado
    for turno in res.turnos:
        if turno.do_job or not turno.bolhas:
            continue
        texto = " ".join(turno.bolhas)
        normal = normalizar(texto)
        for frase in frases(texto):
            if AGENDOU_DITO.search(frase) and not frase.endswith("?") and not turno.agenda_gravou:
                res.falhas.append(f"disse que agendou sem a agenda gravar: \"{frase[:90]}\"")
            if _FOTO_DITA.search(frase) and not turno.fotos:
                res.falhas.append(f"disse que mandou foto sem foto sair: \"{frase[:90]}\"")
        if cortar_estado_inventado(texto, turno.ficha)[1]:
            res.promessas.append(f"afirmou estado do carro sem a ficha: \"{normal[:90]}\"")
        elif turno.original and cortar_estado_inventado(turno.original, turno.ficha)[1]:
            res.corrigidos.append("o modelo afirmou estado do carro, mas a guarda do código cortou")
    for sugestao in res.sugestoes_texto:
        for frase in frases(sugestao):
            if AGENDOU_DITO.search(frase) and not frase.endswith("?"):
                res.falhas.append(f"sugestão da sombra diz que agendou (sombra não grava): \"{frase[:90]}\"")
            if _FOTO_DITA.search(frase) and "fotos que o leo mandaria" not in normalizar(sugestao):
                res.falhas.append(f"sugestão da sombra diz que mandou foto sem guardar as fotos: \"{frase[:90]}\"")


def checar_emojis(res: "ResultadoRoteiro") -> None:
    """L10: checagem GLOBAL. Sem emoji se o cliente não usou; no máximo 1 por resposta;
    mensagem de job (remarketing/pós-venda): nenhum."""
    from app.guarda_politica import contar_emojis
    cliente_usou = False
    for turno in res.turnos:
        if not turno.do_job and contar_emojis(turno.fala):
            cliente_usou = True
        n = contar_emojis(" ".join(turno.bolhas))
        if not n:
            continue
        if turno.do_job:
            res.falhas.append(f"emoji em mensagem do job ({n}): \"{' '.join(turno.bolhas)[:80]}\"")
        elif not cliente_usou:
            res.falhas.append(f"emoji sem o cliente ter usado ({n}) na resposta a \"{turno.fala[:60]}\"")
        elif n > 1:
            res.falhas.append(f"{n} emojis numa resposta (máximo 1) a \"{turno.fala[:60]}\"")


def checar_job(res: "ResultadoRoteiro") -> None:
    """L6: checagens dos roteiros de job (toques, textos diferentes, horário, preço)."""
    from app.elegibilidade import no_horario_de_envio
    deve = res.roteiro["deve"]
    toques = [e for e in res.envios_job if e["tipo"] == "remarketing"]
    pos = [e for e in res.envios_job if e["tipo"] == "pos-venda"]
    if deve.get("toques") is not None:
        ok = len(toques) == deve["toques"]
        (res.ok if ok else res.falhas).append(
            f"toques de remarketing: {len(toques)} (esperado {deve['toques']})")
    if deve.get("envios_pos_venda") is not None:
        ok = len(pos) == deve["envios_pos_venda"]
        (res.ok if ok else res.falhas).append(
            f"mensagens de pós-venda: {len(pos)} (esperado {deve['envios_pos_venda']})")
    if deve.get("textos_diferentes"):
        parecidos = toques_parecidos([e["texto"] for e in toques])
        res.falhas.extend(parecidos)
        if not parecidos:
            res.ok.append(f"{len(toques)} toque(s) diferentes de verdade (abertura e semelhança)")
    if deve.get("envios_no_horario") and res.loja_do_job is not None:
        fora = [e for e in res.envios_job if not no_horario_de_envio(res.loja_do_job, e["quando"])]
        res.falhas.extend(f"envio fora do horário: {_hora_da_loja(res.loja_do_job, e['quando'])}" for e in fora)
        if not fora:
            res.ok.append(f"{len(res.envios_job)} envio(s), todos no horário de envio da loja")
    if "preco_inventado" in res.roteiro["nao_pode"]:
        for e in res.envios_job:
            fora = valores_em_reais(e["texto"]) - res.precos_do_estoque
            res.promessas.extend(f"preço fora do estoque no {e['tipo']}: \"{e['texto']}\"" for _ in [1] if fora)


async def rodar_roteiro(roteiro: dict, grafo, rodada: "Rodada") -> ResultadoRoteiro:
    from app.channels.base import enviar_resultado
    from app.channels.simulador import CanalSimulador
    from app.core.turno import MENSAGEM_ERRO, executar_turno, executar_turno_imagem

    res = ResultadoRoteiro(roteiro=roteiro)
    apontar_banco_temporario()
    preparar_loja(roteiro.get("loja"), roteiro.get("recados"))
    lead_id = roteiro["remetente"] or f"bancada-{_slug(roteiro['nome'])}"
    gravador = GrafoGravador(grafo)
    _limpar_memoria(grafo, lead_id)
    canal = CanalSimulador()

    def _registrar_envios(turno, desde, handoffs_antes):
        for tipo, conteudo in canal.enviadas[desde:]:
            (turno.fotos if tipo == "midia" else turno.bolhas).append(conteudo)
        for h in handoffs_abertos(lead_id)[handoffs_antes:]:
            turno.avisos_vendedor.append(h["motivo"])

    async def _depois_do_turno(turno, resultado, desde, antes):
        if rodada.tentativas_reais:
            raise EnvioRealBloqueado("; ".join(rodada.tentativas_reais))
        await enviar_resultado(canal, lead_id, resultado, loja_id=LOJA_ID)
        _registrar_envios(turno, desde, antes)
        turno.silenciado = resultado.silenciado
        if resultado.texto == MENSAGEM_ERRO:
            turno.erro = "o motor devolveu a mensagem de erro"
        if gravador.ultimo is not None:
            do_turno = mensagens_do_turno(gravador.ultimo)
            turno.tools = [c["name"] for m in do_turno for c in (getattr(m, "tool_calls", None) or [])]
            for m in do_turno:
                if m.__class__.__name__ == "ToolMessage":
                    res.valores_tools |= valores_em_reais(str(m.content))
            entrada, saida = tokens_das(do_turno)
            res.tokens_entrada += entrada
            res.tokens_saida += saida
            rodada.tokens_entrada += entrada
            rodada.tokens_saida += saida
            original = resposta_do_turno(do_turno, gravador.ultimo["messages"][-1])   # L11
            turno.antes_da_tool = textos_antes_da_tool(do_turno)
            turno.internos = internos_do_turno(do_turno)   # N2
            turno.ficha = _fichas_do_turno(do_turno)                         # L12
            turno.agenda_gravou = _agenda_do_turno(do_turno) is not None
            turno.original = original
            if resposta_tem_preco_inventado(original, gravador.ultimo["messages"]):
                turno.barrado = original
        res.turnos.append(turno)

    async def _turno(fala_do_relatorio, chamar):
        turno = Turno(fala=fala_do_relatorio)
        gravador.ultimo = None
        desde, antes = len(canal.enviadas), len(handoffs_abertos(lead_id))
        resultado = await chamar()
        turno.foto_lida = getattr(resultado, "leitura_imagem", None)
        uso = getattr(resultado, "uso_imagem", None)
        if uso is not None:                      # L5: a leitura da foto entra no custo
            res.tokens_imagem_entrada += uso.tokens_entrada
            res.tokens_imagem_saida += uso.tokens_saida
            res.tokens_entrada += uso.tokens_entrada
            res.tokens_saida += uso.tokens_saida
            rodada.tokens_entrada += uso.tokens_entrada
            rodada.tokens_saida += uso.tokens_saida
        await _depois_do_turno(turno, resultado, desde, antes)

    async def _turno_de_audio(caminho: Path):
        from app.api.receber_audio import transcrever_do_cliente
        from app.core.turno import turno_audio_falhou
        transcrito = {}

        async def _chamar():
            from app.core.turno import turno_midia_grande
            from app.limites_midia import MidiaGrandeDemais
            try:
                texto, uso = await asyncio.to_thread(
                    transcrever_do_cliente, LOJA_ID, lead_id, CANAL, caminho.read_bytes(),
                    _mime_do_audio(caminho.name), transcritor=rodada.transcritor)
            except MidiaGrandeDemais:                       # N2: áudio grande demais, sem IA
                transcrito["texto"] = None
                return turno_midia_grande(LOJA_ID, CANAL, lead_id, "audio")
            transcrito["texto"] = texto
            res.transcricoes.append(texto or "")
            res.tokens_audio += uso.tokens_audio
            res.tokens_transcricao += uso.tokens_entrada + uso.tokens_saida
            res.tokens_entrada += uso.tokens_entrada
            res.tokens_saida += uso.tokens_saida
            rodada.tokens_audio += uso.tokens_audio
            rodada.tokens_entrada += uso.tokens_entrada
            rodada.tokens_saida += uso.tokens_saida
            if not texto:
                return turno_audio_falhou(LOJA_ID, CANAL, lead_id)
            return await executar_turno(LOJA_ID, CANAL, lead_id, texto, grafo=gravador)

        await _turno(f"[áudio: {caminho.name}]", _chamar)
        if res.turnos:
            res.turnos[-1].fala = (f"[áudio: {caminho.name}] transcrição: \"{transcrito.get('texto')}\""
                                   if transcrito.get("texto") else f"[áudio: {caminho.name}] (transcrição vazia)")

    foto = None
    if roteiro["imagem"]:
        caminho = RAIZ / roteiro["imagem"]
        if not caminho.is_file():
            res.avisos.append(f"{IMAGEM_AUSENTE}: {roteiro['imagem']}")
        else:
            foto = (caminho.name, caminho.read_bytes(), _mime_da_imagem(caminho.name))
    elif roteiro.get("imagem_texto"):
        foto = ("imagem gerada", gerar_imagem_de_texto(roteiro["imagem_texto"]), "image/png")
    if foto:
        nome, conteudo, mime = foto
        legenda = roteiro.get("legenda") or ""
        await _turno(f"[foto: {nome}] {legenda}".strip(),
                     lambda: executar_turno_imagem(LOJA_ID, CANAL, lead_id, conteudo, mime, legenda,
                                                   grafo=gravador, leitor=rodada.leitor))

    if roteiro.get("audio"):        # M3: o áudio passa pela MESMA transcrição dos canais
        caminho = RAIZ / roteiro["audio"]
        if not caminho.is_file():
            res.avisos.append(f"{AUDIO_AUSENTE}: {roteiro['audio']}")
        else:
            await _turno_de_audio(caminho)

    if roteiro.get("rajada"):       # L7: mensagens seguidas, pelo debounce de verdade (Redis falso)
        desde, antes = len(canal.enviadas), len(handoffs_abertos(lead_id))
        gravador.ultimo = None
        respondidas = await processar_rajada(
            roteiro["rajada"], lead_id,
            lambda juntado: executar_turno(LOJA_ID, CANAL, lead_id, juntado, grafo=gravador))
        res.respostas_rajada = len(respondidas)
        for juntado, resultado in respondidas:
            await _depois_do_turno(Turno(fala=f"[rajada] {juntado}"), resultado, desde, antes)

    for fala in roteiro["falas"]:
        if rodada.gasto_usd >= rodada.teto:
            res.parou_no_teto = rodada.parou_no_teto = True
            break
        await _turno(fala, lambda fala=fala: executar_turno(LOJA_ID, CANAL, lead_id, fala, grafo=gravador))

    res.motivos_finais = [h["motivo"] or "" for h in handoffs_abertos(lead_id)]
    res.mensagens_gravadas = _ler("SELECT COUNT(*) n FROM mensagens WHERE loja_id = ? AND lead_id = ?",
                                  (LOJA_ID, lead_id))[0]["n"]
    res.trocas_gravadas = _ler("SELECT COUNT(*) n FROM trocas WHERE loja_id = ? AND lead_id = ?",
                               (LOJA_ID, lead_id))[0]["n"]
    res.sugestoes_sombra = _ler("SELECT COUNT(*) n FROM sombra_sugestoes WHERE loja_id = ? AND lead_id = ?",
                                (LOJA_ID, lead_id))[0]["n"]
    res.sugestoes_texto = [l["sugestao"] for l in _ler(
        "SELECT sugestao FROM sombra_sugestoes WHERE loja_id = ? AND lead_id = ? ORDER BY id", (LOJA_ID, lead_id))]
    _limpar_memoria(grafo, lead_id)          # L12: a conversa do roteiro não fica na memória do grafo
    res.chamados_gravados = len(handoffs_abertos(lead_id))
    checar(res)
    return res


# ======================================================================
# RODADA E RELATÓRIO
# ======================================================================

@dataclass
class Rodada:
    teto: float
    leitor: object = None          # L5: quem lê a foto (None = IA de verdade; testes passam um falso)
    redator: object = None         # L6: quem escreve o remarketing (None = IA de verdade)
    tokens_entrada: int = 0
    tokens_saida: int = 0
    tokens_audio: int = 0          # M3
    transcritor: object = None     # M3: quem transcreve o áudio (None = IA de verdade; testes passam um falso)
    parou_no_teto: bool = False
    abortada: str | None = None
    tentativas_reais: list = field(default_factory=list)
    resultados: list = field(default_factory=list)

    @property
    def gasto_usd(self) -> float:
        return custo_usd(self.tokens_entrada, self.tokens_saida, self.tokens_audio)


async def rodar(roteiros: list[dict], grafo, teto: float | None = None, leitor=None,
                redator=None, transcritor=None) -> Rodada:
    rodada = Rodada(teto=teto_usd() if teto is None else teto, leitor=leitor, redator=redator,
                    transcritor=transcritor)
    with bloquear_envio_real(rodada.tentativas_reais), ator.como("Bancada", "sistema", "job"):
        for roteiro in roteiros:
            if rodada.parou_no_teto:
                rodada.resultados.append(ResultadoRoteiro(roteiro=roteiro))
                continue
            try:
                executor = rodar_roteiro_job if roteiro.get("passos") else rodar_roteiro
                base = roteiro.get("conhecimento") or (_politicas_demo() if _LOJA_DEMO else None)
                with base_ficticia(base):
                    rodada.resultados.append(await executor(roteiro, grafo, rodada))
            except EnvioRealBloqueado as erro:
                rodada.abortada = str(erro)
                break
    return rodada


def _linha_status(res: ResultadoRoteiro) -> str:
    return res.alerta or res.status


def montar_relatorio(rodada: Rodada, modelo: str = "") -> str:
    agora = datetime.now()
    linhas = [f"# Bancada do Léo — rodada de {agora:%d/%m/%Y %H:%M}", ""]
    linhas.append((f"Modelo: {modelo} · " if modelo else "") + f"Teto: US$ {rodada.teto:.2f} (LEO_API_TETO_USD) · gasto estimado: "
                  f"US$ {rodada.gasto_usd:.4f} ({rodada.tokens_entrada} tokens de entrada, "
                  f"{rodada.tokens_saida} de saída). Embeddings da busca de conhecimento fora da conta.")
    if rodada.parou_no_teto:
        linhas += ["", "**RODADA INCOMPLETA: o teto de gasto foi atingido.**"]
    if rodada.abortada:
        linhas += ["", f"**RODADA ABORTADA: {rodada.abortada}**"]
    linhas.append("")

    for i, res in enumerate(rodada.resultados, 1):
        r = res.roteiro
        linhas += [f"## {i}. {r['nome']} — {_linha_status(res)}", ""]
        info = [f"arquivo `{r['arquivo']}.yaml`"]
        if r["pendente"]:
            info.append(f"pendente: {r['pendente']}")
        if r["remetente"]:
            info.append(f"remetente: {r['remetente']}")
        for recado in r.get("recados") or []:
            info.append(f"recado: \"{recado['texto']}\" (validade {recado['valido_ate']})")
        info.append(f"custo: US$ {res.custo_usd:.4f}")
        if r.get("audio"):
            info.append(f"áudio: {r['audio']}")
        if res.tokens_audio or res.tokens_transcricao:
            info.append(f"transcrição do áudio: {res.tokens_audio} tokens de áudio + {res.tokens_transcricao} "
                        f"de texto (US$ {custo_usd(0, 0, res.tokens_audio):.4f} de áudio; já dentro do custo)")
        if res.tokens_imagem_entrada or res.tokens_imagem_saida:
            info.append(f"leitura da foto: US$ {custo_usd(res.tokens_imagem_entrada, res.tokens_imagem_saida):.4f} "
                        f"({res.tokens_imagem_entrada} tokens de entrada, {res.tokens_imagem_saida} de saída; "
                        "já dentro do custo)")
        linhas += [" · ".join(info), ""]
        if res.status == NAO_RODOU:
            linhas += ["Não rodou (teto de gasto atingido antes).", ""]
            continue
        for turno in res.turnos:
            linhas.append(f"**Cliente:** {turno.fala}  ")
            if turno.silenciado:
                linhas.append("_(Léo em silêncio)_  ")
            if turno.foto_lida:
                erro = turno.foto_lida.get("erro")
                extra = (f" · erro: {erro}, tentativas: {turno.foto_lida.get('tentativas', 1)}"
                         if erro else "")
                linhas.append(f"🖼️ foto lida como **{turno.foto_lida['tipo']}**: "
                              f"{turno.foto_lida['descricao'] or '(sem descrição)'}{extra}  ")
            for bolha in turno.bolhas:
                linhas.append(f"**Léo:** {bolha}  ")
            for foto in turno.fotos:
                linhas.append(f"📷 foto que seria enviada: {foto}  ")
            if turno.tools:
                linhas.append(f"🔧 tools: {', '.join(turno.tools)}  ")
            for aviso in turno.avisos_vendedor:
                linhas.append(f"🔔 aviso ao vendedor (chamado aberto): {aviso}  ")
            if turno.barrado:
                linhas.append(f"🛑 a guarda de preço barrou: \"{turno.barrado}\"  ")
            if (turno.original and turno.bolhas
                    and normalizar(turno.original).split() != normalizar(" ".join(turno.bolhas)).split()):
                linhas.append(f"🧠 o modelo escreveu (antes das guardas e da limpeza): \"{turno.original}\"  ")
            if turno.erro:
                linhas.append(f"⚠️ erro: {turno.erro}  ")
            linhas.append("")
        linhas.append("Checagens:")
        linhas += [f"- ✅ {t}" for t in res.ok]
        linhas += [f"- ❌ PROMESSA: {t}" for t in res.promessas]
        linhas += [f"- ❌ {t}" for t in res.falhas]
        linhas += [f"- ⚠️ {t}" for t in res.avisos]
        linhas += [f"- 🛠️ corrigido pela guarda: {t}" for t in res.corrigidos]
        linhas.append("")

    contagem: dict[str, int] = {}
    for res in rodada.resultados:
        chave = PENDENTE if res.status.startswith(PENDENTE) else res.status
        contagem[chave] = contagem.get(chave, 0) + 1
    alertas = sum(1 for res in rodada.resultados if res.alerta)
    linhas += ["## Resumo", "", "| Resultado | Roteiros |", "|---|---|"]
    for chave in (PASSOU, CORRIGIDO, AVISO, FALHOU, PENDENTE, NAO_RODOU):
        linhas.append(f"| {chave} | {contagem.get(chave, 0)} |")
    linhas += ["", f"Pendentes que passaram (tirar o pendente): {alertas}",
               f"Custo total: US$ {rodada.gasto_usd:.4f} (teto US$ {rodada.teto:.2f})", ""]
    return "\n".join(linhas)


def salvar_relatorio(texto: str, pasta: Path = PASTA_RELATORIO) -> Path:
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / f"rodada_{datetime.now():%Y-%m-%d_%H%M%S}.md"
    caminho.write_text(texto, encoding="utf-8")
    return caminho


def main(argv=None) -> int:
    # L6: os jobs imprimem o texto que mandariam (pode ter emoji); o terminal do Windows
    # (cp1252) quebrava a rodada inteira. Na bancada, a tela é UTF-8 e o que não couber vira "?".
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(description="Bancada de testes do Léo (Gemini real).")
    parser.add_argument("--roteiro", help="nome do roteiro (ou do arquivo, sem .yaml)")
    parser.add_argument("--loja-demo", action="store_true",
                        help="M2: roda os roteiros demo_*.yaml contra a loja de demonstração")
    args = parser.parse_args(argv)
    global _LOJA_DEMO
    _LOJA_DEMO = bool(args.loja_demo)

    from dotenv import load_dotenv
    load_dotenv(RAIZ / ".env")
    chave = os.environ.get("GOOGLE_API_KEY", "")
    if not chave or chave.startswith("chave-falsa"):
        print("GOOGLE_API_KEY real não encontrada no .env. Nada foi gasto.")
        return 2

    try:
        roteiros = carregar_roteiros(so=args.roteiro, demo=_LOJA_DEMO)
    except RoteiroInvalido as erro:
        print(f"Roteiro com problema: {erro}. Nada foi gasto.")
        return 2
    # Banco e logs temporários ANTES de importar o agente (nada toca o loja.db).
    logs.PASTA_LOGS = str(pasta_temporaria() / "logs")
    apontar_banco_temporario()
    import app.core.agent as agent
    from app.config import MODELO_LLM

    try:
        rodada = asyncio.run(rodar(roteiros, agent.agente_grafo))
    finally:
        shutil.rmtree(pasta_temporaria(), ignore_errors=True)
    caminho = salvar_relatorio(montar_relatorio(rodada, MODELO_LLM))
    print(f"\nRelatório: {caminho}")
    if rodada.abortada:
        print(f"BANCADA ABORTADA: {rodada.abortada}")
        return 3
    for res in rodada.resultados:
        print(f"  {_linha_status(res):<20} {res.roteiro['nome']}")
    print(f"Custo total: US$ {rodada.gasto_usd:.4f} (teto US$ {rodada.teto:.2f})")
    return 1 if any(r.status == FALHOU for r in rodada.resultados) else 0


if __name__ == "__main__":
    sys.exit(main())
