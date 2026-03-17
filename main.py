import streamlit as st
import pandas as pd
from st_supabase_connection import SupabaseConnection
import google.generativeai as genai
import json

# --- CONFIGURAÇÃO ---
st.set_page_config(page_title="Guardian Ultra 6.3", layout="wide", page_icon="🛡️")

def format_br(valor):
    try:
        val = float(valor)
        return f"R$ {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except: return str(valor)

# --- CONEXÃO IA DINÂMICA ---
gemini_key = st.secrets.get("GEMINI_API_KEY")
if gemini_key:
    genai.configure(api_key=gemini_key)

# Função "Detetive": Encontra o melhor modelo disponível na hora
def extrair_com_ia_dinamica(prompt):
    try:
        # 1. Tenta o 2.5 primeiro (nosso favorito)
        m25 = genai.GenerativeModel('models/gemini-2.5-flash')
        return m25.generate_content(prompt), "Gemini 2.5 Flash (Elite)"
    except Exception as e:
        if "429" in str(e) or "404" in str(e):
            # 2. Se falhar, busca na lista oficial do Google o que está ativo
            modelos_disponiveis = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
            
            # Filtra para achar qualquer versão do 1.5 Flash (que tem cota alta)
            reserva = [m for m in modelos_disponiveis if "1.5-flash" in m]
            
            if reserva:
                modelo_final = genai.GenerativeModel(reserva[0])
                return modelo_final.generate_content(prompt), f"Reserva Ativada: {reserva[0]}"
            else:
                # Se não achar o 1.5, pega o primeiro que aparecer (pro, etc)
                modelo_final = genai.GenerativeModel(modelos_disponiveis[0])
                return modelo_final.generate_content(prompt), f"Modo Sobrevivência: {modelos_disponiveis[0]}"
        raise e

conn = st.connection("supabase", type=SupabaseConnection)

# --- SIDEBAR ---
st.sidebar.title("🛡️ Guardian Ultra")
menu = st.sidebar.radio("Navegação", ["📊 Dashboard", "🤖 Importar Carteira", "📉 Gestão de Passivo", "📜 Regras"])

# --- 1. IMPORTAÇÃO ---
if menu == "🤖 Importar Carteira":
    st.subheader("📥 Carga Automática com Busca de Modelo")
    uploaded_file = st.file_uploader("Suba o Excel ou PDF", type=['xlsx', 'pdf'])

    if uploaded_file:
        if st.button("🚀 Iniciar Processamento IA"):
            with st.spinner("Buscando modelo ativo e analisando..."):
                try:
                    df = pd.read_excel(uploaded_file) if uploaded_file.name.endswith('.xlsx') else pd.read_csv(uploaded_file)
                    contexto = df.dropna(how='all').head(250).to_string()
                    
                    prompt = f"""
                    Extraia em JSON puro:
                    {{ 
                      "nome_fundo": "NOME_DO_FUNDO",
                      "ativos": [{{ "ativo": "NOME", "valor_mercado": 0.0, "tipo_ativo": "TIPO" }}], 
                      "despesas": [{{ "item": "NOME", "valor": 0.0 }}], 
                      "resumo": {{ "pl": 0.0, "cota": 0.0 }} 
                    }}
                    DADOS: {contexto}
                    """
                    
                    response, motor = extrair_com_ia_dinamica(prompt)
                    data = json.loads(response.text[response.text.find('{'):response.text.rfind('}')+1])
                    
                    st.session_state['import_data'] = data
                    st.success(f"✅ Sucesso via **{motor}**!")
                    st.write(f"📌 Fundo: **{data['nome_fundo']}**")
                    
                    # Exibição
                    c1, c2 = st.columns(2)
                    c1.metric("PL", format_br(data['resumo']['pl']))
                    c2.metric("Cota", f"R$ {data['resumo']['cota']:.6f}")
                    st.table(pd.DataFrame(data['ativos']))

                except Exception as e:
                    st.error(f"Erro Crítico: {e}")

    if 'import_data' in st.session_state:
        if st.button("💾 Gravar no Supabase"):
            data = st.session_state['import_data']
            fundo = data['nome_fundo']
            for a in data['ativos']: a['fundo_nome'] = fundo
            desp = [{"fundo_nome": fundo, "item": d['item'], "valor": -abs(d['valor'])} for d in data['despesas']]
            
            conn.table("carteira_diaria").insert(data['ativos']).execute()
            conn.table("despesas_diarias").insert(desp).execute()
            st.success(f"Dados salvos!")
            del st.session_state['import_data']

# --- DASHBOARD ---
elif menu == "📊 Dashboard":
    st.info("O Dashboard será alimentado assim que você salvar a primeira carteira.")
