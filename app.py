r"""
Simulador do Léo com cara de conversa de WhatsApp (Plano Mestre D2; Maratona 2, M2).

    .venv-teste\Scripts\streamlit run app.py

Canal "simulador": nada sai para ninguém. Balões de conversa, nome do assistente e da loja vindos
da configuração, fotos dentro da conversa e, ao lado, o que o vendedor recebeu (o aviso do
chamado), sem Telegram. A tela só mostra: quem decide é app/.
"""
import asyncio
import html
import uuid

import streamlit as st

import banco
from app.core.turno import executar_turno
from app.demo import avisos_ao_vendedor, cabecalho_do_simulador, id_da_loja_demo, mensagens_do_vendedor

CANAL = "simulador"
VERSAO_HISTORICO = 3          # Q2: (quem, texto, fotos, autor)
VER_VENDEDOR_A_CADA = "4s"    # Q2: busca a resposta do vendedor (painel) sozinho

ESTILO = """
<style>
.zap-topo {background:#075e54;color:#fff;padding:10px 14px;border-radius:10px 10px 0 0;font-weight:600}
.zap-topo small {display:block;font-weight:400;opacity:.85}
.zap-fundo {background:#ece5dd;padding:12px;border-radius:0 0 10px 10px;min-height:120px}
.zap-msg {max-width:80%;padding:8px 11px;margin:6px 0;border-radius:8px;line-height:1.35;
          white-space:pre-wrap;box-shadow:0 1px 1px rgba(0,0,0,.12);color:#111}
.zap-cliente {background:#dcf8c6;margin-left:auto}
.zap-leo {background:#fff;margin-right:auto}
.zap-vendedor {background:#e3f0ff;margin-right:auto}
.zap-msg b {display:block;font-size:.85em;color:#555}
.zap-aviso {background:#fff3cd;border-left:4px solid #e0a800;padding:8px 10px;margin:6px 0;border-radius:6px;color:#111}
</style>
"""


def listar_lojas():
    conexao = banco.conectar()
    try:
        return [(l["id"], l["nome"]) for l in conexao.execute("SELECT id, nome FROM lojas ORDER BY id")]
    finally:
        conexao.close()


def nova_conversa(loja_id):
    st.session_state.loja_id = loja_id
    st.session_state.lead_id = f"sim-{uuid.uuid4().hex[:8]}"
    st.session_state.historico = []          # (quem, texto, fotos, autor)
    st.session_state.ultimo_do_vendedor = 0  # Q2: última resposta do vendedor já mostrada
    st.session_state.versao_historico = VERSAO_HISTORICO


def balao(quem: str, texto: str, autor: str | None = None) -> None:
    classe = {"cliente": "zap-cliente", "vendedor": "zap-vendedor"}.get(quem, "zap-leo")
    nome = f"<b>{html.escape(autor)} (vendedor)</b>" if quem == "vendedor" and autor else ""
    st.markdown(f'<div class="zap-msg {classe}">{nome}{html.escape(texto)}</div>', unsafe_allow_html=True)


st.set_page_config(page_title="Léo - Simulador", page_icon="💬", layout="wide")
st.markdown(ESTILO, unsafe_allow_html=True)

lojas = listar_lojas()
if not lojas:
    st.error("Nenhuma loja cadastrada. Crie a loja de demonstração: scripts\\criar_loja_demo.py")
    st.stop()

nomes = {nome: id_ for id_, nome in lojas}
demo = id_da_loja_demo()
padrao = next((i for i, (id_, _) in enumerate(lojas) if id_ == demo), 0)
escolha = st.sidebar.selectbox("Conversar com a loja", list(nomes), index=padrao)
loja_id = nomes[escolha]

if (st.session_state.get("loja_id") != loja_id
        or st.session_state.get("versao_historico") != VERSAO_HISTORICO):
    nova_conversa(loja_id)
if st.sidebar.button("Nova conversa"):
    nova_conversa(loja_id)
    st.rerun()

topo = cabecalho_do_simulador(loja_id)
conversa, lateral = st.columns([2, 1])

@st.fragment(run_every=VER_VENDEDOR_A_CADA)
def mostrar_conversa():
    """Q2: a cada poucos segundos, traz do banco o que o vendedor respondeu pelo painel
    (só existe na loja de demonstração; nada é enviado a ninguém)."""
    for m in mensagens_do_vendedor(loja_id, st.session_state.lead_id, st.session_state.ultimo_do_vendedor):
        st.session_state.historico.append(("vendedor", m["texto"], [], m["autor"]))
        st.session_state.ultimo_do_vendedor = m["id"]
    st.markdown(f'<div class="zap-topo">{html.escape(topo["agente"])}'
                f'<small>{html.escape(topo["loja"])} · simulador (nada é enviado a ninguém)</small></div>',
                unsafe_allow_html=True)
    with st.container(border=True):
        if not st.session_state.historico:
            st.caption("Escreva como se fosse um cliente no WhatsApp da loja.")
        for quem, texto, fotos, autor in st.session_state.historico:
            if texto:
                balao(quem, texto, autor)
            for caminho in fotos:
                st.image(caminho, width=300)


with conversa:
    mostrar_conversa()

with lateral:
    st.subheader("O vendedor recebeu")
    avisos = avisos_ao_vendedor(loja_id, st.session_state.lead_id)
    if not avisos:
        st.caption("Nenhum aviso ainda. Quando o assistente chamar um vendedor, o aviso aparece aqui.")
    for aviso in avisos:
        st.markdown(f'<div class="zap-aviso"><b>{html.escape(aviso["quando"])}</b> · '
                    f'{html.escape(aviso["situacao"])}<br>{html.escape(aviso["motivo"])}'
                    f'<br><i>{html.escape(aviso["resumo"])}</i></div>', unsafe_allow_html=True)

if entrada := st.chat_input("Mensagem"):
    st.session_state.historico.append(("cliente", entrada, [], None))
    with st.spinner(f"{topo['agente']} está digitando..."):
        resultado = asyncio.run(executar_turno(loja_id, CANAL, st.session_state.lead_id, entrada))
    if resultado.silenciado:
        st.session_state.historico.append(
            ("leo", "(Um vendedor assumiu esta conversa. O assistente está em silêncio.)", [], None))
    else:
        st.session_state.historico.append(("leo", resultado.texto or "", resultado.midias, None))
    st.rerun()
