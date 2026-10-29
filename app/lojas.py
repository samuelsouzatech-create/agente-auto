"""
Configuração por loja (Arquitetura 4.0, seção 4 e item 1.2).

Três tipos de variável:
- REGRA DE PRODUTO: constante neste arquivo; a loja nunca altera.
- PREFERÊNCIA DA LOJA: tem padrão em PADROES e é editável via salvar_config().
- MEDIÇÃO: vem do piloto (fica em PADROES até ser medida).

Cada chave editável tem um DONO:
- "cliente": a própria loja pode mudar pelo painel dela.
- "operador": só você muda (plano, módulos contratados, limites, custos).

A tabela lojas guarda só o que a loja MUDOU. carregar_loja() completa o
resto com PADROES, e por isso uma loja nova nunca quebra.
"""
from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from banco import conectar
from app.segmentos import segmento_existe, segmentos_disponiveis

# ---------------------------------------------------------------------
# Regras de produto (não aparecem na tela, não são editáveis)
# ---------------------------------------------------------------------
MAX_BOLHAS = 3
TETO_TOQUES_REMARKETING = 3
MIN_HORAS_SEM_RESPOSTA = 24
MODULOS = ("whatsapp", "instagram", "agendamento", "fotos", "remarketing", "pos_venda")

# Chaves que alguém pode tentar editar, mas que são regra de produto.
REGRAS_DE_PRODUTO = {
    "atendimento.max_bolhas",
    "remarketing.parar_ao_responder",
    "remarketing.respeitar_optout",
    "financiamento.aviso_estimativa",
    "identificacao_virtual",
    "preco_so_por_tool",
}

# ---------------------------------------------------------------------
# Papéis: quem pode mexer em quê
# ---------------------------------------------------------------------
PAPEIS = ("cliente", "operador")

# Chaves que só o operador altera (fazem parte do plano / contrato / custo).
# Todo o resto do EDITAVEIS pertence ao cliente.
CHAVES_DO_OPERADOR = frozenset({
    *(f"modulos.{m}" for m in MODULOS),
    "custos.teto_diario_llm",
    "remarketing.limite_mensal",
    "instagram.limite_private_replies_h",
})

# ---------------------------------------------------------------------
# Padrões do produto (tabela da seção 4)
# ---------------------------------------------------------------------
PADROES: dict = {
    "nome_agente": "Léo",
    "cidade": "",
    "tom": "simples, cordial e direto",
    "fuso": "America/Recife",
    "atendimento": {
        "horario_humano": "09:00-18:00",
        "dias_humano": [0, 1, 2, 3, 4, 5],        # 0 = segunda ... 6 = domingo
        "debounce_s": 8.0,                        # medição: o PDF sugere 3 a 5 s
        "aguardando_vendedor": "meio_termo",      # decisão 1.12
    },
    "modulos": {
        "whatsapp": True, "instagram": False, "agendamento": True,
        "fotos": True, "remarketing": False, "pos_venda": False,
    },
    "handoff": {"reaviso_min": 5, "gestor_min": 10},
    "remarketing": {
        "primeiro_toque_h": 48,
        "intervalos_h": [48, 120, 288],
        "max_toques": 3,
        "horario_envio": "09:00-19:00",
        "dias_envio": [0, 1, 2, 3, 4, 5],
        "limite_mensal": None,                    # definido no contrato
    },
    "pos_venda": {
        "revisao_meses": 6, "revisao_km": 10000,
        "troca_avista_meses": 12, "troca_financiado_meses_restantes": 12,
    },
    "financiamento": {"taxa_mensal": 0.019},
    "instagram": {
        "responder_comentarios": False,
        "palavras_comentario": ["quero", "valor", "preço", "info"],
        "posts_comentario": "todos",
        "resposta_publica": False,
        "limite_private_replies_h": 20,
        "texto_private_reply": "Oi! Vi seu comentário, te chamei por aqui para te ajudar 🙂",
    },
    "custos": {"teto_diario_llm": None},
    "dados": {"retencao_dias": None},            # a definir com o advogado
}


