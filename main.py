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
            # Opção para pular linhas de cabeçalho (comum em relatórios de fundos)
            skip_rows = st.number_input("Pular quantas linhas de cabeçalho?", min_value=0, value=0)
            
            # Lendo o arquivo pulando as linhas escolhidas
            if uploaded_file.name.endswith('.csv'):
                df_import = pd.read_csv(uploaded_file, skiprows=skip_rows)
            else:
                df_import = pd.read_excel(uploaded_file, skiprows=skip_rows)
            
            st.write("Prévia dos dados:")
            st.dataframe(df_import.head(10)) # Mostra 10 linhas para conferir

            # Seleção de Colunas (O Tradutor)
            st.subheader("🔗 Mapeamento de Colunas")
            col_ativo = st.selectbox("Qual coluna é o NOME DO ATIVO?", df_import.columns)
            col_valor = st.selectbox("Qual coluna é o VALOR DE MERCADO?", df_import.columns)
            col_tipo = st.selectbox("Qual coluna é o TIPO DE ATIVO?", df_import.columns)

            if st.button("Confirmar Envio para o Supabase"):
                # Filtra apenas o que queremos e renomeia para o padrão do banco
                df_final = df_import[[col_ativo, col_valor, col_tipo]].copy()
                df_final.columns = ['ativo', 'valor_mercado', 'tipo_ativo']
                
                # Remove linhas vazias
                df_final = df_final.dropna(subset=['ativo'])
                
                dados = df_final.to_dict(orient='records')
                conn.table("carteira_diaria").insert(dados).execute()
                st.success(f"Show! {len(dados)} ativos importados com sucesso!")
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
