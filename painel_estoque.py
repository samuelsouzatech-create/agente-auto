"""
Painel de estoque (Fase 3 - Bloco 5) — CRUD de carros.

Aba separada do painel de handoff (painel.py), de propósito: no documento
(seção 7), este CRUD é a "fonte da verdade" só no cenário C — loja sem CRM/API.
Quando a loja tem sistema, o estoque vem de lá e esta tela nem entra.

Permite: ver a lista de carros, adicionar, editar (preço, km, fotos, etc.)
e marcar como vendido (tira da oferta na hora).

Rodar com:  streamlit run painel_estoque.py
"""
import streamlit as st

from app.estoque import (
    listar_estoque, adicionar_carro, atualizar_carro, marcar_status,
    OPCOES_CAMBIO, OPCOES_STATUS,
)


def para_streamlit(texto):
    """Escapa o '$' pra não virar fórmula LaTeX no Streamlit (igual ao app.py)."""
    return (texto or "").replace("$", "\\$")


def formatar_brl(valor):
    """98000.0 -> 'R$ 98.000,00'. Só pra exibição na lista."""
    try:
        return "R$ " + f"{float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (ValueError, TypeError):
        return "R$ —"


# Rótulos amigáveis para os status.
ROTULO_STATUS = {
    "disponivel": "🟢 Disponível",
    "reservado": "🟡 Reservado",
    "vendido": "🔴 Vendido",
}


st.set_page_config(page_title="Estoque - Léo", page_icon="🚗", layout="wide")
st.title("🚗 Painel de Estoque")
st.caption("Cadastrar, editar e dar baixa nos carros — Fase 3 (Bloco 5)")

st.sidebar.button("🔄 Atualizar lista")
mostrar_vendidos = st.sidebar.checkbox("Mostrar carros vendidos", value=True)


# ----------------------------------------------------------------------------
# 1) Adicionar carro novo
# ----------------------------------------------------------------------------
with st.expander("➕ Adicionar carro novo", expanded=False):
    with st.form("form_adicionar", clear_on_submit=True):
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
        fotos = st.text_area(
            "Fotos (URLs separadas por vírgula)",
            placeholder="https://.../foto1.jpg, https://.../foto2.jpg",
        )

        enviar = st.form_submit_button("💾 Cadastrar carro")
        if enviar:
            if not marca or not modelo or not cor:
                st.error("Preencha pelo menos marca, modelo e cor.")
            else:
                novo_id = adicionar_carro(
                    marca=marca.strip(), modelo=modelo.strip(), ano=int(ano),
                    km=int(km), cor=cor.strip(), cambio=cambio,
                    preco=float(preco), status=status, fotos=fotos.strip(),
                )
                st.success(f"Carro cadastrado (id {novo_id}).")
                st.rerun()


# ----------------------------------------------------------------------------
# 2) Lista de carros + edição por carro
# ----------------------------------------------------------------------------
carros = listar_estoque(incluir_vendidos=mostrar_vendidos)

if not carros:
    st.info("Nenhum carro no estoque ainda. Use '➕ Adicionar carro novo' acima.")
    st.stop()

st.write(f"**{len(carros)} carro(s) no estoque:**")

for carro in carros:
    carro_id = carro["id"]
    rotulo_status = ROTULO_STATUS.get(carro["status"], carro["status"])
    titulo = (
        f"{rotulo_status}  —  {carro['marca']} {carro['modelo']} {carro['ano']}"
        f"  —  {formatar_brl(carro['preco'])}  (id {carro_id})"
    )

    with st.expander(titulo, expanded=False):
        # Botão de baixa rápida, separado do formulário de edição.
        if carro["status"] != "vendido":
            if st.button("🔴 Marcar como VENDIDO", key=f"vender_{carro_id}"):
                marcar_status(carro_id, "vendido")
                st.success(f"{carro['marca']} {carro['modelo']} marcado como vendido.")
                st.rerun()
        else:
            if st.button("🟢 Voltar para DISPONÍVEL", key=f"voltar_{carro_id}"):
                marcar_status(carro_id, "disponivel")
                st.success(f"{carro['marca']} {carro['modelo']} voltou para a oferta.")
                st.rerun()

        st.markdown("---")

        # Formulário de edição completo deste carro.
        with st.form(f"form_editar_{carro_id}"):
            e1, e2, e3 = st.columns(3)
            with e1:
                ed_marca = st.text_input("Marca", value=carro["marca"], key=f"marca_{carro_id}")
                ed_ano = st.number_input(
                    "Ano", min_value=1950, max_value=2100,
                    value=int(carro["ano"]), step=1, key=f"ano_{carro_id}",
                )
                ed_cambio = st.selectbox(
                    "Câmbio", OPCOES_CAMBIO,
                    index=OPCOES_CAMBIO.index(carro["cambio"]) if carro["cambio"] in OPCOES_CAMBIO else 0,
                    key=f"cambio_{carro_id}",
                )
            with e2:
                ed_modelo = st.text_input("Modelo", value=carro["modelo"], key=f"modelo_{carro_id}")
                ed_km = st.number_input(
                    "Km", min_value=0, value=int(carro["km"]), step=1000, key=f"km_{carro_id}",
                )
                ed_preco = st.number_input(
                    "Preço (R$)", min_value=0.0, value=float(carro["preco"]),
                    step=1000.0, format="%.2f", key=f"preco_{carro_id}",
                )
            with e3:
                ed_cor = st.text_input("Cor", value=carro["cor"], key=f"cor_{carro_id}")
                ed_status = st.selectbox(
                    "Status", OPCOES_STATUS,
                    index=OPCOES_STATUS.index(carro["status"]) if carro["status"] in OPCOES_STATUS else 0,
                    key=f"status_{carro_id}",
                )
            ed_fotos = st.text_area(
                "Fotos (URLs separadas por vírgula)",
                value=carro.get("fotos") or "", key=f"fotos_{carro_id}",
            )

            salvar = st.form_submit_button("💾 Salvar alterações")
            if salvar:
                atualizar_carro(
                    carro_id,
                    marca=ed_marca.strip(), modelo=ed_modelo.strip(), ano=int(ed_ano),
                    km=int(ed_km), cor=ed_cor.strip(), cambio=ed_cambio,
                    preco=float(ed_preco), status=ed_status, fotos=ed_fotos.strip(),
                )
                st.success("Alterações salvas.")
                st.rerun()

        # Prévia das fotos cadastradas (se houver URLs).
        if carro.get("fotos"):
            urls = [u.strip() for u in carro["fotos"].split(",") if u.strip()]
            if urls:
                st.markdown("**Fotos cadastradas:**")
                st.image(urls, width=200)
