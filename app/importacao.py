"""
Importação da base da loja por planilha (Etapa 2, Bloco 6A).

A loja já tem anos de clientes. Eles entram por um CSV (exportado do CRM ou
salvo do Excel), em dois passos:
  1. ler_planilha(conteudo) -> Previa. Só lê e confere; NÃO grava nada.
  2. importar(loja_id, previa, ...) -> grava tudo numa transação só.

O que entra:
  contatos            nome + telefone normalizado (um por telefone, por loja)
  compras_anteriores  o que comprou + data (+ pagamento), quando a linha tem compra

Consentimento: marcado na importação inteira por quem importa (nome e data
ficam gravados). Sem ele, o contato fica guardado e é reconhecido pelo
assistente, mas a loja não manda nada por iniciativa própria (Bloco 6B).
Desfazer: apaga as compras daquela importação e os contatos que ela CRIOU.
"""
from __future__ import annotations

import csv
import io
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from banco import conectar
from app.chaves import exigir_loja
from app.relogio import agora_utc, para_banco
from app.telefone import normalizar_telefone_br

MAX_BYTES = 5 * 1024 * 1024
MAX_LINHAS = 20_000
MAX_MESES = 120
MAX_TEXTO = 80
_EXCEL_ZERO = date(1899, 12, 30)          # o "dia zero" das datas do Excel
_FORMATOS_DATA = ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y")

# Nomes de coluna aceitos (comparados sem acento, sem maiúscula, "_" vira espaço).
COLUNAS = {
    "telefone": ("telefone", "celular", "whatsapp", "fone", "telefone celular",
                 "telefone 1", "phone", "tel"),
    "nome": ("nome", "cliente", "nome do cliente", "nome completo", "name"),
    "carro": ("carro", "veiculo", "veiculo comprado", "carro comprado", "modelo",
              "produto", "item"),
    "data_compra": ("data da compra", "data compra", "data da venda", "data venda", "data"),
    "pagamento": ("pagamento", "forma de pagamento", "forma pagamento"),
    "meses": ("meses", "parcelas", "prazo", "meses financiamento", "meses de financiamento"),
}

MODELO_CSV = (
    "nome;telefone;carro;data_compra;pagamento;meses\n"
    "Ana Souza;(81) 99999-8888;Honda Civic 2019;15/03/2025;financiado;48\n"
    "Carlos Lima;(81) 98888-7777;;;;\n"
)


class PlanilhaInvalida(ValueError):
    """O arquivo não dá para ler (vazio, grande demais, sem coluna de telefone)."""


class ImportacaoInvalida(ValueError):
    """A gravação foi recusada (sem linhas, sem usuário, loja inexistente...)."""


@dataclass
class LinhaImportada:
    linha: int
    telefone: str
    nome: str = ""
    carro: str = ""
    data_compra: date | None = None
    pagamento: str | None = None
    meses: int | None = None


@dataclass
class Previa:
    colunas: dict
    total_linhas: int = 0
    linhas: list = field(default_factory=list)
    recusadas: list = field(default_factory=list)   # [(linha, motivo)]
    avisos: list = field(default_factory=list)      # [(linha, aviso)]

    def contatos(self) -> dict[str, str]:
        """telefone -> nome. Telefone repetido vira um contato (último nome não vazio)."""
        saida: dict[str, str] = {}
        for l in self.linhas:
            saida[l.telefone] = l.nome or saida.get(l.telefone, "")
        return saida

    @property
    def compras(self) -> list:
        return [l for l in self.linhas if l.carro and l.data_compra]


# ------------------------------------------------------------ leitura

def _norm(texto) -> str:
    t = unicodedata.normalize("NFD", str(texto or ""))
    t = "".join(c for c in t if unicodedata.category(c) != "Mn").lower()
    return " ".join(re.sub(r"[_\-./]+", " ", t).split())


def _limpar(texto) -> str:
    return " ".join(str(texto or "").split())[:MAX_TEXTO]


def _decodificar(conteudo: bytes) -> str:
    for codificacao in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return conteudo.decode(codificacao)
        except UnicodeDecodeError:
            continue
    raise PlanilhaInvalida("Não consegui ler o arquivo. Salve como CSV UTF-8.")


def _separador(texto: str) -> str:
    primeira = next((l for l in texto.splitlines() if l.strip()), "")
    return max((";", ",", "\t"), key=primeira.count)


def _achar_colunas(cabecalho: list[str]) -> dict[str, int]:
    normalizados = [_norm(c) for c in cabecalho]
    achadas, usados = {}, set()
    for campo, apelidos in COLUNAS.items():
        for apelido in apelidos:
            alvo = _norm(apelido)
            if alvo in normalizados:
                i = normalizados.index(alvo)
                if i not in usados:
                    achadas[campo] = i
                    usados.add(i)
                    break
    return achadas


def _data(texto) -> date | None:
    t = str(texto or "").strip()
    if not t:
        return None
    if t.isdigit() and 20000 <= int(t) <= 80000:      # data guardada como número no Excel
        return _EXCEL_ZERO + timedelta(days=int(t))
    t = re.split(r"[ T]", t)[0]
    for formato in _FORMATOS_DATA:
        try:
            return datetime.strptime(t, formato).date()
        except ValueError:
            continue
    raise ValueError(texto)


