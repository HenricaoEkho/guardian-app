import streamlit as st
import pandas as pd
from st_supabase_connection import SupabaseConnection

# Configuração
st.set_page_config(page_title="Guardian - Gestão", layout="wide")
st.title("🛡️ Guardian: Inteligência de Dados")

# Conexão
conn = st.connection("supabase", type=SupabaseConnection)

# Menu Lateral para navegação
menu = st.sidebar.radio("Navegação", ["Dashboard", "Importar Excel"])

if menu == "Importar Excel":
    st.subheader("🚀 Carga de Dados via Planilha")
    uploaded_file = st.file_uploader("Arraste seu Excel ou CSV aqui", type=['xlsx', 'csv'])

    if uploaded_file:
        try:
            # Lendo o arquivo corretamente
            df_import = pd.read_csv(uploaded_file) if uploaded_file.name.endswith('.csv') else pd.read_excel(uploaded_file)
            
            st.write("Prévia dos dados:")
            st.dataframe(df_import.head())

            if st.button("Confirmar Envio para o Supabase"):
                dados = df_import.to_dict(orient='records')
                conn.table("carteira_diaria").insert(dados).execute()
                st.success(f"Show! {len(dados)} linhas inseridas no banco.")
        except Exception as e:
            st.error(f"Erro no processamento: {e}")

else:
    st.subheader("📊 Posição da Carteira")
    try:
        response = conn.table("carteira_diaria").select("*").execute()
        if response.data:
            df = pd.DataFrame(response.data)
            st.dataframe(df, use_container_width=True)
            
            # Gráfico Simples
            if 'valor_mercado' in df.columns and 'ativo' in df.columns:
                st.bar_chart(data=df, x='ativo', y='valor_mercado')
        else:
            st.info("Banco de dados vazio.")
    except Exception as e:
        st.error(f"Erro ao carregar dashboard: {e}")
