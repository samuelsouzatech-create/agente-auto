"""
Equipe e Canais da Configuração do operador (S4b da Fase 3). Só LÊ e monta
texto pronto; sem Streamlit. As escritas ficam em app/usuarios.py,
app/canais.py e app/estado_loja.py (com Registro na mesma transação).

- "Recebe avisos" é calculado (ativo e com Telegram), sem coluna nova.
- A chave do canal nunca sai daqui: só se foi encontrada ou não.
- "Última alteração por quem e quando" vem do registro_acoes, no fuso da loja.
"""
from __future__ import annotations

from banco import conectar
from app.apresentacao import horario_para_tela, nome_do_canal
from app.canais import TIPOS_DE_CANAL, listar_canais, nome_de_chave_valido
from app.chaves import exigir_loja
from app.credenciais import (
    ENCONTRADA, NAO_ENCONTRADA, OUTRO_ROBO, SEM_CONFERENCIA, situacao_da_chave,
)
from app.estado_loja import listar_numeros_de_teste
from app.lojas import carregar_loja
from app.telefone import formatar_telefone_br
from app.usuarios import CAMPOS_DO_CADASTRO, listar_usuarios, rotulo_papel

ACOES_EQUIPE = ("criar_pessoa_equipe", "alterar_pessoa_equipe", "desativar_pessoa_equipe",
                "reativar_pessoa_equipe", "criar_acesso", "definir_email_acesso",
                "redefinir_senha")
ACOES_CANAIS = ("cadastrar_canal", "desativar_canal", "cadastrar_numero_teste",
                "desativar_numero_teste")
ACOES_DO_ASSUNTO = {"Equipe": ACOES_EQUIPE, "Canais": ACOES_CANAIS}
# Ações criadas no S4b (o detalhe delas no Registro é montado aqui).
ACOES_S4B = ("criar_pessoa_equipe", "alterar_pessoa_equipe", "desativar_pessoa_equipe",
             "reativar_pessoa_equipe", "cadastrar_canal", "desativar_canal",
             "cadastrar_numero_teste", "desativar_numero_teste")
SEM_MENSAGEM = "nenhuma ainda"
VAZIO = "vazio"

NOTA_EQUIPE = ("Quem trabalha na loja. Quem está ativo e tem Telegram recebe os avisos do "
               "assistente. Ninguém é apagado: quem sai da loja é desativado.")
AJUDA_TELEGRAM = ("Número do chat da pessoa no Telegram (só dígitos). Antes, a pessoa precisa "
                  "abrir o robô de avisos e tocar em Iniciar.")
NOTA_CANAIS = ("Por onde os clientes falam com o assistente. A chave de cada canal fica "
               "guardada só no servidor: aqui aparece apenas se ela foi encontrada.")
AJUDA_ID_CANAL = ("WhatsApp: a identificação do número na Meta. Telegram: o número do robô "
                  "(a parte antes dos dois-pontos da chave).")
AJUDA_NOME_CHAVE = ("O nome com que a chave foi guardada no servidor, por exemplo "
                    "WHATSAPP_TOKEN_LOJA2. Nunca cole a chave aqui. Pode ficar vazio quando o "
                    "canal usa a chave principal do servidor.")
NOTA_NUMEROS = ("Enquanto a loja está em teste, só estes números conversam com o assistente. "
                "No Telegram, use o número do chat da pessoa.")

TEXTO_CHAVE = {
    ENCONTRADA: "encontrada no servidor",
    NAO_ENCONTRADA: "não encontrada no servidor",
    OUTRO_ROBO: "a chave encontrada é de outro robô",
    SEM_CONFERENCIA: "conferência ainda não disponível para este canal",
}
TEXTO_TESTE = {
    ENCONTRADA: ("Chave encontrada no servidor. Por enquanto o teste confere só a chave; "
                 "a conversa de verdade se confere com um número de teste."),
    NAO_ENCONTRADA: ("A chave deste canal não foi encontrada no servidor. Confira o nome da "
                     "chave cadastrado e o servidor."),
    OUTRO_ROBO: "A chave encontrada no servidor é de outro robô do Telegram, não deste canal.",
    SEM_CONFERENCIA: "Ainda não dá para conferir a chave deste tipo de canal.",
}
ROTULOS_CAMPO_EQUIPE = {"nome": "Nome", "papel": "Papel",
                        "telegram": "Telegram", "whatsapp": "WhatsApp"}


