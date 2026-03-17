import streamlit as st
import pandas as pd
from st_supabase_connection import SupabaseConnection
import google.generativeai as genai
import json

st.set_page_config(page_title="Guardian AI", layout="wide", page_icon="🛡️")
st.title("🛡️ Guardian: Inteligência de Dados")

# --- CONEXÃO IA ---
gemini_key = st.secrets.get("GEMINI_API_KEY")

if not gemini_key:
    st.error("⚠️ API Key não encontrada!")
    st.stop()

genai.configure(api_key=gemini_key)

# --- JOGADA DE MESTRE: LISTAR MODELOS DISPONÍVEIS ---
st.sidebar.subheader("🔍 Status da IA")
try:
    available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
    st.sidebar.write("Modelos encontrados:")
    st.sidebar.code(available_models)
    
    # Tentamos pegar o 1.5-flash, se não tiver, pegamos o primeiro da lista
    chosen_model = 'models/gemini-1.5-flash' if 'models/gemini-1.5-flash' in available_models else available_models[0]
    model = genai.GenerativeModel(chosen_model)
    st.sidebar.success(# render as markdown
        f"Usando: {chosen_model}")
except Exception as e:
    st.sidebar.error(f"Erro ao listar modelos: {e}")
    st.stop()

# --- NAVEGAÇÃO ---
menu = st.sidebar.radio("Navegação", ["📊 Dashboard", "🤖 Importar com IA"])

if menu == "🤖 Importar com IA":
    st.subheader("Analista IA: Leitura de Relatórios")
    uploaded_file = st.file_uploader("Suba o arquivo (Excel ou CSV)", type=['xlsx', 'csv'])

    if uploaded_file:
        with st.spinner(f"Processando com {chosen_model}..."):
            try:
                df = pd.read_excel(uploaded_file) if uploaded_file.name.endswith('.xlsx') else pd.read_csv(uploaded_file)
                df_clean = df.dropna(how='all').dropna(axis=1, how='all')
                contexto = df_clean.head(100).to_string()
                
                prompt = f"Retorne APENAS um JSON: [{{'ativo': 'NOME', 'valor_mercado': 0.0, 'tipo_ativo': 'TIPO'}}] com os dados: {contexto}"
                
                response = model.generate_content(prompt)
                
                start = response.text.find('[')
                end = response.text.rfind(']') + 1
                dados = json.loads(response.text[start:end])
                
                st.table(dados)
                
                if st.button("Confirmar e Salvar"):
                    conn = st.connection("supabase", type=SupabaseConnection)
                    conn.table("carteira_diaria").insert(dados).execute()
                    st.success("Salvo!")
            except Exception as e:
                st.error(f"Erro: {e}")
else:
    st.subheader("📊 Posição Consolidada")
    try:
        conn = st.connection("supabase", type=SupabaseConnection)
        res = conn.table("carteira_diaria").select("*").execute()
        if res.data:
            st.dataframe(pd.DataFrame(res.data), use_container_width=True)
    except Exception as e:
        st.error(f"Erro no banco: {e}")
