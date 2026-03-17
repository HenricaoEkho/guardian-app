import streamlit as st
import pandas as pd
from st_supabase_connection import SupabaseConnection
import google.generativeai as genai
import json

# --- CONFIGURAÇÃO E ESTILO ---
st.set_page_config(page_title="Guardian Pro v6", layout="wide", page_icon="🛡️")

def format_br(valor):
    try:
        val = float(valor)
        return f"R$ {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except: return str(valor)

# --- CONEXÕES ---
gemini_key = st.secrets.get("GEMINI_API_KEY")
if gemini_key:
    genai.configure(api_key=gemini_key)
    # Mudando para o 1.5-flash que tem limites melhores que o 2.5 experimental
    model = genai.GenerativeModel('gemini-1.5-flash')

conn = st.connection("supabase", type=SupabaseConnection)

# --- SIDEBAR ---
st.sidebar.title("🛡️ Guardian v6")
menu = st.sidebar.radio("Navegação", ["📊 Dashboard", "🤖 Importar Carteira", "📉 Gestão de Passivo", "📜 Regras"])

# --- 1. IMPORTAR CARTEIRA (AUTO-DETECT) ---
if menu == "🤖 Importar Carteira":
    st.subheader("📥 Carga de Dados Inteligente")
    st.info("A IA identificará o Fundo, Ativos e Despesas automaticamente.")
    
    uploaded_file = st.file_uploader("Suba o Excel ou PDF", type=['xlsx', 'pdf'])

    if uploaded_file:
        if st.button("🚀 Iniciar Análise IA"):
            with st.spinner("O Analista IA está processando..."):
                try:
                    df = pd.read_excel(uploaded_file) if uploaded_file.name.endswith('.xlsx') else pd.read_csv(uploaded_file)
                    contexto = df.dropna(how='all').head(250).to_string()
                    
                    prompt = f"""
                    Aja como Senior de Compliance. Extraia do relatório:
                    1. NOME_FUNDO: Nome completo do fundo no cabeçalho.
                    2. ATIVOS: Diferencie 'Debênture Incentivada' de 'Debênture Comum'.
                    3. DESPESAS: Todos os custos (sempre positivos no JSON).
                    4. RESUMO: PL e Cota.
                    
                    JSON: {{ 
                      "nome_fundo": "NOME",
                      "ativos": [{{ "ativo": "NOME", "valor_mercado": 0.0, "tipo_ativo": "TIPO" }}], 
                      "despesas": [{{ "item": "NOME", "valor": 0.0 }}], 
                      "resumo": {{ "pl": 0.0, "cota": 0.0 }} 
                    }}
                    DADOS: {contexto}
                    """
                    
                    response = model.generate_content(prompt)
                    data = json.loads(response.text[response.text.find('{'):response.text.rfind('}')+1])
                    
                    st.session_state['data_last_import'] = data
                    st.success(f"📌 Fundo Identificado: **{data['nome_fundo']}**")
                    
                    c1, c2 = st.columns(2)
                    c1.metric("PL", format_br(data['resumo']['pl']))
                    c2.metric("Cota", f"R$ {data['resumo']['cota']:.6f}")
                    
                    t1, t2 = st.tabs(["Ativos", "Despesas"])
                    with t1: st.table(pd.DataFrame(data['ativos']))
                    with t2: st.table(pd.DataFrame(data['despesas']))

                except Exception as e:
                    st.error(f"Erro na IA: {e}")

        if 'data_last_import' in st.session_state:
            if st.button("💾 Gravar no Supabase"):
                data = st.session_state['data_last_import']
                fundo = data['nome_fundo']
                
                # Prepara dados com a etiqueta do fundo
                for a in data['ativos']: a['fundo_nome'] = fundo
                desp_final = [{"fundo_nome": fundo, "item": d['item'], "valor": -abs(d['valor'])} for d in data['despesas']]
                
                conn.table("carteira_diaria").insert(data['ativos']).execute()
                conn.table("despesas_diarias").insert(desp_final).execute()
                st.success(f"Dados de {fundo} integrados!")

# --- 2. DASHBOARD ---
elif menu == "📊 Dashboard":
    try:
        res = conn.table("carteira_diaria").select("fundo_nome").execute()
        fundos = list(set([i['fundo_nome'] for i in res.data])) if res.data else []
        fundo_sel = st.sidebar.selectbox("Selecionar Fundo:", fundos)
        
        if fundo_sel:
            st.subheader(f"📊 Dashboard: {fundo_sel}")
            c = conn.table("carteira_diaria").select("*").eq("fundo_nome", fundo_sel).execute()
            df_c = pd.DataFrame(c.data)
            st.metric("PL Total", format_br(df_c['valor_mercado'].sum()))
            st.dataframe(df_c, use_container_width=True)
    except:
        st.info("Aguardando primeira importação...")

# --- 3. PASSIVO ---
elif menu == "📉 Gestão de Passivo":
    st.subheader("📉 Registro de Resgates/Aportes")
    # Busca fundos para o selectbox
    res = conn.table("carteira_diaria").select("fundo_nome").execute()
    fundos = list(set([i['fundo_nome'] for i in res.data])) if res.data else ["Nenhum Fundo"]
    f_p = st.selectbox("Fundo:", fundos)
    tipo = st.selectbox("Tipo", ["Resgate", "Aporte"])
    val = st.number_input("Valor", min_value=0.0)
    if st.button("Registrar"):
        conn.table("movimentacoes_passivo").insert({"fundo_nome": f_p, "tipo": tipo, "valor": val}).execute()
        st.success("Movimentação registrada!")
