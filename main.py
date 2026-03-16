import streamlit as st
import pandas as pd
from st_supabase_connection import SupabaseConnection
import google.generativeai as genai
import json

# Configuração Inicial
st.set_page_config(page_title="Guardian AI", layout="wide")
st.title("🛡️ Guardian: Inteligência de Dados com IA")

# Conexões
conn = st.connection("supabase", type=SupabaseConnection)
genai.configure(api_key=st.secrets.get("GEMINI_API_KEY", "CHAVE_NAO_ENCONTRADA"))
model = genai.GenerativeModel('gemini-1.5-flash')

menu = st.sidebar.radio("Navegação", ["Dashboard", "Importar com IA"])

if menu == "Importar com IA":
    st.subheader("🤖 Analista IA: Leitura de Relatórios Complexos")
    uploaded_file = st.file_uploader("Suba o PDF ou Excel do Fundo", type=['xlsx', 'pdf', 'csv'])

    if uploaded_file:
        with st.spinner("O Gemini está analisando os dados..."):
            # Converte o arquivo para uma string (texto) para a IA ler
            df_raw = pd.read_excel(uploaded_file).to_string()
            
            prompt = f"""
            Abaixo estão os dados brutos de um relatório de fundo de investimento. 
            Extraia todos os ativos da carteira, seus valores de mercado e tipos de ativos.
            Retorne APENAS um JSON no formato:
            [{"ativo": "NOME", "valor_mercado": 0.0, "tipo_ativo": "TIPO"}]
            Dados: {df_raw}
            """
            
            response = model.generate_content(prompt)
            # Limpa a resposta para pegar apenas o JSON
            clean_json = response.text.replace('```json', '').replace('```', '').strip()
            dados_estruturados = json.loads(clean_json)
            
            st.write("✅ IA Identificou os seguintes dados:")
            st.table(dados_estruturados)

            if st.button("Confirmar e Salvar no Supabase"):
                conn.table("carteira_diaria").insert(dados_estruturados).execute()
                st.success("Dados salvos com sucesso!")

else:
    st.subheader("📊 Posição Consolidada")
    res = conn.table("carteira_diaria").select("*").execute()
    if res.data:
        st.dataframe(pd.DataFrame(res.data))
    else:
        st.info("Nenhum dado no banco.")
