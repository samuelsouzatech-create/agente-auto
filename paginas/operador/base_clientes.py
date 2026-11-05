"""Base de clientes (nível Loja), S7 da Fase 3.

Tela nova sobre a importação da Etapa 2 (app/importacao.py), que NÃO muda
por dentro. A tela só mostra e chama as funções de lá:
  resumo_da_base, MODELO_CSV, ler_planilha (só lê, não grava), importar
  (grava numa transação e já vai para o Registro), listar_importacoes e
  desfazer_importacao (também vai para o Registro).

Quatro passos: planilha modelo, arquivo, prévia (nada gravado) e
confirmação. Nada é enviado a ninguém nesta tela.

E2-2: a declaração de autorização é da LOJA. O aviso aparece antes do botão
Importar; quem declarou e quando ficam gravados pela própria importação.
Sem a declaração a importação continua possível: o contato fica guardado,
mas a loja não manda mensagem por iniciativa própria para ele.

Decisões do Samuel no S7: (1B) Desfazer pede confirmação numa caixinha;
(2) pós-venda da base e reativação continuam em "Importar base", no grupo
"Antigas (serão removidas)".
"""
import streamlit as st

from app import importacao
from app.apresentacao import horario_para_tela
from app.lojas import carregar_loja
from app.relogio import agora_utc, dia_local
from app.telefone import formatar_telefone_br
from paginas.comum import (
    avisar, definir_ator_da_sessao, exigir_operador, loja_atual, mostrar_aviso, para_streamlit,
    usuario_atual,
)

AVISO_NADA_ENVIADO = ("Nada é enviado a ninguém nesta tela. A importação apenas registra os "
                      "contatos e as compras anteriores na base da loja.")
AVISO_CONSENTIMENTO = ("A loja declara que possui autorização dos clientes desta planilha para "
                       "receber mensagens pelo WhatsApp. A loja é responsável por essa declaração. "
                       "Sem a declaração, os contatos ficam guardados e o assistente os reconhece "
                       "quando escreverem, mas a loja não manda mensagem por iniciativa própria "
                       "para eles.")
ROTULO_CONSENTIMENTO = ("Confirmo, em nome da loja, que temos autorização dos clientes importados "
                        "para receber mensagens pelo WhatsApp.")
NOMES_DOS_CAMPOS = {"telefone": "Telefone", "nome": "Nome", "carro": "Carro",
                    "data_compra": "Data da compra", "pagamento": "Pagamento", "meses": "Meses"}
PAGAMENTOS = {"avista": "à vista", "financiado": "financiado"}
MAX_PREVIA = 50

exigir_operador()
loja = carregar_loja(loja_atual())

st.title("📇 Base de clientes")
st.caption(f"{para_streamlit(loja.nome)} · clientes e compras de antes do sistema, por planilha CSV.")
definir_ator_da_sessao()          # quem age nesta execução (o nome vem do .env)
quem = usuario_atual()
mostrar_aviso()

# ------------------------------------------------------------ indicadores
resumo = importacao.resumo_da_base(loja.id)
c1, c2, c3 = st.columns(3)
c1.metric("Contatos na base", resumo["contatos"])
c2.metric("Com autorização", resumo["com_consentimento"])
c3.metric("Compras anteriores", resumo["compras"])

# ------------------------------------------------------------ passo 1
st.subheader("1. Planilha modelo")
st.markdown(
    "- Só a coluna **telefone** é obrigatória (celular, com DDD).\n"
    "- Opcionais: **nome**, **carro**, **data_compra**, **pagamento** (à vista ou financiado) e "
    "**meses** (do financiamento).\n"
    "- No Excel: *Salvar como → CSV*. Antes, formate a coluna de telefone como **Texto**.\n"
    "- A compra só entra com carro **e** data. Sem isso, entra só o contato.")
st.download_button("Baixar planilha modelo (CSV)", importacao.MODELO_CSV.encode("utf-8-sig"),
                   file_name="modelo_base.csv", mime="text/csv", key="s7_modelo")

# ------------------------------------------------------------ passo 2
st.subheader("2. Arquivo")
feitas = st.session_state.get("_s7_importacoes", 0)
arquivo = st.file_uploader("Planilha (CSV)", type=["csv"], key=f"s7_arquivo_{loja.id}_{feitas}")

previa = None
if arquivo is None:
    st.caption("Escolha o arquivo para ver a prévia. Nada é gravado antes da confirmação.")
else:
    try:
        previa = importacao.ler_planilha(arquivo.getvalue(), hoje=dia_local(loja, agora_utc()))
    except importacao.PlanilhaInvalida as erro:
        st.error(str(erro))

