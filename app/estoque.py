"""
CRUD de estoque (Fase 3 - Bloco 5; caminho único de venda no P2; Registro no S4c).

Regra do P2: nenhuma função deste arquivo coloca um carro como 'vendido'.
A venda só acontece por app/vendas.py:registrar_venda. Um carro já vendido
também não volta para a oferta por aqui.

S4c: adicionar_carro e atualizar_carro exigem ator e vão para o Registro na
MESMA transação (cadastrar_carro e alterar_carro; alvo "carro:{id}").
atualizar_carro aceita 'esperado' (os valores que a tela mostrou): se o carro
mudou desde então, CarroMudou e nada é gravado. Salvar sem mudar nada não grava.
marcar_status não mudou (fora do S4c).
"""
from banco import conectar

OPCOES_CAMBIO = ["Automático", "Manual"]
# 'vendido' não entra aqui de propósito: só registrar_venda grava 'vendido'.
OPCOES_STATUS = ["disponivel", "reservado", "indisponivel"]
VENDIDO = "vendido"
CAMPOS_DO_CARRO = ("marca", "modelo", "ano", "km", "cor", "cambio", "preco", "status", "fotos")

MENSAGEM_USE_VENDA = ("Para vender um carro, use \"Registrar venda\" na conversa do cliente. "
                      "Assim a venda, o resultado e o pós-venda ficam registrados juntos.")
MENSAGEM_JA_VENDIDO = "Este carro já foi vendido. A situação dele não muda por aqui."
MENSAGEM_STATUS_INVALIDO = "Situação inválida. Escolha Disponível, Reservado ou Indisponível."


class StatusInvalido(ValueError):
    """Situação que o estoque não aceita (ex.: 'vendido' fora do Registrar venda)."""


class CarroMudou(ValueError):
    """Outra pessoa mudou este carro enquanto a tela estava aberta (S4c)."""


class FotosInvalidas(ValueError):
    """Maratona Fotos: alguma foto não passou no preparo (o texto vem pronto para a loja)."""


def _preparar_fotos(loja_id, fotos) -> tuple[str, list]:
    """Maratona Fotos: TODA entrada de foto do estoque passa aqui (API, telas, importação).
    Endereço de foto desta loja vira a referência do depósito; link https é baixado e preparado.
    Devolve (texto para o banco, referências novas guardadas agora)."""
    from app import fotos as _fotos
    try:
        refs, novas = _fotos.normalizar(loja_id, _fotos.separar(fotos))
    except _fotos.FotoRecusada as erro:
        raise FotosInvalidas(str(erro)) from None
    return _fotos.juntar(refs), novas


def _apagar_fotos(loja_id, refs) -> None:
    from app import fotos as _fotos
    for ref in refs:
        try:
            _fotos.apagar(loja_id, ref)
        except Exception:                  # depósito fora do ar: a foto fica, nada mais quebra
            pass


def _validar_status(status):
    if status == VENDIDO:
        raise StatusInvalido(MENSAGEM_USE_VENDA)
    if status not in OPCOES_STATUS:
        raise StatusInvalido(MENSAGEM_STATUS_INVALIDO)


def _status_atual(cursor, carro_id, loja_id):
    cursor.execute("SELECT status FROM estoque WHERE id = ? AND loja_id = ?", (carro_id, loja_id))
    linha = cursor.fetchone()
    return linha["status"] if linha else None


def valores_do_carro(carro) -> dict:
    """Os campos editáveis do carro (fotos vazias viram "")."""
    return {c: ((carro[c] or "") if c == "fotos" else carro[c]) for c in CAMPOS_DO_CARRO}


def listar_estoque(loja_id, incluir_vendidos=True):
    """Lista os carros do estoque. Por padrão traz todos; se
    incluir_vendidos=False, traz só os que não estão vendidos."""
    conexao = conectar()
    cursor = conexao.cursor()
    if incluir_vendidos:
        cursor.execute("SELECT * FROM estoque WHERE loja_id = ? ORDER BY id ASC", (loja_id,))
    else:
        cursor.execute(
            "SELECT * FROM estoque WHERE loja_id = ? AND status != 'vendido' ORDER BY id ASC",
            (loja_id,))
    linhas = cursor.fetchall()
    conexao.close()
    return [dict(linha) for linha in linhas]


def buscar_carro(carro_id, loja_id):
    """Retorna um carro pelo id, ou None se não existir."""
    conexao = conectar()
    cursor = conexao.cursor()
    cursor.execute("SELECT * FROM estoque WHERE id = ? AND loja_id = ?", (carro_id, loja_id))
    linha = cursor.fetchone()
    conexao.close()
    return dict(linha) if linha else None


