import streamlit as st
import pandas as pd
from st_supabase_connection import SupabaseConnection
import google.generativeai as genai
import json

# --- 1. CONFIGURAÇÃO ---
st.set_page_config(page_title="Guardian AI", layout="wide", page_icon="🛡️")
st.title("🛡️ Guardian: Inteligência de Dados")

# --- 2. CONEXÃO IA ---
gemini_key = st.secrets.get("GEMINI_API_KEY")

if not gemini_key:
    st.error("⚠️ API Key não encontrada nos Secrets!")
    st.stop()

try:
    genai.configure(api_key=gemini_key)
    # Mudança aqui: Usando o nome direto do modelo estável
    model = genai.GenerativeModel('gemini-1.5-flash')
except Exception as e:
    st.error(f"Erro ao configurar IA: {e}")

# --- 3. NAVEGAÇÃO ---
menu = st.sidebar.radio("Navegação", ["📊 Dashboard", "🤖 Importar com IA"])

if menu == "🤖 Importar com IA":
    st.subheader("Analista IA: Leitura de Relatórios")
    uploaded_file = st.file_uploader("Suba o arquivo (Excel ou CSV)", type=['xlsx', 'csv'])

    if uploaded_file:
        with st.spinner("IA processando dados..."):
            try:
                # Lê o arquivo
                if uploaded_file.name.endswith('.xlsx'):
                    df = pd.read_excel(uploaded_file)
                else:
                    df = pd.read_csv(uploaded_file)
                
                # Limpa lixo
                df_clean = df.dropna(how='all').dropna(axis=1, how='all')
                contexto = df_clean.head(100).to_string()
                
                prompt = f"""
                Retorne APENAS um JSON: 
                [ {{"ativo": "NOME", "valor_mercado": 0.0, "tipo_ativo": "TIPO"}} ] 
                com os ativos desta lista financeira: {contexto}
                """
                
                # Chamada da IA
                response = model.generate_content(prompt)
                txt = response.text
                
                # Extração do JSON
                start = txt.find('[')
                end = txt.rfind(']') + 1
                
                if start == -1:
                    st.error("Não identifiquei dados de ativos.")
                else:
                    dados = json.loads(txt[start:end])
                    st.write("✅ Dados identificados:")
                    st.table(dados)
                    
                    if st.button("Confirmar e Salvar no Supabase"):
                        conn = st.connection("supabase", type=SupabaseConnection)
                        conn.table("carteira_diaria").insert(dados).execute()
                        st.success("Salvo com sucesso!")
                        st.balloons()
            except Exception as e:
                st.error(f"Erro no processamento: {e}")

else:
    st.subheader("📊 Posição Consolidada")
    try:
        conn = st.connection("supabase", type=SupabaseConnection)
        res = conn.table("carteira_diaria").select("*").execute()
        
        if res.data:
            df_banco = pd.DataFrame(res.data)
            st.dataframe(df_banco, use_container_width=True)
            
            if 'tipo_ativo' in df_banco.columns:
                st.write("### Distribuição por Tipo")
                st.pie_chart(df_banco['tipo_ativo'].value_counts())
        else:
            st.info("Banco vazio. Importe dados primeiro.")
    except Exception as e:
        st.error(f"Erro ao carregar banco: {e}")
