import streamlit as st
import pandas as pd
from st_supabase_connection import SupabaseConnection

st.set_page_config(page_title="Guardian - Importador", layout="wide")
st.title("🛡️ Guardian: Carga de Dados")

conn = st.connection("supabase", type=SupabaseConnection)

# --- NOVO: IMPORTADOR DE EXCEL ---
st.subheader("🚀 Importar Carteira via Excel")
uploaded_file = st.file_uploader("Escolha o arquivo Excel ou CSV", type=['xlsx', 'csv'])

if uploaded_file:
    # Lendo o arquivo
    if uploaded_file.name.endswith('.csv'):
        df_import = pd.read_csv(uploaded_file)
    else:
        df_import = pd.read_excel(uploaded_file)
    
    st.write("Prévia dos dados encontrados:")
    st.dataframe(df_import.head())

    if st.button("Confirmar Carga no Banco"):
        # Transforma o Excel em formato que o Supabase entende (JSON)
        dados = df_import.to_dict(orient='records')
        try:
            conn.table("carteira_diaria").insert(dados).execute()
            st.success(f"Sucesso! {len(dados)} ativos importados.")
        except Exception as e:
            st.error(f"Erro na carga: {e}")

st.divider()

# --- ABA DE VISUALIZAÇÃO ---
st.subheader("📊 Posição Atual")
response = conn.table("carteira_diaria").select("*").execute()
if response.data:
    st.dataframe(response.data)import streamlit as st
from st_supabase_connection import SupabaseConnection

st.set_page_config(page_title="Guardian - Gestão de Fundos", layout="wide")
st.title("🛡️ Guardian: Carteira Diária")

# Conexão
conn = st.connection("supabase", type=SupabaseConnection)

tab1, tab2 = st.tabs(["📊 Visão Geral", "📝 Novo Lançamento"])

with tab1:
    st.subheader("Posição Consolidada")
    # Jeito direto de buscar os dados
    try:
        response = conn.table("carteira_diaria").select("*").execute()
        if response.data:
            st.dataframe(response.data, use_container_width=True)
        else:
            st.info("O banco está vazio. Registre algo na outra aba!")
    except Exception as e:
        st.error(f"Erro ao buscar dados: {e}")

with tab2:
    st.subheader("Registrar Movimentação")
    with st.form("form_venda"):
        ativo = st.text_input("Nome do Ativo (Ex: PETR4)")
        valor = st.number_input("Valor de Mercado", min_value=0.0)
        tipo = st.selectbox("Tipo", ["Ações", "Renda Fixa", "FII", "Tesouro"])
        submit = st.form_submit_button("Salvar na Carteira")
        
        if submit:
            try:
                conn.table("carteira_diaria").insert({"ativo": ativo, "valor_mercado": valor, "tipo_ativo": tipo}).execute()
                st.success("Dado gravado com sucesso! Atualize a página para ver na lista.")
            except Exception as e:
                st.error(f"Erro ao salvar: {e}")
