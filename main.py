import streamlit as st
import pandas as pd
from st_supabase_connection import SupabaseConnection
import google.generativeai as genai
import json

# --- CONFIGURAÇÃO E ESTILO ---
st.set_page_config(page_title="Guardian Hydra v8.1", layout="wide", page_icon="🛡️")

# Função de Formatação BR Turbinada
def format_br(valor, prefixo="R$ "):
    try:
        val = float(valor)
        # Formata com separador de milhar (.) e decimal (,)
        return f"{prefixo}{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except:
        return str(valor)

# --- CONEXÃO IA HÍBRIDA ---
gemini_key = st.secrets.get("GEMINI_API_KEY")
if gemini_key:
    genai.configure(api_key=gemini_key)

MODELOS_PRIORIDADE = [
    'models/gemini-3.1-flash-lite-preview',
    'models/gemini-2.5-flash-lite',
    'models/gemini-3-flash-preview',
    'models/gemini-1.5-flash'
]

def extrair_com_protocolo_hydra(prompt):
    for model_name in MODELOS_PRIORIDADE:
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt)
            return response, model_name
        except:
            continue
    raise Exception("Todos os modelos de IA falharam.")

conn = st.connection("supabase", type=SupabaseConnection)

# --- INTERFACE ---
st.sidebar.title("🛡️ Guardian Hydra")
menu = st.sidebar.radio("Navegação", ["📊 Dashboard", "🤖 Importar Carteira", "📉 Gestão de Passivo", "📜 Regulamento"])

if menu == "🤖 Importar Carteira":
    st.subheader("📥 Carga de Dados Inteligente")
    uploaded_file = st.file_uploader("Suba o Excel ou PDF", type=['xlsx', 'pdf'])

    if uploaded_file:
        if st.button("🚀 Iniciar Processamento Hydra"):
            with st.spinner("IA Processando..."):
                try:
                    df = pd.read_excel(uploaded_file) if uploaded_file.name.endswith('.xlsx') else pd.read_csv(uploaded_file)
                    contexto = df.dropna(how='all').head(300).to_string()
                    
                    prompt = f"""
                    Analista de Compliance: Extraia do relatório:
                    1. NOME_FUNDO, PL, COTA.
                    2. ATIVOS: Lista [{{ativo, valor_mercado, tipo_ativo}}]. 
                       Diferencie 'Debênture Incentivada' se houver.
                    3. DESPESAS: Lista [{{item, valor}}].

                    Retorne APENAS JSON puro:
                    {{ 
                      "nome_fundo": "NOME",
                      "resumo": {{ "pl": 0.0, "cota": 0.0 }},
                      "ativos": [], "despesas": [] 
                    }}
                    DADOS: {contexto}
                    """
                    
                    response, motor = extrair_com_protocolo_hydra(prompt)
                    data = json.loads(response.text[response.text.find('{'):response.text.rfind('}')+1])
                    
                    # --- TRATAMENTO DOS DADOS ---
                    # 1. Garante que despesas sejam negativas e calcula o total
                    total_desp = 0
                    for d in data['despesas']:
                        d['valor'] = -abs(float(d['valor']))
                        total_desp += d['valor']
                    data['resumo']['total_despesas'] = total_desp
                    
                    st.session_state['data_import'] = data
                    st.success(f"🔥 Processado via: {motor}")
                    st.write(f"📌 Fundo: **{data['nome_fundo']}**")
                    
                    # --- MÉTRICAS NO TOPO ---
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Patrimônio Líquido", format_br(data['resumo']['pl']))
                    c2.metric("Valor da Cota", f"R$ {data['resumo']['cota']:.6f}")
                    c3.metric("Total Despesas (Dia)", format_br(data['resumo']['total_despesas']), delta_color="inverse")
                    
                    # --- TABELAS FORMATADAS BR ---
                    t1, t2 = st.tabs(["📄 Ativos", "💸 Despesas"])
                    with t1:
                        df_a = pd.DataFrame(data['ativos'])
                        st.table(df_a.assign(valor_mercado=df_a['valor_mercado'].apply(lambda x: format_br(x))))
                    with t2:
                        df_d = pd.DataFrame(data['despesas'])
                        st.table(df_d.assign(valor=df_d['valor'].apply(lambda x: format_br(x))))

                except Exception as e:
                    st.error(f"Erro: {e}")

    if 'data_import' in st.session_state:
        if st.button("💾 Gravar no Supabase"):
            data = st.session_state['data_import']
            fundo = data['nome_fundo']
            
            # Adiciona fundo_nome antes de salvar
            for a in data['ativos']: a['fundo_nome'] = fundo
            for d in data['despesas']: d['fundo_nome'] = fundo
            
            conn.table("carteira_diaria").insert(data['ativos']).execute()
            conn.table("despesas_diarias").insert(data['despesas']).execute()
            
            st.success(f"Dados de {fundo} integrados!")
            st.balloons()
            del st.session_state['data_import']

# --- DASHBOARD ---
elif menu == "📊 Dashboard":
    st.info("O Dashboard está pronto para consolidar os dados salvos.")