def _pagamento(texto) -> str | None:
    t = _norm(texto)
    if not t:
        return None
    if any(p in t for p in ("financ", "parcel", "cdc")):
        return "financiado"
    if "vista" in t or t in ("pix", "dinheiro", "avista"):
        return "avista"
    raise ValueError(texto)


def _meses(texto) -> int | None:
    t = str(texto or "").strip()
    if not t:
        return None
    achados = re.findall(r"\d+", t)
    if not achados:
        raise ValueError(texto)
    meses = int(achados[0])
    if not 1 <= meses <= MAX_MESES:
        raise ValueError(texto)
    return meses


def _motivo_telefone(bruto: str) -> str:
    if not bruto:
        return "Sem telefone"
    if "e+" in bruto.lower():
        return (f"Telefone em notação científica ('{bruto}'): no Excel, formate a "
                "coluna como Texto antes de salvar")
    return f"Telefone inválido ou fixo: '{bruto}'"


def ler_planilha(conteudo: bytes, *, hoje: date | None = None) -> Previa:
    """Lê e confere o CSV. Não grava nada."""
    if not conteudo:
        raise PlanilhaInvalida("O arquivo está vazio.")
    if len(conteudo) > MAX_BYTES:
        raise PlanilhaInvalida("Arquivo grande demais (máximo 5 MB). Divida em partes.")
    texto = _decodificar(conteudo)
    leitor = csv.reader(io.StringIO(texto), delimiter=_separador(texto))
    cheias = [(n, l) for n, l in enumerate(leitor, start=1) if any(c.strip() for c in l)]
    if not cheias:
        raise PlanilhaInvalida("O arquivo está vazio.")
    (_, cabecalho), dados = cheias[0], cheias[1:]
    if len(dados) > MAX_LINHAS:
        raise PlanilhaInvalida(f"Mais de {MAX_LINHAS} linhas. Divida em partes.")
    colunas = _achar_colunas(cabecalho)
    if "telefone" not in colunas:
        nomes = ", ".join(c.strip() for c in cabecalho if c.strip())
        raise PlanilhaInvalida(f"Não achei a coluna de telefone. Colunas da planilha: {nomes}.")

    hoje = hoje or date.today()
    previa = Previa(colunas={campo: cabecalho[i].strip() for campo, i in colunas.items()},
                    total_linhas=len(dados))
    for n, celulas in dados:
        def valor(campo):
            i = colunas.get(campo)
            return celulas[i].strip() if i is not None and i < len(celulas) else ""

        bruto = valor("telefone")
        if re.fullmatch(r"\d+\.0", bruto):          # número que o Excel virou "819...0.0"
            bruto = bruto[:-2]
        telefone = normalizar_telefone_br(bruto)
        if not telefone:
            previa.recusadas.append((n, _motivo_telefone(bruto)))
            continue
        item = LinhaImportada(linha=n, telefone=telefone, nome=_limpar(valor("nome")))
        carro, data_txt = _limpar(valor("carro")), valor("data_compra")

        if carro and data_txt:
            try:
                dia = _data(data_txt)
            except ValueError:
                previa.avisos.append((n, f"Data inválida ('{data_txt}'): entra só o contato"))
                dia = None
            if dia and dia > hoje:
                previa.avisos.append((n, f"Data no futuro ('{data_txt}'): entra só o contato"))
                dia = None
            if dia:
                item.carro, item.data_compra = carro, dia
                try:
                    item.pagamento = _pagamento(valor("pagamento"))
                except ValueError:
                    previa.avisos.append((n, f"Pagamento não reconhecido ('{valor('pagamento')}'): "
                                             "a compra entra sem a forma de pagamento"))
                if item.pagamento == "financiado":
                    try:
                        item.meses = _meses(valor("meses"))
                    except ValueError:
                        previa.avisos.append((n, f"Meses inválidos ('{valor('meses')}'): "
                                                 "a compra entra sem o prazo"))
        elif carro:
            previa.avisos.append((n, "Compra sem data: entra só o contato"))
        elif data_txt:
            previa.avisos.append((n, "Data sem o que foi comprado: entra só o contato"))
        previa.linhas.append(item)
    return previa


# ------------------------------------------------------------ gravação

