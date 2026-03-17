import streamlit as st
import pandas as pd
from st_supabase_connection import SupabaseConnection
import google.generativeai as genai
import json

# --- CONFIGURAÇÃO E ESTILO ---
st.set_page_config(page_title="Guardian Pro v6.1", layout="wide", page_icon="🛡️")

def format_br(valor):
    try:
        val = float(valor)
        return f"R$ {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except: return str(valor)

# --- CONEXÕES ---
gemini_key = st.secrets.get("GEMINI_API_KEY")
if gemini_key:
    genai.configure(api_key=gemini_key)
    # VOLTANDO PARA O MODELO QUE FUNCIONOU NO SEU AMBIENTE:
    model = genai.GenerativeModel('models/gemini-2.5-flash')

conn = st.connection("supabase", type=SupabaseConnection)

# --- SIDEBAR ---
st.sidebar.title("🛡️ Guardian v6.1")
menu = st.sidebar.radio("Navegação", ["📊 Dashboard", "🤖 Importar Carteira", "📉 Gestão de Passivo", "📜 Regras"])

# --- 1. IMPORTAR CARTEIRA (AUTO-DETECT NOME DO FUNDO) ---
if menu == "🤖 Importar Carteira":
    st.subheader("📥 Carga de Dados Automática")
    st.info("A IA identificará o Fundo, Ativos e Despesas sozinha.")
    
    uploaded_file = st.file_uploader("Suba o Excel ou PDF", type=['xlsx', 'pdf'])

    if uploaded_file:
        # Colocamos o botão para você não gastar sua quota de 20/dia sem querer
        if st.button("🚀 Iniciar Análise IA"):
            with st.spinner("IA Analisando (Modelo 2.5 Flash)..."):
                try:
                    df = pd.read_excel(uploaded_file) if uploaded_file.name.endswith('.xlsx') else pd.read_csv(uploaded_file)
                    # Lemos o topo do arquivo para a IA achar o nome do fundo
                    contexto = df.dropna(how='all').head(250).to_string()
                    
                    prompt = f"""
                    Aja como Senior de Backoffice. Extraia do relatório:
                    1. NOME_FUNDO: Nome completo do fundo que aparece no cabeçalho ou título.
                    2. ATIVOS: Identifique detalhadamente. Se for debênture, verifique se é 'Incentivada' (Lei 12.431).
                    3. DESPESAS: Todos os custos (Sempre positivos no JSON).
                    4. RESUMO: Patrimônio Líquido (PL) e Valor da Cota.
                    
                    JSON: {{ 
                      "nome_fundo": "NOME_DO_FUNDO_AQUI",
                      "ativos": [{{ "ativo": "NOME", "valor_mercado": 0.0, "tipo_ativo": "TIPO" }}], 
                      "despesas": [{{ "item": "NOME", "valor": 0.0 }}], 
                      "resumo": {{ "pl": 0.0, "cota": 0.0 }} 
                    }}
                    DADOS: {contexto}
                    """
                    
                    response = model.generate_content(prompt)
                    data = json.loads(response.text[response.text.find('{'):response.text.rfind('}')+1])
                    
                    # Salva temporariamente na memória do navegador para você poder conferir antes de salvar no banco
                    st.session_state['last_data'] = data
                    
                    st.success(f"📌 Fundo Detectado: **{data['nome_fundo']}**")
                    
                    c1, c2 = st.columns(2)
                    c1.metric("PL Identificado", format_br(data['resumo']['pl']))
                    c2.metric("Cota", f"R$ {data['resumo']['cota']:.6f}")
                    
                    t1, t2 = st.tabs(["Ativos", "Despesas"])
                    with t1:
                        df_ativos = pd.DataFrame(data['ativos'])
                        st.table(df_ativos.assign(valor_mercado=df_ativos['valor_mercado'].apply(format_br)))
                    with t2:
                        st.table(pd.DataFrame(data['despesas']))

                except Exception as e:
                    st.error(f"Erro no processamento IA: {e}")

        # Se a IA já rodou e os dados estão na memória, mostramos o botão de salvar
        if 'last_data' in st.session_state:
            if st.button("💾 Confirmar e Gravar no Supabase"):
                try:
                    data = st.session_state['last_data']
                    fundo = data['nome_fundo']
                    
                    # Prepara os dados com a etiqueta do fundo e formatação de despesa
                    for a in data['ativos']: a['fundo_nome'] = fundo
                    desp_final = [{"fundo_nome": fundo, "item": d['item'], "valor": -abs(d['valor'])} for d in data['despesas']]
                    
                    # Envia para o banco
                    conn.table("carteira_diaria").insert(data['ativos']).execute()
                    conn.table("despesas_diarias").insert(desp_final).execute()
                    
                    st.success(f"Show! Dados do fundo '{fundo}' integrados com sucesso.")
                    st.balloons()
                    del st.session_state['last_data'] # Limpa a memória após salvar
                except Exception as e:
                    st.error(f"Erro ao salvar no banco (Verifique o RLS no Supabase): {e}")

# --- 2. DASHBOARD ---
elif menu == "📊 Dashboard":
    try:
        # Busca a lista de fundos que já existem no banco para o filtro
        res = conn.table("carteira_diaria").select("fundo_nome").execute()
        fundos = list(set([i['fundo_nome'] for i in res.data])) if res.data else []
        
        fundo_sel = st.sidebar.selectbox("Selecionar Fundo:", fundos if fundos else ["Nenhum cadastrado"])
        
        if fundo_sel != "Nenhum cadastrado":
            st.subheader(f"📊 Painel: {fundo_sel}")
            c = conn.table("carteira_diaria").select("*").eq("fundo_nome", fundo_sel).execute()
            df_c = pd.DataFrame(c.data)
            
            st.metric("PL Total Consolidado", format_br(df_c['valor_mercado'].sum()))
            st.dataframe(df_c, use_container_width=True)
    except Exception as e:
        st.info("Aguardando a primeira carga de dados.")

# --- 3. PASSIVO ---
elif menu == "📉 Gestão de Passivo":
    st.subheader("📉 Registro de Resgates")
    st.info("Aqui você cadastra as saídas de cotistas para simular o enquadramento futuro.")
