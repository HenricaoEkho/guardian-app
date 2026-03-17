import streamlit as st
import pandas as pd
from st_supabase_connection import SupabaseConnection
import google.generativeai as genai
import json

# --- CONFIGURAÇÃO ---
st.set_page_config(page_title="Guardian Pro Ultra 6.4", layout="wide", page_icon="🛡️")

def format_br(valor):
    try:
        val = float(valor)
        return f"R$ {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except: return str(valor)

# --- CONEXÃO IA ---
gemini_key = st.secrets.get("GEMINI_API_KEY")
if gemini_key:
    genai.configure(api_key=gemini_key)

# Função "Tanque": Tenta o melhor, se der qualquer erro, pula pro 1.5 estável
def extrair_com_ia_blindada(prompt):
    # Tentativa 1: O 2.5 (Elite - 20/dia)
    try:
        model_elite = genai.GenerativeModel('gemini-2.5-flash')
        return model_elite.generate_content(prompt), "Gemini 2.5 Flash (Elite)"
    except Exception:
        # Tentativa 2: O 1.5 (Reserva - 1500/dia) - Usando nome completo estável
        try:
            model_reserva = genai.GenerativeModel('gemini-1.5-flash')
            return model_reserva.generate_content(prompt), "Gemini 1.5 Flash (Tanque de Guerra)"
        except Exception as e2:
            raise Exception(f"Ambos os modelos falharam. Erro final: {e2}")

conn = st.connection("supabase", type=SupabaseConnection)

# --- SIDEBAR ---
st.sidebar.title("🛡️ Guardian Ultra")
menu = st.sidebar.radio("Navegação", ["📊 Dashboard", "🤖 Importar Carteira", "📉 Gestão de Passivo", "📜 Regras"])

# --- 1. IMPORTAÇÃO ---
if menu == "🤖 Importar Carteira":
    st.subheader("📥 Carga Automática Blindada")
    st.info("O sistema tentará o 2.5, mas se ele estiver cansado (quota), o 1.5 assume na hora.")
    
    uploaded_file = st.file_uploader("Suba o Excel ou PDF", type=['xlsx', 'pdf'])

    if uploaded_file:
        if st.button("🚀 Iniciar Processamento IA"):
            with st.spinner("IA analisando dados..."):
                try:
                    df = pd.read_excel(uploaded_file) if uploaded_file.name.endswith('.xlsx') else pd.read_csv(uploaded_file)
                    contexto = df.dropna(how='all').head(250).to_string()
                    
                    prompt = f"""
                    Aja como um analista de fundos. Extraia estes dados do relatório:
                    - NOME_FUNDO: Nome completo.
                    - ATIVOS: Lista com 'ativo', 'valor_mercado' e 'tipo_ativo' (Diferencie Debênture Incentivada).
                    - DESPESAS: Lista com 'item' e 'valor'.
                    - RESUMO: 'pl' e 'cota'.
                    
                    Retorne APENAS um JSON puro:
                    {{ 
                      "nome_fundo": "NOME",
                      "ativos": [{{ "ativo": "NOME", "valor_mercado": 0.0, "tipo_ativo": "TIPO" }}], 
                      "despesas": [{{ "item": "NOME", "valor": 0.0 }}], 
                      "resumo": {{ "pl": 0.0, "cota": 0.0 }} 
                    }}
                    DADOS: {contexto}
                    """
                    
                    response, motor = extrair_com_ia_blindada(prompt)
                    raw_text = response.text
                    
                    # Limpeza de texto para evitar que a IA mande ```json ... ```
                    data = json.loads(raw_text[raw_text.find('{'):raw_text.rfind('}')+1])
                    
                    st.session_state['import_data'] = data
                    st.success(f"✅ Processado via **{motor}**!")
                    st.write(f"📌 Fundo Identificado: **{data['nome_fundo']}**")
                    
                    c1, c2 = st.columns(2)
                    c1.metric("PL", format_br(data['resumo']['pl']))
                    c2.metric("Cota", f"R$ {data['resumo']['cota']:.6f}")
                    
                    with st.expander("Ver Ativos Identificados"):
                        st.table(pd.DataFrame(data['ativos']))

                except Exception as e:
                    st.error(f"Erro no processamento: {e}")

    if 'import_data' in st.session_state:
        if st.button("💾 Gravar no Supabase"):
            data = st.session_state['import_data']
            fundo = data['nome_fundo']
            
            # Prepara dados
            for a in data['ativos']: a['fundo_nome'] = fundo
            despesas = [{"fundo_nome": fundo, "item": d['item'], "valor": -abs(d['valor'])} for d in data['despesas']]
            
            conn.table("carteira_diaria").insert(data['ativos']).execute()
            conn.table("despesas_diarias").insert(despesas).execute()
            st.success(f"Dados de {fundo} integrados!")
            st.balloons()
            del st.session_state['import_data']

# --- DASHBOARD ---
elif menu == "📊 Dashboard":
    st.info("Aqui aparecerá a análise de enquadramento.")
