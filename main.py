import streamlit as st
import pandas as pd
from st_supabase_connection import SupabaseConnection
import google.generativeai as genai
import json

# --- CONFIGURAÇÃO ---
st.set_page_config(page_title="Guardian Ultra 6.5", layout="wide", page_icon="🛡️")

def format_br(valor):
    try:
        val = float(valor)
        return f"R$ {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except: return str(valor)

# --- CONEXÃO IA INTELIGENTE ---
gemini_key = st.secrets.get("GEMINI_API_KEY")
if gemini_key:
    genai.configure(api_key=gemini_key)

def extrair_com_ia_radar(prompt):
    try:
        # 1. Tenta listar todos os modelos que você tem acesso
        modelos = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        
        # 2. Ordem de prioridade: 2.5-flash (se tiver cota) -> 1.5-flash -> 1.5-pro -> o que sobrar
        preferencia = ["2.5-flash", "1.5-flash", "1.5-pro"]
        model_to_use = None
        
        # Busca na lista do Google algo que bata com nossa preferência
        for pref in preferencia:
            match = [m for m in modelos if pref in m]
            if match:
                model_to_use = match[0]
                break
        
        if not model_to_use:
            model_to_use = modelos[0] # Pega qualquer um que sobrar

        # 3. Executa a extração
        model = genai.GenerativeModel(model_to_use)
        response = model.generate_content(prompt)
        return response, model_to_use

    except Exception as e:
        # Se der erro de cota no 2.5, tentamos forçar o 1.5 manual como última chance
        if "429" in str(e):
             model = genai.GenerativeModel("gemini-1.5-flash")
             return model.generate_content(prompt), "gemini-1.5-flash (Forçado)"
        raise e

conn = st.connection("supabase", type=SupabaseConnection)

# --- INTERFACE ---
st.sidebar.title("🛡️ Guardian Ultra")
menu = st.sidebar.radio("Navegação", ["📊 Dashboard", "🤖 Importar Carteira", "📉 Gestão de Passivo"])

if menu == "🤖 Importar Carteira":
    st.subheader("📥 Carga Automática com Radar de Modelos")
    uploaded_file = st.file_uploader("Suba o Excel ou PDF", type=['xlsx', 'pdf'])

    if uploaded_file:
        if st.button("🚀 Iniciar Processamento IA"):
            with st.spinner("IA rastreando modelo estável e analisando..."):
                try:
                    df = pd.read_excel(uploaded_file) if uploaded_file.name.endswith('.xlsx') else pd.read_csv(uploaded_file)
                    contexto = df.dropna(how='all').head(300).to_string()
                    
                    prompt = f"""
                    Aja como Analista de Fundos. Extraia para JSON:
                    {{ 
                      "nome_fundo": "NOME_COMPLETO",
                      "ativos": [{{ "ativo": "NOME", "valor_mercado": 0.0, "tipo_ativo": "TIPO" }}], 
                      "despesas": [{{ "item": "NOME", "valor": 0.0 }}], 
                      "resumo": {{ "pl": 0.0, "cota": 0.0 }} 
                    }}
                    DADOS: {contexto}
                    """
                    
                    response, motor = extrair_com_ia_radar(prompt)
                    raw_text = response.text
                    data = json.loads(raw_text[raw_text.find('{'):raw_text.rfind('}')+1])
                    
                    st.session_state['import_data'] = data
                    st.success(f"✅ Sucesso via **{motor}**!")
                    
                    st.metric("Fundo Detectado", data['nome_fundo'])
                    c1, c2 = st.columns(2)
                    c1.metric("PL", format_br(data['resumo']['pl']))
                    c2.metric("Cota", f"R$ {data['resumo']['cota']:.6f}")
                    
                    st.table(pd.DataFrame(data['ativos']).assign(valor_mercado=lambda x: x['valor_mercado'].apply(format_br)))

                except Exception as e:
                    st.error(f"Erro no Radar IA: {e}")

    if 'import_data' in st.session_state:
        if st.button("💾 Gravar no Supabase"):
            data = st.session_state['import_data']
            fundo = data['nome_fundo']
            for a in data['ativos']: a['fundo_nome'] = fundo
            despesas = [{"fundo_nome": fundo, "item": d['item'], "valor": -abs(d['valor'])} for d in data['despesas']]
            
            conn.table("carteira_diaria").insert(data['ativos']).execute()
            conn.table("despesas_diarias").insert(despesas).execute()
            st.success("Tudo salvo!")
            st.balloons()
            del st.session_state['import_data']
