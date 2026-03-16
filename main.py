import streamlit as st
import pandas as pd
from st_supabase_connection import SupabaseConnection
import google.generativeai as genai
import json

# 1. Configuração Inicial
st.set_page_config(page_title="Guardian AI", layout="wide")
st.title("🛡️ Guardian: Inteligência de Dados com IA")

# 2. Verificação de Segurança da API Key
gemini_key = st.secrets.get("GEMINI_API_KEY")

if not gemini_key or gemini_key == "AIzaSyDoWH6p4-asXzlI4hyzCQ0X_6eaqTQCHhE":
    st.error("⚠️ Erro: API Key do Gemini não encontrada nos Secrets do Streamlit.")
    st.info("Va em Settings > Secrets e adicione: GEMINI_API_KEY = 'sua_chave_aqui'")
    st.stop()

# 3. Configuração do Modelo
try:
    genai.configure(api_key=gemini_key)
    model = genai.GenerativeModel('gemini-1.5-flash')
except Exception as e:
    st.error(f"Erro ao configurar o motor de IA: {e}")
    st.stop()

# 4. Interface de Navegação
menu = st.sidebar.radio("Navegação", ["Dashboard", "Importar com IA"])

if menu == "Importar com IA":
    st.subheader("🤖 Analista IA: Leitura de Relatórios")
    uploaded_file = st.file_uploader("Suba o Excel do Fundo (JGP, Sparta, etc)", type=['xlsx', 'csv'])

    if uploaded_file:
        with st.spinner("Limpando e analisando dados..."):
            try:
                # Leitura e Limpeza básica para não estourar o limite da IA
                df = pd.read_excel(uploaded_file) if uploaded_file.name.endswith('.xlsx') else pd.read_csv(uploaded_file)
                df_clean = df.dropna(how='all').dropna(axis=1, how='all')
                
                # Enviamos apenas as primeiras 100 linhas para evitar erro de tamanho
                contexto_texto = df_clean.head(100).to_string()
                
                prompt = f"""
                Analise estes dados de um relatório de fundo e extraia a CARTEIRA DE ATIVOS.
                Ignore cabeçalhos. Retorne APENAS um JSON puro no formato:
                [ {{"ativo": "NOME", "valor_mercado": 0.0, "tipo_ativo": "TIPO"}} ]
                
                DADOS:
                {contexto_texto}
                """
                
                response = model.generate_content(prompt)
                res_text = response.text.strip()
                
                # Extração do JSON (caça os colchetes para evitar textos extras da IA)
                start = res_text.find('[')
                end = res_text.rfind(']') + 1
                
                if start == -1:
                    st.warning("IA não encontrou dados estruturados. Verifique o arquivo.")
                    st.write("Resposta da IA:", res_text)
                else:
                    dados_finais = json.loads(res_text[start:end])
                    st.write("✅ Dados identificados:")
                    st.table(dados_finais)

                    if st.button("Confirmar e Salvar no Banco"):
                        conn = st.connection("supabase", type=SupabaseConnection)
                        conn.table("carteira_diaria").insert(dados_finais).execute()
                        st.success("Dados enviados para o Supabase!")

            except Exception as e:
                st.error(f"Erro no processamento: {e}")

else:
    # Dashboard Simples
    st.subheader("📊 Posição em Carteira")
    try:
        conn = st.connection("supabase", type=SupabaseConnection)
        res = conn.table("carteira_diaria").select("*").execute()
        if res.data:
            st.dataframe(pd.DataFrame(res.data), use_container_width=True)
        else:
            st.info("Nenhum dado encontrado no banco de dados.")
    except Exception as e:
        st.error(f"Erro ao carregar banco: {e}")
