import streamlit as st
import pandas as pd
from st_supabase_connection import SupabaseConnection
import google.generativeai as genai
import json
import time

# --- CONFIGURAÇÃO E ESTILO ---
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

# --- SIDEBAR ---
st.sidebar.title("🛡️ Guardian v6")
menu = st.sidebar.radio("Navegação", ["📊 Dashboard", "🤖 Importar Carteira", "📉 Gestão de Passivo", "📜 Regras"])

# --- 1. IMPORTAR CARTEIRA (TOTALMENTE AUTOMÁTICO) ---
if menu == "🤖 Importar Carteira":
    st.subheader("📥 Carga de Dados Inteligente")
    st.info("A IA identificará automaticamente o nome do fundo, ativos e despesas.")
    
    uploaded_file = st.file_uploader("Suba o Excel ou PDF", type=['xlsx', 'pdf'])

    if uploaded_file:
        if st.button("Iniciar Análise IA"):
            with st.spinner("O Analista IA está lendo o relatório..."):
                try:
                    df = pd.read_excel(uploaded_file) if uploaded_file.name.endswith('.xlsx') else pd.read_csv(uploaded_file)
                    # Pegamos o topo do arquivo onde costuma estar o nome do fundo
                    contexto = df.dropna(how='all').head(200).to_string()
                    
                    prompt = f"""
                    Aja como um Senior de Backoffice. Analise o relatório e extraia:
                    1. NOME_FUNDO: Identifique o nome completo do fundo no cabeçalho.
                    2. ATIVOS: Identifique Ativos (seja específico com 'Debênture Incentivada').
                    3. DESPESAS: Taxas e custos (sempre positivos no JSON).
                    4. RESUMO: PL e Cota.
                    
                    JSON: {{ 
                      "nome_fundo": "NOME IDENTIFICADO",
                      "ativos": [{{ "ativo": "NOME", "valor_mercado": 0.0, "tipo_ativo": "TIPO" }}], 
                      "despesas": [{{ "item": "NOME", "valor": 0.0 }}], 
                      "resumo": {{ "pl": 0.0, "cota": 0.0 }} 
                    }}
                    DADOS: {contexto}
                    """
                    
                    response = model.generate_content(prompt)
                    data = json.loads(response.text[response.text.find('{'):response.text.rfind('}')+1])
                    
                    # Guardamos o nome identificado na sessão do Streamlit
                    st.session_state['fundo_detectado'] = data['nome_fundo']
                    
                    st.success(f"📌 Fundo Identificado: **{data['nome_fundo']}**")
                    
                    col1, col2 = st.columns(2)
                    col1.metric("PL do Relatório", format_br(data['resumo']['pl']))
                    col2.metric("Cota", f"R$ {data['resumo']['cota']:.6f}")
                    
                    tab1, tab2 = st.tabs(["Ativos", "Despesas"])
                    with tab1:
                        st.table(pd.DataFrame(data['ativos']))
                    with tab2:
                        st.table(pd.DataFrame(data['despesas']))

                    if st.button("Gravar no Banco de Dados"):
                        # Adiciona o nome do fundo extraído pela IA em cada linha
                        for a in data['ativos']: a['fundo_nome'] = data['nome_fundo']
                        for d in data['despesas']: 
                            d['fundo_nome'] = data['nome_fundo']
                            d['valor'] = -abs(d['valor'])
                        
                        conn.table("carteira_diaria").insert(data['ativos']).execute()
                        conn.table("despesas_diarias").insert(data['despesas']).execute()
                        st.success(f"Carteira de {data['nome_fundo']} salva com sucesso!")

                except Exception as e:
                    if "429" in str(e):
                        st.error("🚨 Limite de IA atingido (20/dia). Aguarde alguns minutos ou use uma chave Pro.")
                    else:
                        st.error(f"Erro: {e}")

# --- 2. DASHBOARD DINÂMICO ---
elif menu == "📊 Dashboard":
    # Busca nomes de fundos que já existem no banco
    try:
        res_fundos = conn.table("carteira_diaria").select("fundo_nome").execute()
        lista_fundos = list(set([item['fundo_nome'] for item in res_fundos.data])) if res_fundos.data else []
        
        fundo_sel = st.sidebar.selectbox("Selecionar Fundo:", lista_fundos if lista_fundos else ["Nenhum fundo cadastrado"])
        
        if fundo_sel != "Nenhum fundo cadastrado":
            st.subheader(f"📊 Dashboard: {fundo_sel}")
            # Filtra os dados conforme o fundo selecionado
            c = conn.table("carteira_diaria").select("*").eq("fundo_nome", fundo_sel).execute()
            df_c = pd.DataFrame(c.data)
            pl_total = df_c['valor_mercado'].sum()
            st.metric("PL Consolidado", format_br(pl_total))
            st.dataframe(df_c, use_container_width=True)
    except:
        st.info("Suba uma carteira para começar.")import streamlit as st
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