def adicionar_carro(marca, modelo, ano, km, cor, cambio, preco,
                    status="disponivel", fotos="", *, loja_id):
    """Cadastra um carro novo. Retorna o id gerado.
    Carro novo nunca nasce 'vendido' (regra do P2)."""
    _validar_status(status)
    from app.registro import conferir_ator, registrar   # aqui dentro: evita import circular
    conferir_ator(loja_id)
    texto_fotos, novas = _preparar_fotos(loja_id, fotos)
    valores = dict(zip(CAMPOS_DO_CARRO,
                       (marca, modelo, ano, km, cor, cambio, preco, status, texto_fotos)))
    conexao = conectar()
    try:
        novo_id = conexao.execute(
            "INSERT INTO estoque (loja_id, marca, modelo, ano, km, cor, cambio, preco, status, fotos) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (loja_id, *valores.values())).lastrowid
        registrar("cadastrar_carro", loja_id, None, valores, conexao=conexao,
                  alvo=f"carro:{novo_id}")
        conexao.commit()
    except BaseException:
        _apagar_fotos(loja_id, novas)
        raise
    finally:
        conexao.close()
    return novo_id


def atualizar_carro(carro_id, marca, modelo, ano, km, cor, cambio, preco,
                    status, fotos="", *, loja_id, esperado=None):
    """Atualiza os campos editáveis de um carro existente.
    Carro já vendido: os dados (preço, fotos...) podem ser corrigidos, mas a
    situação continua 'vendido'. Nenhum carro vira 'vendido' por aqui."""
    from app.registro import conferir_ator, registrar   # aqui dentro: evita import circular
    conferir_ator(loja_id)
    texto_fotos, novas = _preparar_fotos(loja_id, fotos)
    saiu = []
    conexao = conectar()
    try:
        linha = conexao.execute(
            f"SELECT {', '.join(CAMPOS_DO_CARRO)} FROM estoque WHERE id = ? AND loja_id = ?",
            (carro_id, loja_id)).fetchone()
        if linha is None:
            _apagar_fotos(loja_id, novas)
            return "Carro não encontrado nesta loja."
        atual = valores_do_carro(linha)
        if atual["status"] == VENDIDO:
            if status != VENDIDO:
                raise StatusInvalido(MENSAGEM_JA_VENDIDO)
        else:
            _validar_status(status)
        if esperado is not None and any(atual[c] != esperado.get(c) for c in CAMPOS_DO_CARRO):
            raise CarroMudou("Outra pessoa mudou este carro enquanto você editava. "
                             "Nada foi gravado.")
        novos = dict(zip(CAMPOS_DO_CARRO,
                         (marca, modelo, ano, km, cor, cambio, preco, status, texto_fotos)))
        mudou = [c for c in CAMPOS_DO_CARRO if atual[c] != novos[c]]
        if not mudou:
            return "Carro atualizado."
        from app import fotos as _fotos
        ficam = set(_fotos.separar(texto_fotos))
        saiu = [r for r in _fotos.separar(atual["fotos"]) if r not in ficam]
        conexao.execute(
            "UPDATE estoque SET marca = ?, modelo = ?, ano = ?, km = ?, cor = ?, cambio = ?, "
            "preco = ?, status = ?, fotos = ? WHERE id = ? AND loja_id = ?",
            (*novos.values(), carro_id, loja_id))
        registrar("alterar_carro", loja_id, {c: atual[c] for c in mudou},
                  {**{c: novos[c] for c in mudou}, "carro": f"{marca} {modelo} {ano}"},
                  conexao=conexao, alvo=f"carro:{carro_id}")
        conexao.commit()
    except BaseException:
        _apagar_fotos(loja_id, novas)
        raise
    finally:
        conexao.close()
    _apagar_fotos(loja_id, saiu)          # fotos que saíram do carro saem do depósito
    return "Carro atualizado."


def marcar_status(carro_id, status, loja_id):
    """Muda só a situação: disponivel, reservado ou indisponivel.
    'vendido' é recusado: use registrar_venda (app/vendas.py)."""
    _validar_status(status)
    conexao = conectar()
    try:
        cursor = conexao.cursor()
        atual = _status_atual(cursor, carro_id, loja_id)
        if atual is None:
            return "Carro não encontrado nesta loja."
        if atual == VENDIDO:
            raise StatusInvalido(MENSAGEM_JA_VENDIDO)
        cursor.execute("UPDATE estoque SET status = ? WHERE id = ? AND loja_id = ?",
                       (status, carro_id, loja_id))
        conexao.commit()
    finally:
        conexao.close()
    return f"Status alterado para '{status}'."


# ------------------------------------------------------------ fotos do carro (Maratona Fotos, F2)
# Enviar (arquivo), adicionar por link, apagar e mudar a ordem. Tudo passa por atualizar_carro:
# o preparo, o Registro ("alterar_carro") e a limpeza do depósito ficam num lugar só.

class CarroNaoEncontrado(LookupError):
    """Carro (ou foto) que não existe NESTA loja."""


def _carro_para_fotos(carro_id, loja_id) -> dict:
    carro = buscar_carro(carro_id, loja_id)
    if carro is None:
        raise CarroNaoEncontrado("Não encontramos esse carro.")
    if carro["status"] == VENDIDO:
        raise StatusInvalido(MENSAGEM_JA_VENDIDO)
    return carro


def _regravar_fotos(carro: dict, refs: list, loja_id) -> None:
    from app import fotos as _fotos
    atualizar_carro(carro["id"], carro["marca"], carro["modelo"], carro["ano"], carro["km"], carro["cor"],
                    carro["cambio"], carro["preco"], carro["status"], _fotos.juntar(refs), loja_id=loja_id)


def adicionar_fotos(carro_id, arquivos, *, loja_id) -> tuple[list, list]:
    """arquivos: [(nome, bytes)]. Cada um passa pelo preparo; os recusados não impedem os outros.
    Devolve (referências do carro na ordem, [(nome, mensagem)] recusados). Nenhum entrou: FotosInvalidas."""
    from app import fotos as _fotos
    carro = _carro_para_fotos(carro_id, loja_id)
    atuais = _fotos.separar(carro["fotos"])
    novas, recusadas = [], []
    for nome, dados in arquivos:
        if len(atuais) + len(novas) >= _fotos.MAX_FOTOS_POR_CARRO:
            recusadas.append((nome, _fotos.MSG_DEMAIS))
            continue
        try:
            novas.append(_fotos.guardar(loja_id, dados))
        except _fotos.FotoRecusada as erro:
            recusadas.append((nome, str(erro)))
    if not novas:
        raise FotosInvalidas(recusadas[0][1] if recusadas else _fotos.MSG_NAO_E_IMAGEM)
    try:
        _regravar_fotos(carro, atuais + novas, loja_id)
    except BaseException:
        _apagar_fotos(loja_id, novas)
        raise
    return atuais + novas, recusadas


def adicionar_foto_por_link(carro_id, link, *, loja_id) -> list:
    from app import fotos as _fotos
    carro = _carro_para_fotos(carro_id, loja_id)
    atuais = _fotos.separar(carro["fotos"])
    if len(atuais) >= _fotos.MAX_FOTOS_POR_CARRO:
        raise FotosInvalidas(_fotos.MSG_DEMAIS)
    if not str(link or "").strip().startswith("https://"):
        raise FotosInvalidas(_fotos.MSG_LINK)
    try:
        nova = _fotos.guardar_de_link(loja_id, str(link).strip())
    except _fotos.FotoRecusada as erro:
        raise FotosInvalidas(str(erro)) from None
    try:
        _regravar_fotos(carro, atuais + [nova], loja_id)
    except BaseException:
        _apagar_fotos(loja_id, [nova])
        raise
    return atuais + [nova]


def apagar_foto(carro_id, nome, *, loja_id) -> list:
    """Tira a foto do carro (e do depósito). Foto que não é deste carro: CarroNaoEncontrado."""
    from app import fotos as _fotos
    carro = _carro_para_fotos(carro_id, loja_id)
    atuais = _fotos.separar(carro["fotos"])
    alvo = _fotos.ref_de(loja_id, nome) if _fotos.NOME.match(str(nome or "")) else None
    if alvo not in atuais:
        raise CarroNaoEncontrado("Essa foto não é deste carro.")
    ficam = [r for r in atuais if r != alvo]
    _regravar_fotos(carro, ficam, loja_id)
    return ficam


MENSAGEM_ORDEM = "A lista de fotos não confere com as fotos do carro. Recarregue a página e tente de novo."


def ordenar_fotos(carro_id, enderecos, *, loja_id) -> list:
    """Mesmas fotos do carro, na ordem nova (endereços que o painel mostrou)."""
    from app import fotos as _fotos
    carro = _carro_para_fotos(carro_id, loja_id)
    atuais = _fotos.separar(carro["fotos"])
    nova = [_fotos.ref_do_endereco(loja_id, e) for e in (enderecos or [])]
    if None in nova or sorted(nova) != sorted(atuais) or len(set(nova)) != len(nova):
        raise FotosInvalidas(MENSAGEM_ORDEM)
    _regravar_fotos(carro, nova, loja_id)
    return nova
