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

# Função de Fallback Aprimorada (Sem o prefixo models/ que às vezes causa conflito)
def extrair_dados_com_ia(prompt):
    # Lista de modelos para tentar (em ordem de preferência)
    tentativas = [
        ("gemini-2.5-flash", "Elite (2.5)"),
        ("gemini-1.5-flash", "Reserva de Guerra (1.5)")
    ]
    
    erros = []
    for model_id, label in tentativas:
        try:
            model = genai.GenerativeModel(model_id)
            response = model.generate_content(prompt)
            return response, label
        except Exception as e:
            erros.append(f"{model_id}: {str(e)}")
            continue # Tenta o próximo da lista
            
    # Se todos falharem, levanta o erro com os detalhes
    raise Exception(f"Falha em todos os modelos: {'; '.join(erros)}")

conn = st.connection("supabase", type=SupabaseConnection)

# --- SIDEBAR ---
st.sidebar.title("🛡️ Guardian Ultra")
menu = st.sidebar.radio("Navegação", ["📊 Dashboard", "🤖 Importar Carteira", "📉 Gestão de Passivo", "📜 Regras & Regulamento"])

# --- 1. IMPORTAR CARTEIRA ---
if menu == "🤖 Importar Carteira":
    st.subheader("📥 Carga de Dados Inteligente")
    st.info("O sistema tenta o Gemini 2.5. Se falhar ou acabar a cota, ele pula pro 1.5 sozinho.")
    
    uploaded_file = st.file_uploader("Suba o Excel ou PDF", type=['xlsx', 'pdf'])

    if uploaded_file:
        if st.button("🚀 Iniciar Processamento IA"):
            with st.spinner("IA analisando dados..."):
                try:
                    # Carrega os dados do arquivo
                    df = pd.read_excel(uploaded_file) if uploaded_file.name.endswith('.xlsx') else pd.read_csv(uploaded_file)
                    contexto = df.dropna(how='all').head(250).to_string()
                    
                    prompt = f"""
                    Aja como Senior de Compliance. Extraia do relatório:
                    1. NOME_FUNDO: Nome completo do fundo no cabeçalho.
                    2. ATIVOS: Diferencie 'Debênture Incentivada' (Lei 12.431) de 'Debênture Comum'.
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
                    
                    # Extração segura do JSON
                    raw_text = response.text
                    data = json.loads(raw_text[raw_text.find('{'):raw_text.rfind('}')+1])
                    
                    st.session_state['import_data'] = data
                    st.success(f"📌 Fundo Identificado: **{data['nome_fundo']}** (via {motor_usado})")
                    
                    c1, c2 = st.columns(2)
                    c1.metric("PL Identificado", format_br(data['resumo']['pl']))
                    c2.metric("Cota", f"R$ {data['resumo']['cota']:.6f}")
                    
                    t1, t2 = st.tabs(["📄 Ativos Detalhados", "💸 Despesas"])
                    with t1:
                        df_ativos = pd.DataFrame(data['ativos'])
                        if not df_ativos.empty:
                            st.table(df_ativos.assign(valor_mercado=df_ativos['valor_mercado'].apply(format_br)))
                    with t2:
                        st.table(pd.DataFrame(data['despesas']))

                except Exception as e:
                    st.error(f"Erro no motor da IA: {e}")

        if 'import_data' in st.session_state:
            if st.button("💾 Confirmar e Salvar no Supabase"):
                data = st.session_state['import_data']
                fundo = data['nome_fundo']
                
                # Tag do fundo e ajuste de despesas
                for a in data['ativos']: a['fundo_nome'] = fundo
                desp_final = [{"fundo_nome": fundo, "item": d['item'], "valor": -abs(d['valor'])} for d in data['despesas']]
                
                conn.table("carteira_diaria").insert(data['ativos']).execute()
                conn.table("despesas_diarias").insert(desp_final).execute()
                
                st.success(f"Dados de '{fundo}' salvos com sucesso!")
                st.balloons()
                del st.session_state['import_data']

# --- DASHBOARD E OUTROS ---
elif menu == "📊 Dashboard":
    st.info("Selecione um fundo na barra lateral para ver os dados.")
    # Lógica de dashboard simplificada para teste
    try:
        res = conn.table("carteira_diaria").select("fundo_nome").execute()
        fundos = list(set([i['fundo_nome'] for i in res.data])) if res.data else []
        fundo_sel = st.sidebar.selectbox("Fundo:", fundos)
        if fundo_sel:
            st.write(f"### Dados de {fundo_sel}")
            c = conn.table("carteira_diaria").select("*").eq("fundo_nome", fundo_sel).execute()
            st.dataframe(pd.DataFrame(c.data))
    except: pass
