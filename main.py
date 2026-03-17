import streamlit as st
import pandas as pd
from st_supabase_connection import SupabaseConnection
import google.generativeai as genai
import json

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Guardian AI", layout="wide", page_icon="🛡️")
st.title("🛡️ Guardian: Inteligência de Dados")

# --- CONEXÕES E SEGURANÇA ---
gemini_key = st.secrets.get("GEMINI_API_KEY")
supabase_url = st.secrets.get("connections", {}).get("supabase", {}).get("SUPABASE_URL")

if not gemini_key:
    st.error("⚠️ API Key do Gemini não encontrada nos Secrets!")
    st.stop()

# Configura o motor da IA
try:
    genai.configure(api_key=gemini_key)
    # Usando o modelo mais estável e rápido para extração
    model = genai.GenerativeModel('gemini-1.5-flash')
except Exception as e:
    st.error(f"Erro ao ligar o motor de IA: {e}")

# --- NAVEGAÇÃO LATERAL ---
menu = st.sidebar.radio("Navegação", ["📊 Dashboard", "🤖 Importar com IA"])

if menu == "🤖 Importar com IA":
    st.subheader("Analista IA: Leitura de Relatórios Complexos")
    uploaded_file = st.file_uploader("Suba o arquivo (Excel da JGP, Sparta, etc)", type=['xlsx', 'csv'])

    if uploaded_file:
        with st.spinner("IA processando dados..."):
            try:
                # 1. Lê o arquivo e limpa linhas/colunas totalmente vazias
                df = pd.read_excel(uploaded_file) if uploaded_file.name.endswith('.xlsx') else pd.read_csv(uploaded_file)
                df_clean = df.dropna(how='all').dropna(axis=1, how='all')
                
                # 2. Manda apenas o essencial (primeiras 100 linhas) para não estourar a IA
                contexto = df_clean.head(100).to_string()
                
                prompt = f"""
                Você é um especialista em fundos. Extraia os ATIVOS, VALORES DE MERCADO e TIPOS.
                Ignore cabeçalhos e rodapés. Retorne APENAS o JSON no formato abaixo, sem textos extras:
                [ {{"ativo": "NOME", "valor_mercado": 0.0, "tipo_ativo": "TIPO"}} ]
                
                DADOS DO RELATÓRIO:
                {contexto}
                """
                
                # 3. Chamada da IA
                response = model.generate_content(prompt)
                txt = response.text
                
                # 4. Extração segura do JSON
                start = txt.find('[')
                end = txt.rfind(']') + 1
                if start == -1 or end == 0:
                    st.error("A IA não conseguiu estruturar os dados. Tente um arquivo mais limpo.")
                    st.expander("Ver resposta bruta").write(txt)
                else:
                    dados_json = json.loads(txt[start:end])
                    st.write("✅ Dados identificados pela IA:")
                    st.table(dados_json)
                    
                    if st.button("Confirmar e Salvar no Supabase"):
                        conn = st.connection("supabase", type=SupabaseConnection)
                        conn.table("carteira_diaria").insert(dados_json).execute()
                        st.success("Dados integrados com sucesso!")
                        st.balloons()
            except Exception as e:
                st.error(f"Erro no processamento: {e}")

else:
    st.subheader("📊 Posição Consolidada (Dados do Supabase)")
    try:
        conn = st.connection("supabase", type=SupabaseConnection)
        res = conn.table("carteira_diaria").select("*").execute()
        if res.data:
            df_banco = pd.DataFrame(res.data)
            st.dataframe(df_banco, use_container_width=True)
            
            # Pequeno gráfico de pizza para dar um tchan
            if 'tipo_ativo' in df_banco.columns:
                st.write("Distribuição por Tipo:")
                st.pie_chart(df_banco['tipo_ativo'].value_counts())
        else:
            st.info("O banco de dados está vazio. Vá em 'Importar com IA'.")
    except Exception as e:
        st.error(f"Erro ao carregar banco: {e}")
