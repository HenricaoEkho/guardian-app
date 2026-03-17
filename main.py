import streamlit as st
import pandas as pd
from st_supabase_connection import SupabaseConnection
import google.generativeai as genai
import json

# --- FUNÇÃO DE FORMATAÇÃO BR ---
def format_br(valor):
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

st.set_page_config(page_title="Guardian AI v3", layout="wide", page_icon="🛡️")
st.title("🛡️ Guardian: Inteligência Financeira")

# --- CONEXÃO IA ---
gemini_key = st.secrets.get("GEMINI_API_KEY")
genai.configure(api_key=gemini_key)
available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
chosen_model = 'models/gemini-2.5-flash' if 'models/gemini-2.5-flash' in available_models else available_models[0]
model = genai.GenerativeModel(chosen_model)

menu = st.sidebar.radio("Navegação", ["📊 Dashboard", "🤖 Importar Relatório", "📜 Regulamentos & Enquadramento"])

if menu == "🤖 Importar Relatório":
    st.subheader("🤖 Analista IA: Extração Profissional")
    uploaded_file = st.file_uploader("Suba o Excel ou PDF", type=['xlsx', 'csv', 'pdf'])

    if uploaded_file:
        with st.spinner("Analisando com foco em enquadramento (Lei 12.431)..."):
            try:
                df = pd.read_excel(uploaded_file) if uploaded_file.name.endswith('.xlsx') else pd.read_csv(uploaded_file)
                contexto = df.dropna(how='all').head(200).to_string() # Mais linhas para pegar detalhes
                
                prompt = f"""
                Você é um analista de compliance de fundos brasileiro. 
                Analise os dados e extraia:
                1. ATIVOS: Identifique detalhadamente. Se for uma debênture, verifique se é 'Incentivada' (Lei 12.431).
                2. DESPESAS: Qualquer custo. IMPORTANTE: O valor deve ser SEMPRE NEGATIVO no JSON.
                3. RESUMO: Patrimônio Líquido, Cota e Total Despesas.

                Categorias de Ativo permitidas: 'Título Público', 'Debênture Incentivada', 'Debênture Comum', 'Fundo de Renda Fixa', 'Ações', 'Caixa'.

                Retorne APENAS JSON:
                {{
                  "ativos": [{{ "ativo": "NOME", "valor_mercado": 0.0, "tipo_ativo": "CATEGORIA" }}],
                  "despesas": [{{ "item": "NOME", "valor": 0.0 }}],
                  "resumo": {{ "pl": 0.0, "cota": 0.0, "total_despesas": 0.0 }}
                }}
                DADOS: {contexto}
                """
                
                response = model.generate_content(prompt)
                data = json.loads(response.text[response.text.find('{'):response.text.rfind('}') + 1])
                
                # Tratamento de Despesas (Garantir Negativo)
                for d in data['despesas']:
                    d['valor'] = -abs(d['valor'])
                data['resumo']['total_despesas'] = -abs(data['resumo']['total_despesas'])

                # --- EXIBIÇÃO ---
                col1, col2, col3 = st.columns(3)
                col1.metric("Patrimônio Líquido", format_br(data['resumo']['pl']))
                col2.metric("Valor da Cota", f"R$ {data['resumo']['cota']:.6f}")
                col3.metric("Total Despesas", format_br(data['resumo']['total_despesas']), delta_color="inverse")

                tab1, tab2 = st.tabs(["📄 Ativos (Foco Enquadramento)", "💸 Despesas (Negativas)"])
                with tab1:
                    df_ativos = pd.DataFrame(data['ativos'])
                    st.table(df_ativos)
                with tab2:
                    st.table(data['despesas'])

                if st.button("Confirmar e Salvar no Supabase"):
                    conn = st.connection("supabase", type=SupabaseConnection)
                    conn.table("carteira_diaria").insert(data['ativos']).execute()
                    st.success("Carteira salva!")
                    
            except Exception as e:
                st.error(f"Erro: {e}")

# --- NOVA ABA DE REGULAMENTOS (ESTRUTURA INICIAL) ---
elif menu == "📜 Regulamentos & Enquadramento":
    st.subheader("📜 Gestão de Regulamentos")
    st.info("Aqui vamos subir os PDFs dos regulamentos para a IA ler as travas de enquadramento.")
    # Próximo passo: Criar tabela 'regulamentos' no Supabase