# ---------------------------------------------------------------------
# Validadores
# ---------------------------------------------------------------------
_HORARIO = re.compile(r"^([01]\d|2[0-3]):[0-5]\d-([01]\d|2[0-3]):[0-5]\d$")


def _int(minimo: int, maximo: int) -> Callable:
    def validar(v):
        if isinstance(v, bool) or not isinstance(v, int):
            raise ValueError("precisa ser um número inteiro")
        if not minimo <= v <= maximo:
            raise ValueError(f"precisa estar entre {minimo} e {maximo}")
        return v
    return validar


def _float(minimo: float, maximo: float) -> Callable:
    def validar(v):
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError("precisa ser um número")
        if not minimo <= v <= maximo:
            raise ValueError(f"precisa estar entre {minimo} e {maximo}")
        return float(v)
    return validar


def _bool(v):
    if not isinstance(v, bool):
        raise ValueError("precisa ser verdadeiro ou falso")
    return v


def _texto(minimo: int, maximo: int) -> Callable:
    def validar(v):
        if not isinstance(v, str):
            raise ValueError("precisa ser texto")
        v = v.strip()
        if not minimo <= len(v) <= maximo:
            raise ValueError(f"precisa ter entre {minimo} e {maximo} caracteres")
        return v
    return validar


def _opcao(*opcoes: str) -> Callable:
    def validar(v):
        if v not in opcoes:
            raise ValueError(f"opções válidas: {', '.join(opcoes)}")
        return v
    return validar


def _faixa_horario(inicio_min: str = "00:00", fim_max: str = "23:59") -> Callable:
    def validar(v):
        if not isinstance(v, str) or not _HORARIO.match(v):
            raise ValueError('use o formato "HH:MM-HH:MM", ex.: "09:00-19:00"')
        inicio, fim = v.split("-")
        if inicio >= fim:
            raise ValueError("o início precisa ser antes do fim")
        if inicio < inicio_min or fim > fim_max:
            raise ValueError(f"precisa ficar entre {inicio_min} e {fim_max}")
        return v
    return validar


def _dias(v):
    if (not isinstance(v, list) or not v
            or any(isinstance(d, bool) or not isinstance(d, int) or not 0 <= d <= 6 for d in v)):
        raise ValueError("lista de dias de 0 (segunda) a 6 (domingo), com ao menos um dia")
    return sorted(set(v))


def _lista_int(minimo: int, maximo: int, max_itens: int) -> Callable:
    def validar(v):
        if not isinstance(v, list) or not 1 <= len(v) <= max_itens:
            raise ValueError(f"lista com 1 a {max_itens} valores")
        return [_int(minimo, maximo)(x) for x in v]
    return validar


def _lista_texto(max_itens: int = 30, max_len: int = 40) -> Callable:
    def validar(v):
        if not isinstance(v, list) or not 1 <= len(v) <= max_itens:
            raise ValueError(f"lista com 1 a {max_itens} palavras")
        return [_texto(1, max_len)(x) for x in v]
    return validar


def _todos_ou_lista(v):
    if v == "todos":
        return v
    return _lista_texto(max_itens=200, max_len=64)(v)


def _opcional(validador: Callable) -> Callable:
    def validar(v):
        return None if v is None else validador(v)
    return validar


def _fuso(v):
    try:
        ZoneInfo(v)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise ValueError('fuso inválido (ex.: "America/Recife")')
    return v