def importar(loja_id, previa: Previa, *, usuario: str, consentimento: bool,
             arquivo: str = "", agora: datetime | None = None) -> dict:
    """Grava a prévia numa transação só. Reimportar não duplica nada."""
    loja_id = exigir_loja(loja_id)
    usuario = " ".join(str(usuario or "").split())
    if not usuario:
        raise ImportacaoInvalida("Informe quem está importando.")
    if not previa.linhas:
        raise ImportacaoInvalida("Nenhuma linha válida para importar.")
    quando = para_banco(agora or agora_utc())
    marca = 1 if consentimento else 0
    novos = atualizados = compras_novas = compras_repetidas = 0

    conexao = conectar()
    try:
        if conexao.execute("SELECT 1 FROM lojas WHERE id = ?", (loja_id,)).fetchone() is None:
            raise ImportacaoInvalida(f"A loja {loja_id} não existe.")
        imp = conexao.execute(
            "INSERT INTO importacoes (loja_id, arquivo, usuario, consentimento, linhas, recusadas, "
            "criado_em) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (loja_id, str(arquivo or "")[:200], usuario, marca, previa.total_linhas,
             len(previa.recusadas), quando)).lastrowid

        for telefone, nome in previa.contatos().items():
            existe = conexao.execute("SELECT id FROM contatos WHERE loja_id = ? AND telefone = ?",
                                     (loja_id, telefone)).fetchone()
            if existe is None:
                conexao.execute(
                    "INSERT INTO contatos (loja_id, telefone, nome, origem, consentimento, "
                    "consentimento_em, consentimento_por, importacao_id, criado_em, atualizado_em) "
                    "VALUES (?, ?, ?, 'planilha', ?, ?, ?, ?, ?, ?)",
                    (loja_id, telefone, nome or None, marca, quando if marca else None,
                     usuario if marca else None, imp, quando, quando))
                novos += 1
            else:
                # Nome vazio não apaga o que já existe. Consentimento só sobe, nunca desce.
                conexao.execute(
                    """UPDATE contatos SET
                           nome = COALESCE(NULLIF(?, ''), nome),
                           consentimento_em = CASE WHEN ? = 1 AND consentimento = 0
                                                   THEN ? ELSE consentimento_em END,
                           consentimento_por = CASE WHEN ? = 1 AND consentimento = 0
                                                    THEN ? ELSE consentimento_por END,
                           consentimento = MAX(consentimento, ?),
                           atualizado_em = ?
                       WHERE id = ?""",
                    (nome, marca, quando, marca, usuario, marca, quando, existe["id"]))
                atualizados += 1

        for l in previa.compras:
            n = conexao.execute(
                "INSERT OR IGNORE INTO compras_anteriores (loja_id, telefone, descricao, data_compra, "
                "forma_pagamento, meses_financiamento, importacao_id, criado_em) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (loja_id, l.telefone, l.carro, l.data_compra.isoformat(), l.pagamento, l.meses,
                 imp, quando)).rowcount
            compras_novas += n
            compras_repetidas += 1 - n

        conexao.execute(
            "UPDATE importacoes SET contatos_novos = ?, contatos_atualizados = ?, compras = ? "
            "WHERE id = ?", (novos, atualizados, compras_novas, imp))
        conexao.commit()
    except Exception:
        conexao.rollback()
        raise
    finally:
        conexao.close()
    return {"importacao_id": imp, "contatos_novos": novos, "contatos_atualizados": atualizados,
            "compras_novas": compras_novas, "compras_repetidas": compras_repetidas,
            "recusadas": len(previa.recusadas)}


def desfazer_importacao(loja_id, importacao_id: int, *, agora: datetime | None = None) -> dict:
    loja_id = exigir_loja(loja_id)
    conexao = conectar()
    try:
        imp = conexao.execute("SELECT desfeita_em FROM importacoes WHERE id = ? AND loja_id = ?",
                              (importacao_id, loja_id)).fetchone()
        if imp is None:
            raise ImportacaoInvalida("Importação não encontrada nesta loja.")
        if imp["desfeita_em"]:
            raise ImportacaoInvalida("Esta importação já foi desfeita.")
        compras = conexao.execute(
            "DELETE FROM compras_anteriores WHERE loja_id = ? AND importacao_id = ?",
            (loja_id, importacao_id)).rowcount
        contatos = conexao.execute(
            "DELETE FROM contatos WHERE loja_id = ? AND importacao_id = ?",
            (loja_id, importacao_id)).rowcount
        conexao.execute("UPDATE importacoes SET desfeita_em = ? WHERE id = ?",
                        (para_banco(agora or agora_utc()), importacao_id))
        conexao.commit()
    finally:
        conexao.close()
    return {"contatos": contatos, "compras": compras}


def listar_importacoes(loja_id, limite: int = 20) -> list[dict]:
    loja_id = exigir_loja(loja_id)
    conexao = conectar()
    try:
        linhas = conexao.execute("SELECT * FROM importacoes WHERE loja_id = ? ORDER BY id DESC LIMIT ?",
                                 (loja_id, limite)).fetchall()
    finally:
        conexao.close()
    return [dict(l) for l in linhas]


def resumo_da_base(loja_id) -> dict:
    loja_id = exigir_loja(loja_id)
    conexao = conectar()
    try:
        c = conexao.execute("SELECT COUNT(*) AS n, COALESCE(SUM(consentimento), 0) AS ok "
                            "FROM contatos WHERE loja_id = ?", (loja_id,)).fetchone()
        compras = conexao.execute("SELECT COUNT(*) FROM compras_anteriores WHERE loja_id = ?",
                                  (loja_id,)).fetchone()[0]
    finally:
        conexao.close()
    return {"contatos": c["n"], "com_consentimento": c["ok"], "compras": compras}
