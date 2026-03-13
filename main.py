import streamlit as st
from st_supabase_connection import SupabaseConnection

# Configuração da página
st.set_page_config(page_title="Guardian - Gestão de Fundos", layout="wide")

st.title("🛡️ Guardian: Carteira Diária")

# Conexão com o Supabase
conn = st.connection("supabase", type=SupabaseConnection)

# Aba de Visualização
tab1, tab2 = st.tabs(["📊 Visão Geral", "📝 Novo Lançamento"])

with tab1:
    st.subheader("Posição Consolidada")
    # Busca os dados do banco
    df = conn.query("*", table="carteira_diaria").execute()
    if df.data:
        st.dataframe(df.data) # Mostra a tabela bonitona
    else:
        st.info("Nenhum dado encontrado. Vá na aba de lançamentos!")

with tab2:
    st.subheader("Registrar Movimentação")
    with st.form("form_venda"):
        ativo = st.text_input("Nome do Ativo (Ex: PETR4)")
        valor = st.number_input("Valor de Mercado", min_value=0.0)
        tipo = st.selectbox("Tipo", ["Ações", "Renda Fixa", "FII", "Tesouro"])
        submit = st.form_submit_button("Salvar na Carteira")
        
        if submit:
            conn.table("carteira_diaria").insert({"ativo": ativo, "valor_mercado": valor, "tipo_ativo": tipo}).execute()
            st.success("Dado gravado com sucesso!")
