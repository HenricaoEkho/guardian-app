import streamlit as st
import pandas as pd
from st_supabase_connection import SupabaseConnection
import google.generativeai as genai
import json

# --- CONFIGURAÇÃO E ESTILO ---
st.set_page_config(page_title="Guardian Pro Ultra", layout="wide", page_icon="🛡️")

def format_br(valor):
    try:
        val = float(valor)
        return f"R$ {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except: return str(valor)

# --- CONEXÃO IA ---
gemini_key = st.secrets.get("GEMINI_API_KEY")
if gemini_key:
    genai.configure(api_key=gemini_key)

# Função Inteligente de Fallback (Troca Automática)
def extrair_dados_com_ia(prompt):
    try:
        # Tenta o modelo 2.5 (O mais potente, limite de 20/dia)
        model = genai.GenerativeModel('models/gemini-2.5-flash')
        response = model.generate_content(prompt)
        return response, "Gemini 2.5 Flash (Elite)"
    except Exception as e:
        if "429" in str(e): # Se estourar a cota...
            # Troca para o 1.5 (Limite de 1.500/dia)
            model = genai.GenerativeModel('models/gemini-1.5-flash')
            response = model.generate_content(prompt)
            return response, "Gemini 1.5 Flash (Reserva de Guerra)"
        else:
            raise e

conn = st.connection("supabase", type=SupabaseConnection)

# --- SIDEBAR ---
st.sidebar.title("🛡️ Guardian Ultra")
menu = st.sidebar.radio("Navegação", ["📊 Dashboard", "🤖 Importar Carteira", "📉 Gestão de Passivo", "📜 Regras & Regulamento"])

# --- 1. IMPORTAR CARTEIRA AUTOMÁTICA ---
if menu == "🤖 Importar Carteira":
    st.subheader("📥 Carga de Dados Inteligente com Auto-Switch")
    st.info("O sistema tentará o Gemini 2.5. Se a cota acabar, mudará para o 1.5 automaticamente.")
    
    uploaded_file = st.file_uploader("Suba o Excel ou PDF", type=['xlsx', 'pdf'])

    if uploaded_file:
        if st.button("🚀 Iniciar Processamento IA"):
            with st.spinner("IA analisando dados..."):
                try:
                    df = pd.read_excel(uploaded_file) if uploaded_file.name.endswith('.xlsx') else pd.read_csv(uploaded_file)
                    contexto = df.dropna(how='all').head(250).to_string()
                    
                    prompt = f"""
                    Aja como Senior de Compliance. Extraia do relatório:
                    1. NOME_FUNDO: Nome completo do fundo no cabeçalho.
                    2. ATIVOS: Identifique detalhadamente (Debênture Incentivada Lei 12.431 vs Comum).
                    3. DESPESAS: Todos os custos (Sempre positivos no JSON).
                    4. RESUMO: Patrimônio Líquido e Cota.
                    
                    JSON: {{ 
                      "nome_fundo": "NOME_DO_FUNDO",
                      "ativos": [{{ "ativo": "NOME", "valor_mercado": 0.0, "tipo_ativo": "TIPO" }}], 
                      "despesas": [{{ "item": "NOME", "valor": 0.0 }}], 
                      "resumo": {{ "pl": 0.0, "cota": 0.0 }} 
                    }}
                    DADOS: {contexto}
                    """
                    
                    response, motor_usado = extrair_dados_com_ia(prompt)
                    data = json.loads(response.text[response.text.find('{'):response.text.rfind('}')+1])
                    
                    st.session_state['import_data'] = data
                    st.success(f"📌 Fundo Identificado: **{data['nome_fundo']}** (via {motor_usado})")
                    
                    c1, c2 = st.columns(2)
                    c1.metric("PL Identificado", format_br(data['resumo']['pl']))
                    c2.metric("Cota", f"R$ {data['resumo']['cota']:.6f}")
                    
                    t1, t2 = st.tabs(["📄 Ativos Detalhados", "💸 Despesas"])
                    with t1:
                        df_ativos = pd.DataFrame(data['ativos'])
                        st.table(df_ativos.assign(valor_mercado=df_ativos['valor_mercado'].apply(format_br)))
                    with t2:
                        st.table(pd.DataFrame(data['despesas']))

                except Exception as e:
                    st.error(f"Erro no processamento: {e}")

        # Botão de salvar (só aparece se houver dados na memória)
        if 'import_data' in st.session_state:
            if st.button("💾 Confirmar e Salvar no Supabase"):
                data = st.session_state['import_data']
                fundo = data['nome_fundo']
                
                for a in data['ativos']: a['fundo_nome'] = fundo
                desp_final = [{"fundo_nome": fundo, "item": d['item'], "valor": -abs(d['valor'])} for d in data['despesas']]
                
                conn.table("carteira_diaria").insert(data['ativos']).execute()
                conn.table("despesas_diarias").insert(desp_final).execute()
                
                st.success(f"Dados de '{fundo}' salvos com sucesso!")
                st.balloons()
                del st.session_state['import_data']

# --- 2. DASHBOARD ---
elif menu == "📊 Dashboard":
    try:
        res = conn.table("carteira_diaria").select("fundo_nome").execute()
        fundos = list(set([i['fundo_nome'] for i in res.data])) if res.data else []
        fundo_sel = st.sidebar.selectbox("Fundo Ativo:", fundos if fundos else ["Nenhum cadastrado"])
        
        if fundo_sel != "Nenhum cadastrado":
            st.subheader(f"📊 Painel Consolidado: {fundo_sel}")
            c = conn.table("carteira_diaria").select("*").eq("fundo_nome", fundo_sel).execute()
            df_c = pd.DataFrame(c.data)
            
            st.metric("PL Total do Fundo", format_br(df_c['valor_mercado'].sum()))
            st.dataframe(df_c, use_container_width=True)
    except:
        st.info("Suba uma carteira para ver o Dashboard.")

# --- 3. PASSIVO E REGULAMENTO (EM BREVE) ---
else:
    st.info("Aba em desenvolvimento. Próxima etapa: Upload de PDF de Regulamento.")
