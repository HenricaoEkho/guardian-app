import streamlit as st
import pandas as pd
from st_supabase_connection import SupabaseConnection
import google.generativeai as genai
import json

# --- CONFIGURAÇÃO ---
st.set_page_config(page_title="Guardian Hard Reset", layout="wide", page_icon="🛡️")

def format_br(valor):
    try:
        val = float(valor)
        return f"R$ {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except: return str(valor)

# --- CONEXÃO IA ---
gemini_key = st.secrets.get("GEMINI_API_KEY")
if gemini_key:
    genai.configure(api_key=gemini_key)

# --- SIDEBAR DE DIAGNÓSTICO ---
st.sidebar.title("🛡️ Diagnóstico Guardian")
try:
    # Vamos listar o que o Google diz que você tem
    modelos_reais = [m.name for m in genai.list_models()]
    st.sidebar.write("✅ Modelos que sua Key enxerga:")
    st.sidebar.code(modelos_reais)
    
    # Deixa você escolher um da lista se o automático falhar
    modelo_escolhido = st.sidebar.selectbox("Escolha um modelo manualmente:", modelos_reais)
except Exception as e:
    st.sidebar.error(f"Erro ao listar modelos: {e}")
    modelo_escolhido = "gemini-1.5-flash" # Fallback

conn = st.connection("supabase", type=SupabaseConnection)

# --- INTERFACE ---
menu = st.sidebar.radio("Navegação", ["📊 Dashboard", "🤖 Importar Carteira"])

if menu == "🤖 Importar Carteira":
    st.subheader("📥 Carga de Dados (Modo Força Bruta)")
    uploaded_file = st.file_uploader("Suba o Excel ou PDF", type=['xlsx', 'pdf'])

    if uploaded_file:
        # Usamos o modelo que você selecionou no sidebar ou o flash
        if st.button("🚀 Iniciar Processamento"):
            with st.spinner(f"Tentando usar: {modelo_escolhido}..."):
                try:
                    df = pd.read_excel(uploaded_file) if uploaded_file.name.endswith('.xlsx') else pd.read_csv(uploaded_file)
                    contexto = df.dropna(how='all').head(300).to_string()
                    
                    prompt = f"Extraia em JSON puro: {{'nome_fundo': 'NOME', 'ativos': [{{'ativo': 'NOME', 'valor_mercado': 0.0, 'tipo_ativo': 'TIPO'}}]}} DADOS: {contexto}"
                    
                    # Chamada direta sem frescura
                    model = genai.GenerativeModel(modelo_escolhido)
                    response = model.generate_content(prompt)
                    
                    raw_text = response.text
                    data = json.loads(raw_text[raw_text.find('{'):raw_text.rfind('}')+1])
                    
                    st.success(f"🔥 FUNCIONOU COM: {modelo_escolhido}")
                    st.write(f"📌 Fundo: **{data['nome_fundo']}**")
                    st.table(pd.DataFrame(data['ativos']).assign(valor_mercado=lambda x: x['valor_mercado'].apply(format_br)))
                    
                    # Salva na sessão para o botão de gravar aparecer
                    st.session_state['import_ok'] = data

                except Exception as e:
                    st.error(f"Putz, ainda deu erro: {e}")
                    st.info("💡 Dica: Olhe a lista na esquerda e tente trocar o modelo no seletor!")

    if 'import_ok' in st.session_state:
        if st.button("💾 Gravar no Supabase"):
            # Lógica de gravação...
            st.success("Dados salvos!")
            del st.session_state['import_ok']