# ------------------------------------------------------------ última alteração

def ultima_alteracao(loja_id, assunto: str, agora=None) -> dict | None:
    """{"quem", "quando"} da última ação do assunto nesta loja, ou None."""
    loja_id = exigir_loja(loja_id)
    acoes = ACOES_DO_ASSUNTO.get(assunto)
    if acoes is None:
        raise ValueError(f"Assunto sem registro próprio: {assunto}")
    marcas = ", ".join("?" for _ in acoes)
    conexao = conectar()
    try:
        linha = conexao.execute(
            f"SELECT quando, pessoa FROM registro_acoes WHERE loja_id = ? AND acao IN ({marcas}) "
            "ORDER BY quando DESC, id DESC LIMIT 1", (loja_id, *acoes)).fetchone()
    finally:
        conexao.close()
    if linha is None:
        return None
    return {"quem": linha["pessoa"],
            "quando": horario_para_tela(carregar_loja(loja_id), linha["quando"], agora=agora)}


# ------------------------------------------------------------ equipe

def _whatsapp_na_tela(valor) -> str:
    if not valor:
        return ""
    return formatar_telefone_br(valor) or str(valor)


def equipe_da_loja(loja_id) -> list[dict]:
    """Todas as pessoas da loja (ativas primeiro), prontas para a tela.
    'versao' = os valores do cadastro, para a proteção de conflito."""
    loja_id = exigir_loja(loja_id)
    saida = []
    for u in listar_usuarios(loja_id, incluir_inativos=True):
        ativo = bool(u["ativo"])
        saida.append({
            "id": u["id"], "nome": u["nome"], "papel": u["papel"],
            "rotulo_papel": rotulo_papel(u["papel"]),
            "telegram": u["contato_telegram"] or "",
            "whatsapp": u["contato_whatsapp"] or "",
            "whatsapp_tela": _whatsapp_na_tela(u["contato_whatsapp"]),
            "ativo": ativo,
            "recebe_avisos": ativo and bool(u["contato_telegram"]),
            "versao": {c: u[c] for c in CAMPOS_DO_CADASTRO},
        })
    return saida


def resumo_da_equipe(loja_id) -> dict:
    pessoas = equipe_da_loja(loja_id)
    return {"ativos": sum(1 for p in pessoas if p["ativo"]),
            "recebem_avisos": sum(1 for p in pessoas if p["recebe_avisos"])}


# ------------------------------------------------------------ canais

def _ultimas_mensagens(loja_id: int) -> dict:
    conexao = conectar()
    try:
        linhas = conexao.execute(
            "SELECT canal, MAX(criado_em) AS quando FROM mensagens "
            "WHERE loja_id = ? AND direcao = 'cliente' GROUP BY canal", (loja_id,)).fetchall()
    finally:
        conexao.close()
    return {l["canal"]: l["quando"] for l in linhas}


def _nome_do_canal_na_tela(canal: dict) -> str:
    final = str(canal.get("id_externo") or "")[-4:]
    nome = nome_do_canal(canal.get("tipo"))
    return f"{nome} · final {final}" if final else nome


def canais_da_loja(loja_id) -> list[dict]:
    """Canais da loja, sem a chave e sem o nome da chave."""
    loja_id = exigir_loja(loja_id)
    loja = carregar_loja(loja_id)
    ultimas = _ultimas_mensagens(loja_id)
    saida = []
    for c in listar_canais(loja_id):
        situacao = situacao_da_chave(c)
        quando = ultimas.get(c["tipo"])
        saida.append({
            "id": c["id"], "tipo": c["tipo"], "nome": _nome_do_canal_na_tela(c),
            "ativo": bool(c["ativo"]),
            "situacao": "Ativo" if c["ativo"] else "Desativado",
            "chave": situacao, "chave_texto": TEXTO_CHAVE[situacao],
            "ultima_mensagem": horario_para_tela(loja, quando) if quando else SEM_MENSAGEM,
        })
    return saida


