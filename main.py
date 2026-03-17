import streamlit as st
import pandas as pd
from st_supabase_connection import SupabaseConnection
import google.generativeai as genai
import json

# --- CONFIGURAÇÃO E FORMATAÇÃO ---
st.set_page_config(page_title="Guardian Hydra v8", layout="wide", page_icon="🛡️")

def format_br(valor):
    try:
        val = float(valor)
        return f"R$ {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except: return str(valor)

# --- CONEXÃO E LISTA HÍBRIDA (SÓ OS QUE VOCÊ VALIDOU) ---
gemini_key = st.secrets.get("GEMINI_API_KEY")
if gemini_key:
    genai.configure(api_key=gemini_key)

# Lista de modelos por ordem de "QI" e Estabilidade que você testou
MODELOS_PRIORIDADE = [
    'models/gemini-3.1-flash-lite-preview', # O que você achou melhorzinho
    'models/gemini-2.5-flash-lite',
    'models/gemini-3-flash-preview',
    'models/gemini-robotics-er-1.5-preview',
    'models/gemini-flash-latest',
    'models/gemma-3-27b-it',
    'models/gemini-flash-lite-latest'
]

def extrair_com_protocolo_hydra(prompt):
    tentativas_log = []
    for model_name in MODELOS_PRIORIDADE:
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt)
            # Se chegou aqui, funcionou!
            return response, model_name
        except Exception as e:
            tentativas_log.append(f"❌ {model_name}: {str(e)[:50]}...")
            continue
    
    raise Exception(f"Todos os modelos falharam ou estão sem cota. Logs: {tentativas_log}")

conn = st.connection("supabase", type=SupabaseConnection)

# --- INTERFACE ---
st.sidebar.title("🛡️ Guardian Hydra")
menu = st.sidebar.radio("Navegação", ["📊 Dashboard", "🤖 Importar Carteira", "📉 Gestão de Passivo", "📜 Regulamento"])

if menu == "🤖 Importar Carteira":
    st.subheader("📥 Carga de Dados Inteligente (Híbrida)")
    uploaded_file = st.file_uploader("Suba o Excel ou PDF", type=['xlsx', 'pdf'])

    if uploaded_file:
        if st.button("🚀 Iniciar Processamento Hydra"):
            with st.spinner("IA Híbrida em ação..."):
                try:
                    df = pd.read_excel(uploaded_file) if uploaded_file.name.endswith('.xlsx') else pd.read_csv(uploaded_file)
                    contexto = df.dropna(how='all').head(300).to_string()
                    
                    # O PROMPT COMPLETO ESTÁ DE VOLTA!
                    prompt = f"""
                    Você é um Especialista de Compliance de Fundos no Brasil. 
                    Analise os dados e extraia com precisão máxima:
                    
                    1. NOME_FUNDO: Nome completo do fundo.
                    2. ATIVOS: Identifique detalhadamente. Se for debênture, diferencie se é 'Debênture Incentivada' (Lei 12.431) ou 'Debênture Comum'.
                    3. DESPESAS: Taxas, impostos, custódia.
                    4. RESUMO: Patrimônio Líquido (PL) e Valor da Cota.

                    REGRAS DE VALORES: Use ponto para decimal (Ex: 1234.56).
                    
                    JSON: {{ 
                      "nome_fundo": "NOME",
                      "ativos": [{{ "ativo": "NOME", "valor_mercado": 0.0, "tipo_ativo": "TIPO" }}], 
                      "despesas": [{{ "item": "NOME", "valor": 0.0 }}], 
                      "resumo": {{ "pl": 0.0, "cota": 0.0 }} 
                    }}
                    DADOS: {contexto}
                    """
                    
                    response, motor_vencedor = extrair_com_protocolo_hydra(prompt)
                    raw_text = response.text
                    data = json.loads(raw_text[raw_text.find('{'):raw_text.rfind('}')+1])
                    
                    st.session_state['data_import'] = data
                    st.success(f"🔥 Sucesso via: **{motor_vencedor}**")
                    st.write(f"📌 Fundo: **{data['nome_fundo']}**")
                    
                    c1, c2 = st.columns(2)
                    c1.metric("PL", format_br(data['resumo']['pl']))
                    c2.metric("Cota", f"R$ {data['resumo']['cota']:.6f}")
                    
                    t1, t2 = st.tabs(["📄 Ativos", "💸 Despesas"])
                    with t1:
                        df_a = pd.DataFrame(data['ativos'])
                        st.table(df_a.assign(valor_mercado=df_a['valor_mercado'].apply(format_br)))
                    with t2:
                        st.table(pd.DataFrame(data['despesas']))

                except Exception as e:
                    st.error(f"Falha total no sistema: {e}")

    if 'data_import' in st.session_state:
        if st.button("💾 Gravar no Supabase"):
            data = st.session_state['data_import']
            fundo = data['nome_fundo']
            
            # Preparando ativos e despesas com a etiqueta do fundo
            for a in data['ativos']: a['fundo_nome'] = fundo
            desp_final = [{"fundo_nome": fundo, "item": d['item'], "valor": -abs(d['valor'])} for d in data['despesas']]
            
            conn.table("carteira_diaria").insert(data['ativos']).execute()
            conn.table("despesas_diarias").insert(desp_final).execute()
            
            st.success(f"Dados de {fundo} integrados com sucesso!")
            st.balloons()
            del st.session_state['data_import']

# --- DASHBOARD ---
elif menu == "📊 Dashboard":
    st.info("Selecione um fundo na barra lateral para ver o enquadramento projetado.")