# ------------------------------------------------------------ passos 3 e 4
if previa is not None:
    st.subheader("3. Prévia (nada foi gravado ainda)")
    st.caption("Colunas reconhecidas: " + ", ".join(
        f"{NOMES_DOS_CAMPOS.get(campo, campo)} ← “{para_streamlit(nome)}”"
        for campo, nome in previa.colunas.items()))
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Linhas lidas", previa.total_linhas)
    m2.metric("Contatos", len(previa.contatos()))
    m3.metric("Compras", len(previa.compras))
    m4.metric("Recusadas", len(previa.recusadas))

    if previa.linhas:
        st.dataframe([{
            "Linha": l.linha, "Nome": l.nome, "Telefone": formatar_telefone_br(l.telefone),
            "Compra": l.carro,
            "Data": l.data_compra.strftime("%d/%m/%Y") if l.data_compra else "",
            "Pagamento": PAGAMENTOS.get(l.pagamento or "", ""), "Meses": str(l.meses) if l.meses else "",
        } for l in previa.linhas[:MAX_PREVIA]], hide_index=True)
        if len(previa.linhas) > MAX_PREVIA:
            st.caption(f"Mostrando {MAX_PREVIA} de {len(previa.linhas)} linhas válidas.")
    if previa.recusadas:
        with st.expander(f"⚠️ {len(previa.recusadas)} linha(s) recusada(s): não entram",
                         expanded=True):
            st.dataframe([{"Linha": n, "Motivo": m} for n, m in previa.recusadas],
                         hide_index=True)
    if previa.avisos:
        with st.expander(f"ℹ️ {len(previa.avisos)} aviso(s): a linha entra, com ressalva",
                         expanded=True):
            st.dataframe([{"Linha": n, "Aviso": m} for n, m in previa.avisos], hide_index=True)

    st.subheader("4. Confirmação")
    st.info("📭 " + AVISO_NADA_ENVIADO)
    st.warning("⚖️ " + AVISO_CONSENTIMENTO)
    consentimento = st.checkbox(ROTULO_CONSENTIMENTO, key=f"s7_consentimento_{feitas}")
    if not previa.linhas:
        st.caption("Nenhuma linha válida: corrija a planilha e escolha o arquivo de novo.")
    if st.button("Importar", type="primary", disabled=not previa.linhas, key="s7_importar"):
        try:
            r = importacao.importar(loja.id, previa, usuario=quem, consentimento=consentimento,
                                    arquivo=getattr(arquivo, "name", ""))
        except importacao.ImportacaoInvalida as erro:
            avisar(str(erro), "error")
        else:
            texto = (f"Importação feita: {r['contatos_novos']} contato(s) novo(s), "
                     f"{r['contatos_atualizados']} atualizado(s) e "
                     f"{r['compras_novas']} compra(s) nova(s).")
            if r["compras_repetidas"]:
                texto += f" {r['compras_repetidas']} compra(s) já estavam na base."
            if consentimento:
                texto += f" Autorização declarada por {quem}."
            else:
                texto += (" Sem autorização declarada: a loja não manda mensagem por iniciativa "
                          "própria para esses contatos.")
            avisar(texto)
            st.session_state["_s7_importacoes"] = feitas + 1
        st.rerun()

# ------------------------------------------------------------ histórico
st.divider()
st.subheader("Importações feitas")
lista = importacao.listar_importacoes(loja.id)
if not lista:
    st.info("Nenhuma importação nesta loja ainda.")
else:
    st.dataframe([{
        "Quando": horario_para_tela(loja, i["criado_em"]),
        "Arquivo": i["arquivo"] or "—",
        "Quem importou": i["usuario"],
        "Contatos novos": i["contatos_novos"] or 0,
        "Contatos atualizados": i["contatos_atualizados"] or 0,
        "Compras": i["compras"] or 0,
        "Linhas recusadas": i["recusadas"] or 0,
        "Autorização": "Declarada" if i["consentimento"] else "Não declarada",
        "Situação": (f"Desfeita ({horario_para_tela(loja, i['desfeita_em'])})"
                     if i["desfeita_em"] else "Valendo"),
    } for i in lista], hide_index=True)
    st.caption("Mostrando as importações mais recentes.")

    ativas = [i for i in lista if not i["desfeita_em"]]
    if ativas:
        st.markdown("**Desfazer uma importação**")
        st.caption("Desfazer apaga as compras dessa importação e os contatos que ela criou. "
                   "Contatos que já existiam antes dela continuam na base.")
        desfeitas = st.session_state.get("_s7_desfeitas", 0)
        rotulos = {i["id"]: (f"{horario_para_tela(loja, i['criado_em'])} · "
                             f"{i['arquivo'] or 'sem nome'} · "
                             f"{i['contatos_novos'] or 0} contato(s) novo(s)") for i in ativas}
        escolhida = st.selectbox("Qual importação", list(rotulos), format_func=rotulos.get,
                                 key=f"s7_desfazer_qual_{desfeitas}")
        certeza = st.checkbox("Confirmo que quero desfazer esta importação.",
                              key=f"s7_desfazer_conf_{desfeitas}")
        if st.button("Desfazer", disabled=not certeza, key="s7_desfazer") and certeza:
            try:
                r = importacao.desfazer_importacao(loja.id, escolhida)
            except importacao.ImportacaoInvalida as erro:
                avisar(str(erro), "error")
            else:
                avisar(f"Importação desfeita: {r['contatos']} contato(s) e {r['compras']} "
                       "compra(s) apagados.")
                st.session_state["_s7_desfeitas"] = desfeitas + 1
            st.rerun()

st.caption("Pós-venda da base e reativação continuam em “Importar base”, no grupo "
           "“Antigas (serão removidas)”.")
