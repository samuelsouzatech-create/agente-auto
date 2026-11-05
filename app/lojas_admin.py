"""Operações do operador sobre as lojas (Etapa 1, Bloco 5; S2 da Fase 3).

S2: criar_loja cria a loja de verdade (nome, cidade, fuso e segmento).
- A loja nasce Em teste: não ganha linha em estado_lojas (migração 11), e
  loja sem linha lá conta como em teste.
- Cidade e fuso já entram confirmados (saem da marca "a confirmar").
- Loja e Registro na mesma transação: erro no meio = nada fica.
- Só o operador cria.
A tela antiga "Lojas e canais" continua usando app/lojas.criar_loja até o S4b.
"""
import json

from banco import conectar
from app.ator import exigir_ator
from app.estado_loja import EM_TESTE, SoOperador
from app.lojas import EDITAVEIS, PADROES
from app.segmentos import segmento_existe

MAX_NOME = 80
FUSO_PADRAO = PADROES["fuso"]

# Fusos do Brasil, como aparecem na tela (sem nome técnico).
FUSOS_DO_BRASIL = {
    "America/Noronha": "Fernando de Noronha",
    "America/Recife": "Recife (PE)",
    "America/Fortaleza": "Fortaleza (CE, MA, PI, RN, PB)",
    "America/Maceio": "Maceió (AL, SE)",
    "America/Bahia": "Salvador (BA)",
    "America/Belem": "Belém (PA, AP)",
    "America/Araguaina": "Palmas (TO)",
    "America/Sao_Paulo": "Brasília e São Paulo (DF, SP, RJ, MG, ES, GO e Sul)",
    "America/Campo_Grande": "Campo Grande (MS)",
    "America/Cuiaba": "Cuiabá (MT)",
    "America/Porto_Velho": "Porto Velho (RO)",
    "America/Boa_Vista": "Boa Vista (RR)",
    "America/Manaus": "Manaus (AM)",
    "America/Rio_Branco": "Rio Branco (AC)",
}
ROTULOS_SEGMENTO = {"veiculos": "Veículos"}


class LojaInvalida(ValueError):
    def __init__(self, erros: list[str]):
        self.erros = erros
        super().__init__("; ".join(erros))


def rotulo_segmento(segmento: str) -> str:
    return ROTULOS_SEGMENTO.get(segmento, segmento)


def listar_lojas() -> list[dict]:
    conexao = conectar()
    try:
        linhas = conexao.execute(
            "SELECT id, nome, segmento, ativo, criado_em FROM lojas ORDER BY id"
        ).fetchall()
    finally:
        conexao.close()
    return [dict(l) for l in linhas]


def renomear_loja(loja_id: int, nome: str) -> bool:
    """Troca o nome da loja. Sobe a versão da configuração para o agente
    usar o nome novo já na próxima mensagem."""
    nome = (nome or "").strip()
    if not 1 <= len(nome) <= 80:
        raise ValueError("o nome precisa ter entre 1 e 80 caracteres")
    conexao = conectar()
    try:
        cursor = conexao.execute(
            "UPDATE lojas SET nome = ?, versao_config = versao_config + 1 WHERE id = ?",
            (nome, loja_id),
        )
        conexao.commit()
        return cursor.rowcount > 0
    finally:
        conexao.close()


def criar_loja(nome, cidade, fuso, segmento, agora=None) -> int:
    """S2: cria a loja Em teste e grava no Registro. Devolve o número da loja."""
    ator = exigir_ator()                         # sem ator: SemAtor, nada criado
    if ator.papel != "operador" or ator.loja_id is not None:
        raise SoOperador("Só o operador cria lojas.")

    erros = []
    nome_limpo = " ".join(str(nome or "").split())
    if not 1 <= len(nome_limpo) <= MAX_NOME:
        erros.append(f"Nome da loja: precisa ter entre 1 e {MAX_NOME} caracteres")
    cidade_limpa = " ".join(str(cidade or "").split())
    if not cidade_limpa:
        erros.append("Cidade: não pode ficar vazia")
    else:
        try:
            cidade_limpa = EDITAVEIS["cidade"](cidade_limpa)
        except ValueError as erro:
            erros.append(f"Cidade: {erro}")
    try:
        EDITAVEIS["fuso"](fuso)
    except ValueError:
        erros.append("Fuso horário: escolha um da lista")
    if not segmento_existe(segmento):
        erros.append("Segmento: escolha um da lista")
    if erros:
        raise LojaInvalida(erros)

    from app.registro import registrar           # aqui dentro: evita import circular
    config = {"cidade": cidade_limpa, "fuso": fuso, "_confirmados": ["cidade", "fuso"]}
    conexao = conectar()
    try:
        novo_id = conexao.execute(
            "INSERT INTO lojas (nome, segmento, config) VALUES (?, ?, ?)",
            (nome_limpo, segmento, json.dumps(config, ensure_ascii=False)),
        ).lastrowid
        registrar("criar_loja", novo_id, None,
                  {"nome": nome_limpo, "cidade": cidade_limpa, "fuso": fuso,
                   "segmento": segmento, "estado": EM_TESTE},
                  conexao=conexao, alvo="loja", agora=agora)
        conexao.commit()
    finally:
        conexao.close()
    return novo_id
