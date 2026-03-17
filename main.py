import streamlit as st
import pandas as pd
from st_supabase_connection import SupabaseConnection
import google.generativeai as genai
import json

# --- CONFIGURAÇÃO E ESTILO BR ---
st.set_page_config(page_title="Guardian Pro", layout="wide", page_icon="🛡️")

def format_br(valor):
    try:
        return f"R$ {float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except: return str(valor)

# --- CONEXÕES ---
gemini_key = st.secrets.get("GEMINI_API_KEY")
genai.configure(api_key=gemini_key)
model = genai.GenerativeModel('models/gemini-2.5-flash')
conn = st.connection("supabase", type=SupabaseConnection)

# --- SIDEBAR: GESTÃO DE FUNDOS ---
st.sidebar.title("🛡️ Guardian v5")
fundo_selecionado = st.sidebar.text_input("Fundo Ativo:", value="Fundo Zambs")
menu = st.sidebar.radio("Navegação", ["📊 Dashboard", "🤖 Importar Carteira", "📉 Gestão de Passivo", "📜 Regras"])

# --- 1. IMPORTAR CARTEIRA ---
if menu == "🤖 Importar Carteira":
    st.subheader(f"📥 Importar Dados: {fundo_selecionado}")
    uploaded_file = st.file_uploader("Excel ou PDF", type=['xlsx', 'pdf'])

    if uploaded_file:
        with st.spinner("IA Analisando ativos e despesas..."):
            try:
                df = pd.read_excel(uploaded_file) if uploaded_file.name.endswith('.xlsx') else pd.read_csv(uploaded_file)
                contexto = df.dropna(how='all').head(250).to_string()
                
                prompt = f"""
                Analista de Backoffice: Extraia dados para o fundo {fundo_selecionado}.
                REGRAS: 
                - Identifique Ativos (seja específico com 'Debênture Incentivada').
                - Identifique Despesas (Taxas, custódia, etc).
                JSON: {{ "ativos": [{{ "ativo": "NOME", "valor_mercado": 0.0, "tipo_ativo": "TIPO" }}], "despesas": [{{ "item": "NOME", "valor": 0.0 }}], "resumo": {{ "pl": 0.0, "cota": 0.0 }} }}
                DADOS: {contexto}
                """
                
                response = model.generate_content(prompt)
                data = json.loads(response.text[response.text.find('{'):response.text.rfind('}')+1])
                
                # Visualização na tela
                st.metric("PL Identificado", format_br(data['resumo']['pl']))
                
                t1, t2 = st.tabs(["Ativos", "Despesas"])
                with t1:
                    df_a = pd.DataFrame(data['ativos'])
                    st.table(df_a.assign(valor_mercado=df_a['valor_mercado'].apply(format_br)))
                with t2:
                    df_d = pd.DataFrame(data['despesas'])
                    st.table(df_d.assign(valor=df_d['valor'].apply(format_br)))

                if st.button("Salvar no Supabase"):
                    # Adiciona a "etiqueta" do fundo em cada linha antes de salvar
                    for a in data['ativos']: a['fundo_nome'] = fundo_selecionado
                    for d in data['despesas']: 
                        d['fundo_nome'] = fundo_selecionado
                        d['valor'] = -abs(d['valor']) # Força negativo no banco
                    
                    conn.table("carteira_diaria").insert(data['ativos']).execute()
                    conn.table("despesas_diarias").insert(data['despesas']).execute()
                    st.success(f"Dados salvos para {fundo_selecionado}!")
                    st.balloons()
            except Exception as e:
                st.error(f"Erro: {e}")

# --- 2. DASHBOARD COM LOGICA DE ENQUADRAMENTO ---
elif menu == "📊 Dashboard":
    st.subheader(f"📊 Painel de Controle: {fundo_selecionado}")
    
    # Filtra tudo pelo nome do fundo!
    c = conn.table("carteira_diaria").select("*").eq("fundo_nome", fundo_selecionado).execute()
    d = conn.table("despesas_diarias").select("*").eq("fundo_nome", fundo_selecionado).execute()
    p = conn.table("movimentacoes_passivo").select("*").eq("fundo_nome", fundo_selecionado).execute()

    if c.data:
        df_c = pd.DataFrame(c.data)
        pl_total = df_c['valor_mercado'].sum()
        total_desp = sum(item['valor'] for item in d.data)
        total_resgates = sum(item['valor'] for item in p.data if item['tipo'] == 'Resgate')
        
        pl_projetado = pl_total - total_resgates
        perc_inc = (df_c[df_c['tipo_ativo'] == 'Debênture Incentivada']['valor_mercado'].sum() / pl_total) * 100
        
        col1, col2, col3 = st.columns(3)
        col1.metric("PL Atual", format_br(pl_total))
        col2.metric("Total Despesas", format_br(total_desp), delta_color="inverse")
        col3.metric("% Incentivadas", f"{perc_inc:.2f}%")

        st.divider()
        st.write("### PL Projetado (Pós-Resgate)")
        perc_projetado = (df_c[df_c['tipo_ativo'] == 'Debênture Incentivada']['valor_mercado'].sum() / pl_projetado) * 100
        st.metric("PL Pós-Passivo", format_br(pl_projetado), delta=f"{perc_projetado:.2f}% Enquadramento")

# --- 3. GESTÃO DE PASSIVO ---
elif menu == "📉 Gestão de Passivo":
    st.subheader(f"Movimentação de Cotistas: {fundo_selecionado}")
    tipo = st.selectbox("Operação", ["Resgate", "Aporte"])
    val = st.number_input("Valor")
    data_l = st.date_input("Liquidação")
    if st.button("Registrar"):
        conn.table("movimentacoes_passivo").insert({"fundo_nome": fundo_selecionado, "tipo": tipo, "valor": val, "data_liquidacao": str(data_l)}).execute()
        st.success("Registrado!")