# Tudo o que a tela de Configuração pode alterar. O que não está aqui é recusado.
EDITAVEIS: dict[str, Callable] = {
    "nome_agente": _texto(1, 40),
    "cidade": _texto(0, 80),
    "tom": _texto(1, 200),
    "fuso": _fuso,
    "atendimento.horario_humano": _faixa_horario(),
    "atendimento.dias_humano": _dias,
    "atendimento.debounce_s": _float(1, 20),
    "atendimento.aguardando_vendedor": _opcao("conversar", "esperar", "meio_termo"),
    "handoff.reaviso_min": _int(1, 120),
    "handoff.gestor_min": _int(1, 240),
    "remarketing.primeiro_toque_h": _int(MIN_HORAS_SEM_RESPOSTA, 720),
    "remarketing.intervalos_h": _lista_int(MIN_HORAS_SEM_RESPOSTA, 720, TETO_TOQUES_REMARKETING),
    "remarketing.max_toques": _int(1, TETO_TOQUES_REMARKETING),
    "remarketing.horario_envio": _faixa_horario("08:00", "21:00"),
    "remarketing.dias_envio": _dias,
    "remarketing.limite_mensal": _opcional(_int(0, 100_000)),
    "pos_venda.revisao_meses": _int(1, 24),
    "pos_venda.revisao_km": _int(1000, 50_000),
    "pos_venda.troca_avista_meses": _int(3, 60),
    "pos_venda.troca_financiado_meses_restantes": _int(1, 60),
    "financiamento.taxa_mensal": _float(0.001, 0.06),
    "instagram.responder_comentarios": _bool,
    "instagram.palavras_comentario": _lista_texto(),
    "instagram.posts_comentario": _todos_ou_lista,
    "instagram.resposta_publica": _bool,
    "instagram.limite_private_replies_h": _int(1, 200),
    "instagram.texto_private_reply": _texto(1, 300),
    "custos.teto_diario_llm": _opcional(_float(0, 10_000)),
    "dados.retencao_dias": _opcional(_int(30, 3650)),
    **{f"modulos.{m}": _bool for m in MODULOS},
}

# Garantia: toda chave do operador precisa existir no EDITAVEIS.
assert CHAVES_DO_OPERADOR <= set(EDITAVEIS), "CHAVES_DO_OPERADOR tem chave fora do EDITAVEIS"


def dono_da_chave(chave: str) -> str:
    """Quem pode alterar a chave: "operador" ou "cliente".
    Chave desconhecida ou regra de produto levanta KeyError."""
    if chave not in EDITAVEIS:
        raise KeyError(chave)
    return "operador" if chave in CHAVES_DO_OPERADOR else "cliente"


def chaves_do(papel: str) -> list[str]:
    """Chaves que pertencem a um papel (na ordem do EDITAVEIS)."""
    _validar_papel(papel)
    return [c for c in EDITAVEIS if dono_da_chave(c) == papel]


# ---------------------------------------------------------------------
# Erros
# ---------------------------------------------------------------------
class LojaNaoEncontrada(LookupError):
    pass


class ConfigInvalida(ValueError):
    def __init__(self, erros: list[str]):
        self.erros = erros
        super().__init__("; ".join(erros))


class SemPermissao(ConfigInvalida):
    """Quem salvou não tem papel para alterar uma das chaves (ex.: cliente mexendo no plano)."""


class ConflitoDeVersao(RuntimeError):
    """Outra pessoa salvou a configuração ao mesmo tempo. Recarregue e tente de novo."""


def _validar_papel(papel: str) -> None:
    if papel not in PAPEIS:
        raise ConfigInvalida([f"papel '{papel}' não existe (válidos: {', '.join(PAPEIS)})"])


# ---------------------------------------------------------------------
# Modelo
# ---------------------------------------------------------------------
@dataclass(frozen=True)
class Loja:
    id: int
    nome: str
    segmento: str
    config: dict
    versao_config: int
    ativo: bool

    def get(self, chave: str, padrao: Any = None) -> Any:
        """Lê por caminho com ponto: loja.get("remarketing.max_toques")."""
        try:
            return _ler_chave(self.config, chave)
        except KeyError:
            return padrao


def _mesclar(base: dict, custom: dict) -> dict:
    """Completa custom com base. Dicts se mesclam; listas e valores substituem."""
    resultado = copy.deepcopy(base)
    for chave, valor in custom.items():
        if isinstance(valor, dict) and isinstance(resultado.get(chave), dict):
            resultado[chave] = _mesclar(resultado[chave], valor)
        else:
            resultado[chave] = copy.deepcopy(valor)
    return resultado


