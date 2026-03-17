import streamlit as st
import pandas as pd
from st_supabase_connection import SupabaseConnection
import google.generativeai as genai
import json

# 1. Configuração e Título
st.set_page_config(page_title="Guardian AI", layout="wide")
st.title("🛡️ Guardian: Inteligência de Dados")

# 2. Puxa a chave dos Secrets
gemini_key = st.secrets.get("GEMINI_API_KEY")

if not gemini_key:
    st.error("⚠️ API Key não encontrada nos Secrets!")
    st.stop()

# 3. Configura o motor da IA
genai.configure(api_key=gemini_key)
model = genai.GenerativeModel('gemini-1.5-flash')

# 4. Navegação lateral
menu = st.sidebar.radio("Navegação", ["📊 Dashboard", "🤖 Importar com IA"])

if menu == "🤖 Importar com IA":
    st.subheader("Analista IA: Leitura de Relatórios")
    uploaded_file = st.file_uploader("Suba o arquivo (Excel ou CSV)", type=['xlsx', 'csv'])

    if uploaded_file:
        with st.spinner("IA processando dados..."):
            try:
                # Lê e limpa lixo do Excel
                df = pd.read_excel(uploaded_file) if uploaded_file.name.endswith('.xlsx') else pd.read_csv(uploaded_file)
                df_clean = df.dropna(how='all').dropna(axis=1, how='all')
                
                # Manda só o essencial para a IA (primeiras 100 linhas)
                contexto = df_clean.head(100).to_string()
                
                prompt = f"Retorne APENAS um JSON: [{{'ativo': 'NOME', 'valor_mercado': 0.0, 'tipo_ativo': 'TIPO'}}] com os ativos desta lista: {contexto}"
                
                response = model.generate_content(prompt)
                txt = response.text
                
                # Extrai o JSON da resposta da IA
                start, end = txt.find('['), txt.rfind(']') + 1
                dados = json.loads(txt[start:end])
                
                st.table(dados)
                
                if st.button("Confirmar e Salvar no Banco"):
                    conn = st.connection("supabase", type=SupabaseConnection)
                    conn.table("carteira_diaria").insert(dados).execute()
                    st.success("Salvo com sucesso!")
            except Exception as e:
                st.error(f"Erro: {e}")
else:
    st.subheader("Posição Consolidada")
    try:
        conn = st.connection("supabase", type=SupabaseConnection)
        res = conn.table("carteira_diaria").select("*").execute()
        if res.data:
            st.dataframe(pd.DataFrame(res.data), use_container_width=True)
    except:
        st.info("Aguardando dados...")
