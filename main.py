import streamlit as st
import pandas as pd
from st_supabase_connection import SupabaseConnection
import google.generativeai as genai
import json

# Configuração Inicial
st.set_page_config(page_title="Guardian AI", layout="wide")
st.title("🛡️ Guardian: Inteligência de Dados com IA")

# Conexões
# Use .get() para não travar se a chave não existir
gemini_key = st.secrets.get("GEMINI_API_KEY", "CHAVE_NAO_ENCONTRADA")
genai.configure(api_key=gemini_key)
model = genai.GenerativeModel('gemini-1.5-flash')

menu = st.sidebar.radio("Navegação", ["Dashboard", "Importar com IA"])

if menu == "Importar com IA":
    st.subheader("🤖 Analista IA: Leitura de Relatórios Complexos")
    uploaded_file = st.file_uploader("Suba o PDF ou Excel do Fundo", type=['xlsx', 'pdf', 'csv'])

    if uploaded_file:
        with st.spinner("O Gemini está analisando os dados..."):
            # Lendo o arquivo corretamente (tratando CSV ou Excel)
            if uploaded_file.name.endswith('.csv'):
                df_raw = pd.read_csv(uploaded_file).to_string()
            else:
                df_raw = pd.read_excel(uploaded_file).to_string()
            
            prompt = f"""
            Abaixo estão os dados brutos de um relatório de fundo de investimento. 
            Extraia todos os ativos da carteira, seus valores de mercado e tipos de ativos.
            Retorne APENAS um JSON no formato:
            [{{"ativo": "NOME", "valor_mercado": 0.0, "tipo_ativo": "TIPO"}}]
            Dados: {df_raw}
            """
            
            response = model.generate_content(prompt)
            
            # --- NOVA LÓGICA DE LIMPEZA DE JSON ---
            try:
                # Tenta isolar o JSON no meio do texto
                response_text = response.text.strip()
                # Procura onde o JSON começa e termina (entre colchetes)
                start_index = response_text.find('[')
                end_index = response_text.rfind(']') + 1
                
                if start_index == -1 or end_index == 0:
                     raise ValueError("A IA não retornou um JSON válido.")

                json_raw = response_text[start_index:end_index]
                dados_estruturados = json.loads(json_raw)
                
                st.write("✅ IA Identificou os seguintes dados:")
                st.table(dados_estruturados)

                if st.button("Confirmar e Salvar no Supabase"):
                    conn = st.connection("supabase", type=SupabaseConnection)
                    conn.table("carteira_diaria").insert(dados_estruturados).execute()
                    st.success("Dados salvos com sucesso!")

            except json.JSONDecodeError as e:
                st.error(f"Erro ao ler o JSON da IA: {e}")
                st.info(f"Resposta bruta da IA: {response.text}") # Mostra para te ajudar a debugar
            except ValueError as e:
                st.error(f"Erro nos dados: {e}")
            except Exception as e:
                st.error(f"Ocorreu um erro inesperado: {e}")

else:
    st.subheader("📊 Posição Consolidada")
    conn = st.connection("supabase", type=SupabaseConnection)
    res = conn.table("carteira_diaria").select("*").execute()
    if res.data:
        st.dataframe(pd.DataFrame(res.data), use_container_width=True)
    else:
        st.info("Nenhum dado no banco.")