def _ler_chave(d: dict, caminho: str) -> Any:
    atual = d
    for parte in caminho.split("."):
        if not isinstance(atual, dict) or parte not in atual:
            raise KeyError(caminho)
        atual = atual[parte]
    return atual


def _gravar_chave(d: dict, caminho: str, valor: Any) -> None:
    partes = caminho.split(".")
    atual = d
    for parte in partes[:-1]:
        atual = atual.setdefault(parte, {})
    atual[partes[-1]] = valor


def _ler_json(texto: str | None, loja_id: int) -> dict:
    try:
        dados = json.loads(texto or "{}")
        return dados if isinstance(dados, dict) else {}
    except json.JSONDecodeError:
        print(f"[Lojas] AVISO: config da loja {loja_id} corrompida; usando padrões.")
        return {}


# ---------------------------------------------------------------------
# Cache: (loja_id, versao_config) -> config mesclada.
# Mudou a versão, a próxima leitura remonta. Sem reiniciar o servidor.
# ---------------------------------------------------------------------
_cache_config: dict[tuple[int, int], dict] = {}


def limpar_cache() -> None:
    _cache_config.clear()


def carregar_loja(loja_id: int) -> Loja:
    conexao = conectar()
    try:
        linha = conexao.execute("SELECT * FROM lojas WHERE id = ?", (loja_id,)).fetchone()
    finally:
        conexao.close()
    if linha is None:
        raise LojaNaoEncontrada(f"Loja {loja_id} não existe.")

    chave_cache = (linha["id"], linha["versao_config"])
    if chave_cache not in _cache_config:
        _cache_config[chave_cache] = _mesclar(PADROES, _ler_json(linha["config"], loja_id))

    return Loja(
        id=linha["id"],
        nome=linha["nome"],
        segmento=linha["segmento"],
        config=copy.deepcopy(_cache_config[chave_cache]),
        versao_config=linha["versao_config"],
        ativo=bool(linha["ativo"]),
    )


def modulo_ativo(loja: Loja, nome: str) -> bool:
    """O 'disjuntor'. Módulo desconhecido conta como desligado."""
    return bool(loja.config.get("modulos", {}).get(nome, False))


def pendentes(loja: Loja, papel: str | None = None) -> list[str]:
    """Variáveis ainda no padrão do produto, não confirmadas com o cliente
    (a marca 'padrão, a confirmar' da tela).
    Com papel, devolve só as pendências daquele dono."""
    confirmados = set(loja.config.get("_confirmados", []))
    chaves = EDITAVEIS if papel is None else chaves_do(papel)
    return [chave for chave in chaves if chave not in confirmados]