def testar_conexao(loja_id, canal_id) -> tuple[bool, str]:
    """Por enquanto só confere se a chave existe (até haver conta da Meta)."""
    loja_id = exigir_loja(loja_id)
    canal = next((c for c in listar_canais(loja_id) if c["id"] == canal_id), None)
    if canal is None:
        return False, "Este canal não é desta loja."
    situacao = situacao_da_chave(canal)
    texto = TEXTO_TESTE[situacao]
    if not canal["ativo"]:
        texto += " Atenção: o canal está desativado."
    return situacao == ENCONTRADA, texto


def validar_canal_novo(tipo, id_externo, nome_chave) -> list[str]:
    """Erros em palavras simples, antes de chamar cadastrar_canal."""
    erros = []
    if tipo not in TIPOS_DE_CANAL:
        erros.append("Escolha o tipo de canal.")
    if not str(id_externo or "").strip():
        erros.append("Informe o identificador do canal.")
    nome = str(nome_chave or "").strip()
    if nome and (":" in nome or len(nome) > 60):
        erros.append("Isso parece a própria chave. Coloque só o nome com que ela foi guardada "
                     "no servidor.")
    elif nome and not nome_de_chave_valido(nome):
        erros.append("O nome da chave usa só letras sem acento, números e _ "
                     "(exemplo: WHATSAPP_TOKEN_LOJA2).")
    return erros


# ------------------------------------------------------------ números de teste

def numeros_de_teste_da_loja(loja_id) -> list[dict]:
    saida = []
    for n in listar_numeros_de_teste(exigir_loja(loja_id)):
        numero = n["id_externo"]
        if n["tipo_de_canal"] == "whatsapp":
            numero = formatar_telefone_br(numero) or numero
        partes = [nome_do_canal(n["tipo_de_canal"]), numero] + ([n["nome"]] if n["nome"] else [])
        saida.append({"id": n["id"], "texto": " · ".join(partes)})
    return saida


# ------------------------------------------------------------ Registro

def _valor_equipe(chave, valor) -> str:
    if valor in (None, ""):
        return VAZIO
    if chave == "papel":
        return rotulo_papel(valor)
    if chave == "whatsapp":
        return _whatsapp_na_tela(valor)
    return str(valor)


def _canal(tipo) -> str:
    return nome_do_canal(tipo) if tipo else "Canal"


def detalhe_do_registro(acao: str, antes, depois) -> str:
    """Texto da coluna Detalhe do Registro para as ações do S4b. Sem ids."""
    a = antes if isinstance(antes, dict) else {}
    d = depois if isinstance(depois, dict) else {}
    if acao in ("criar_pessoa_equipe", "desativar_pessoa_equipe", "reativar_pessoa_equipe"):
        nome = d.get("nome") or a.get("nome") or ""
        papel = d.get("papel") or a.get("papel")
        return " · ".join(p for p in (str(nome), rotulo_papel(papel) if papel else "") if p)
    if acao == "alterar_pessoa_equipe":
        mudou = [f"{rotulo}: {_valor_equipe(k, a.get(k))} → {_valor_equipe(k, d.get(k))}"
                 for k, rotulo in ROTULOS_CAMPO_EQUIPE.items() if k in d and a.get(k) != d.get(k)]
        partes = [str(d.get("pessoa") or "")] + ([", ".join(mudou)] if mudou else [])
        return " · ".join(p for p in partes if p)
    if acao == "cadastrar_canal":
        if a.get("veio_de_outra_loja"):
            como = "trazido de outra loja"
        elif not a:
            como = "ligado a esta loja"
        elif not a.get("ativo"):
            como = "reativado"
        else:
            como = "chave atualizada"
        return f"{_canal(d.get('tipo') or a.get('tipo'))} · {como}"
    if acao == "desativar_canal":
        return f"{_canal(a.get('tipo') or d.get('tipo'))} · desativado"
    if acao in ("cadastrar_numero_teste", "desativar_numero_teste"):
        nome = d.get("nome") or a.get("nome")
        return " · ".join(p for p in (_canal(d.get("canal") or a.get("canal")), nome) if p)
    return ""

# O pytest acha que toda função que começa com "test" é teste.
# Esta não é: é o botão "Testar conexão" da tela de Canais.
testar_conexao.__test__ = False
