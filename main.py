import streamlit as st
import pandas as pd
from st_supabase_connection import SupabaseConnection
import google.generativeai as genai
import json

st.set_page_config(page_title="Guardian AI v2", layout="wide", page_icon="🛡️")
st.title("🛡️ Guardian: Inteligência Financeira")

# --- CONEXÃO IA ---
gemini_key = st.secrets.get("GEMINI_API_KEY")
genai.configure(api_key=gemini_key)

# Lógica de seleção automática de modelo (já que funcionou!)
available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
chosen_model = 'models/gemini-2.5-flash' if 'models/gemini-2.5-flash' in available_models else available_models[0]
model = genai.GenerativeModel(chosen_model)

st.sidebar.success(f"Motor: {chosen_model}")

menu = st.sidebar.radio("Navegação", ["📊 Dashboard", "🤖 Importar Relatório"])

if menu == "🤖 Importar Relatório":
    st.subheader("🤖 Analista IA: Extração Completa")
    uploaded_file = st.file_uploader("Suba o Excel ou PDF", type=['xlsx', 'csv', 'pdf'])

    if uploaded_file:
        with st.spinner("Analisando Ativos, Despesas e Resumo..."):
            try:
                # Leitura
                df = pd.read_excel(uploaded_file) if uploaded_file.name.endswith('.xlsx') else pd.read_csv(uploaded_file)
                contexto = df.dropna(how='all').head(150).to_string() # Pegamos 150 linhas para garantir
                
                prompt = f"""
                Você é um especialista em backoffice de fundos. Analise os dados e extraia:
                1. ATIVOS: Apenas itens individuais (IGNORE linhas de 'TOTAL', 'PORTFOLIO' ou 'SUBTOTAL').
                2. DESPESAS: Taxas, impostos e custos operacionais.
                3. RESUMO: Patrimônio Líquido, Valor da Cota e Total de Despesas.

                Retorne APENAS um JSON:
                {{
                  "ativos": [{{ "ativo": "NOME", "valor_mercado": 0.0, "tipo_ativo": "TIPO" }}],
                  "despesas": [{{ "item": "NOME", "valor": 0.0 }}],
                  "resumo": {{ "pl": 0.0, "cota": 0.0, "total_despesas": 0.0 }}
                }}
                DADOS: {contexto}
                """
                
                response = model.generate_content(prompt)
                txt = response.text
                start, end = txt.find('{'), txt.rfind('}') + 1
                data = json.loads(txt[start:end])
                
                # --- EXIBIÇÃO ORGANIZADA ---
                col1, col2, col3 = st.columns(3)
                col1.metric("Patrimônio Líquido", f"R$ {data['resumo']['pl']:,.2f}")
                col2.metric("Valor da Cota", f"R$ {data['resumo']['cota']:.6f}")
                col3.metric("Total Despesas", f"R$ {data['resumo']['total_despesas']:,.2f}", delta_color="inverse")

                tab1, tab2 = st.tabs(["📄 Ativos Identificados", "💸 Despesas"])
                with tab1:
                    st.table(data['ativos'])
                with tab2:
                    st.table(data['despesas'])

                if st.button("Confirmar e Salvar Tudo"):
                    conn = st.connection("supabase", type=SupabaseConnection)
                    # Salva os ativos
                    conn.table("carteira_diaria").insert(data['ativos']).execute()
                    st.success("Dados salvos no Supabase!")
                    
            except Exception as e:
                st.error(f"Erro no processamento: {e}")

else:
    st.subheader("📊 Visão Consolidada")
    # Aqui depois podemos puxar o histórico do banco
    st.info("O Dashboard está pronto para receber os dados históricos.")
