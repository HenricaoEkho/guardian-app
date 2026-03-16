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
        with st.spinner("Limpando e analisando dados com IA..."):
            try:
                # 1. Lê o arquivo
                if uploaded_file.name.endswith('.csv'):
                    df_raw = pd.read_csv(uploaded_file)
                else:
                    df_raw = pd.read_excel(uploaded_file)
                
                # 2. LIMPEZA: Remove linhas e colunas que estão 100% vazias
                df_clean = df_raw.dropna(how='all').dropna(axis=1, how='all')
                
                # 3. Pega apenas as primeiras 100 linhas (geralmente onde está a carteira)
                # Isso evita mandar lixo e estourar o limite da API
                texto_para_ia = df_clean.head(100).to_string()
                
                prompt = f"""
                Você é um especialista em fundos de investimento. 
                Analise os dados abaixo e extraia a CARTEIRA DE ATIVOS.
                Ignore cabeçalhos e rodapés. Foque em: Nome do Ativo, Valor de Mercado e Tipo.
                
                Retorne APENAS um JSON no formato:
                [
                  {{"ativo": "NOME DO ATIVO", "valor_mercado": 1234.56, "tipo_ativo": "TIPO"}}
                ]
                
                DADOS:
                {texto_para_ia}
                """
                
                # 4. Chama a IA
                response = model.generate_content(prompt)
                
                # 5. Processa a resposta
                response_text = response.text.strip()
                start_index = response_text.find('[')
                end_index = response_text.rfind(']') + 1
                
                if start_index == -1:
                    st.error("A IA não conseguiu encontrar dados de ativos. Tente subir um trecho mais limpo.")
                    st.info(f"Resposta da IA: {response_text}")
                else:
                    dados_json = json.loads(response_text[start_index:end_index])
                    st.write("✅ Ativos identificados pela IA:")
                    st.table(dados_json)

                    if st.button("Confirmar e Salvar no Supabase"):
                        conn = st.connection("supabase", type=SupabaseConnection)
                        conn.table("carteira_diaria").insert(dados_json).execute()
                        st.success("Dados integrados ao Guardian!")

            except Exception as e:
                st.error(f"Erro no processamento: {e}")
            
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
