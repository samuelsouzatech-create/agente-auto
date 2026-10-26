"""Estoque da loja escolhida: cadastrar, editar e dar baixa."""
import streamlit as st

from app.estoque import (
    OPCOES_CAMBIO, OPCOES_STATUS, adicionar_carro, atualizar_carro, listar_estoque, marcar_status,
)
from app.lojas import carregar_loja
from paginas.comum import formatar_brl, loja_atual

ROTULO_STATUS = {"disponivel": "🟢 Disponível", "reservado": "🟡 Reservado", "vendido": "🔴 Vendido"}

loja = carregar_loja(loja_atual())
st.title("🚗 Estoque")
st.caption(f"{loja.nome} · cadastrar, editar e dar baixa nos carros")
mostrar_vendidos = st.checkbox("Mostrar carros vendidos", value=True)

with st.expander("➕ Adicionar carro novo", expanded=False):
    with st.form(f"form_adicionar_{loja.id}", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            marca = st.text_input("Marca")
            ano = st.number_input("Ano", min_value=1950, max_value=2100, value=2020, step=1)
            cambio = st.selectbox("Câmbio", OPCOES_CAMBIO)
        with c2:
            modelo = st.text_input("Modelo")
            km = st.number_input("Km", min_value=0, value=0, step=1000)
            preco = st.number_input("Preço (R$)", min_value=0.0, value=0.0, step=1000.0, format="%.2f")
        with c3:
            cor = st.text_input("Cor")
            status = st.selectbox("Status", OPCOES_STATUS)
        fotos = st.text_area("Fotos (URLs separadas por vírgula)",
                             placeholder="https://.../foto1.jpg, https://.../foto2.jpg")
        if st.form_submit_button("💾 Cadastrar carro"):
            if not marca or not modelo or not cor:
                st.error("Preencha pelo menos marca, modelo e cor.")
            else:
                novo_id = adicionar_carro(
                    marca=marca.strip(), modelo=modelo.strip(), ano=int(ano), km=int(km),
                    cor=cor.strip(), cambio=cambio, preco=float(preco), status=status,
                    fotos=fotos.strip(), loja_id=loja.id,
                )
                st.success(f"Carro cadastrado (id {novo_id}).")
                st.rerun()

carros = listar_estoque(loja_id=loja.id, incluir_vendidos=mostrar_vendidos)
if not carros:
    st.info("Nenhum carro no estoque desta loja. Use '➕ Adicionar carro novo' acima.")
    st.stop()

st.write(f"**{len(carros)} carro(s) no estoque:**")
for carro in carros:
    cid = carro["id"]
    titulo = (f"{ROTULO_STATUS.get(carro['status'], carro['status'])}  —  {carro['marca']} "
              f"{carro['modelo']} {carro['ano']}  —  {formatar_brl(carro['preco'])}  (id {cid})")
    with st.expander(titulo, expanded=False):
        if carro["status"] != "vendido":
            if st.button("🔴 Marcar como VENDIDO", key=f"vender_{cid}"):
                marcar_status(cid, "vendido", loja_id=loja.id)
                st.rerun()
        elif st.button("🟢 Voltar para DISPONÍVEL", key=f"voltar_{cid}"):
            marcar_status(cid, "disponivel", loja_id=loja.id)
            st.rerun()

        st.markdown("---")
        with st.form(f"form_editar_{cid}"):
            e1, e2, e3 = st.columns(3)
            with e1:
                ed_marca = st.text_input("Marca", value=carro["marca"])
                ed_ano = st.number_input("Ano", min_value=1950, max_value=2100,
                                         value=int(carro["ano"]), step=1)
                ed_cambio = st.selectbox(
                    "Câmbio", OPCOES_CAMBIO,
                    index=OPCOES_CAMBIO.index(carro["cambio"]) if carro["cambio"] in OPCOES_CAMBIO else 0)
            with e2:
                ed_modelo = st.text_input("Modelo", value=carro["modelo"])
                ed_km = st.number_input("Km", min_value=0, value=int(carro["km"]), step=1000)
                ed_preco = st.number_input("Preço (R$)", min_value=0.0, value=float(carro["preco"]),
                                           step=1000.0, format="%.2f")
            with e3:
                ed_cor = st.text_input("Cor", value=carro["cor"])
                ed_status = st.selectbox(
                    "Status", OPCOES_STATUS,
                    index=OPCOES_STATUS.index(carro["status"]) if carro["status"] in OPCOES_STATUS else 0)
            ed_fotos = st.text_area("Fotos (URLs separadas por vírgula)", value=carro.get("fotos") or "")
            if st.form_submit_button("💾 Salvar alterações"):
                atualizar_carro(
                    cid, marca=ed_marca.strip(), modelo=ed_modelo.strip(), ano=int(ed_ano),
                    km=int(ed_km), cor=ed_cor.strip(), cambio=ed_cambio, preco=float(ed_preco),
                    status=ed_status, fotos=ed_fotos.strip(), loja_id=loja.id,
                )
                st.success("Alterações salvas.")
                st.rerun()

        urls = [u.strip() for u in (carro.get("fotos") or "").split(",") if u.strip()]
        if urls:
            st.markdown("**Fotos cadastradas:**")
            st.image(urls, width=200)