def salvar_config(loja_id: int, mudancas: dict[str, Any], usuario: str,
                  papel: str = "operador") -> Loja:
    """Valida TUDO antes de gravar (ou grava tudo, ou nada), registra cada
    mudança em config_historico e incrementa versao_config.
    Salvar o mesmo valor do padrão é válido e marca a chave como confirmada.

    papel: "operador" pode tudo; "cliente" só as chaves dele. Se o cliente
    tentar mexer em chave do operador, NADA é gravado (SemPermissao).
    O padrão é "operador" para scripts e testes antigos; as páginas do
    painel sempre passam o papel explicitamente."""
    _validar_papel(papel)
    if not mudancas:
        raise ConfigInvalida(["nenhuma mudança enviada"])

    # 1) Permissão primeiro: cliente mexendo no plano recusa tudo.
    if papel == "cliente":
        negadas = [
            f"{chave}: só o operador pode alterar"
            for chave in mudancas
            if chave in CHAVES_DO_OPERADOR
        ]
        if negadas:
            raise SemPermissao(negadas)

    # 2) Validação dos valores.
    erros, validadas = [], {}
    for chave, valor in mudancas.items():
        if chave in REGRAS_DE_PRODUTO:
            erros.append(f"{chave}: é regra do produto e não pode ser alterada")
            continue
        validador = EDITAVEIS.get(chave)
        if validador is None:
            erros.append(f"{chave}: configuração desconhecida")
            continue
        try:
            validadas[chave] = validador(valor)
        except ValueError as e:
            erros.append(f"{chave}: {e}")
    if erros:
        raise ConfigInvalida(erros)

    # 3) Gravação (tudo ou nada).
    conexao = conectar()
    try:
        linha = conexao.execute(
            "SELECT config, versao_config FROM lojas WHERE id = ?", (loja_id,)
        ).fetchone()
        if linha is None:
            raise LojaNaoEncontrada(f"Loja {loja_id} não existe.")

        custom = _ler_json(linha["config"], loja_id)
        efetiva_antes = _mesclar(PADROES, custom)
        confirmados = set(custom.get("_confirmados", []))
        historico = []
        for chave, valor in validadas.items():
            try:
                antigo = _ler_chave(efetiva_antes, chave)
            except KeyError:
                antigo = None
            _gravar_chave(custom, chave, valor)
            confirmados.add(chave)
            historico.append((
                loja_id, usuario, chave,
                json.dumps(antigo, ensure_ascii=False),
                json.dumps(valor, ensure_ascii=False),
            ))
        custom["_confirmados"] = sorted(confirmados)

        # Trava otimista: só grava se ninguém salvou entre a leitura e aqui.
        cursor = conexao.execute(
            "UPDATE lojas SET config = ?, versao_config = versao_config + 1 "
            "WHERE id = ? AND versao_config = ?",
            (json.dumps(custom, ensure_ascii=False), loja_id, linha["versao_config"]),
        )
        if cursor.rowcount == 0:
            conexao.rollback()
            raise ConflitoDeVersao("A configuração mudou enquanto você editava. Recarregue.")

        conexao.executemany(
            "INSERT INTO config_historico (loja_id, usuario, chave, valor_antigo, valor_novo) "
            "VALUES (?, ?, ?, ?, ?)",
            historico,
        )
        conexao.commit()
    finally:
        conexao.close()

    return carregar_loja(loja_id)


def criar_loja(nome: str, segmento: str = "veiculos",
               config: dict[str, Any] | None = None, usuario: str = "operador") -> int:
    """Cria uma loja nova (config vazia = todos os padrões). Se vier config,
    ela passa pela mesma validação da tela. Só o operador cria lojas."""
    if not segmento_existe(segmento):
        raise ConfigInvalida([f"segmento '{segmento}' não existe "
                              f"(disponíveis: {segmentos_disponiveis()})"])
    _texto(1, 80)(nome)
    conexao = conectar()
    try:
        cursor = conexao.execute(
            "INSERT INTO lojas (nome, segmento, config) VALUES (?, ?, '{}')",
            (nome.strip(), segmento),
        )
        loja_id = cursor.lastrowid
        conexao.commit()
    finally:
        conexao.close()
    if config:
        salvar_config(loja_id, config, usuario, papel="operador")
    return loja_id


def historico_config(loja_id: int, limite: int = 50) -> list[dict]:
    conexao = conectar()
    try:
        linhas = conexao.execute(
            "SELECT usuario, chave, valor_antigo, valor_novo, criado_em "
            "FROM config_historico WHERE loja_id = ? ORDER BY id DESC LIMIT ?",
            (loja_id, limite),
        ).fetchall()
    finally:
        conexao.close()
    return [dict(l) for l in linhas]

def __getattr__(nome: str):
    """Compatibilidade: SEGMENTOS deixou de ser lista fixa (Etapa 2, Bloco 1).
    Quem ainda importa SEGMENTOS recebe os segmentos lidos das pastas."""
    if nome == "SEGMENTOS":
        return set(segmentos_disponiveis())
    raise AttributeError(f"module {__name__!r} has no attribute {nome!r}")
