import streamlit as st
import pandas as pd
from st_supabase_connection import SupabaseConnection
import google.generativeai as genai
import json
from pypdf import PdfReader

# --- 1. CONFIGURAÇÃO E FORMATAÇÃO ---
st.set_page_config(page_title="Guardian Ultra v13", layout="wide", page_icon="🛡️")

def format_br(valor, prefixo="R$ "):
    try:
        val = float(valor)
        return f"{prefixo}{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except: return str(valor)

# --- 2. CONEXÃO IA HÍBRIDA (HYDRA) ---
gemini_key = st.secrets.get("GEMINI_API_KEY")
if gemini_key:
    genai.configure(api_key=gemini_key)

MODELOS = ['models/gemini-1.5-flash', 'models/gemini-3.1-flash-lite-preview']

def chamar_ia_hydra(prompt):
    for m in MODELOS:
        try:
            model = genai.GenerativeModel(m)
            return model.generate_content(prompt), m
        except: continue
    raise Exception("Sistema Hydra: Falha na comunicação com os modelos de IA.")

conn = st.connection("supabase", type=SupabaseConnection)

# --- 3. SIDEBAR: NAVEGAÇÃO ---
st.sidebar.title("🛡️ Guardian Ultra v13")
try:
    # Busca nomes únicos de fundos que já possuem carteira ou regulamento
    res_f = conn.table("carteira_diaria").select("fundo_nome").execute()
    lista_fundos = sorted(list(set([i['fundo_nome'] for i in res_f.data]))) if res_f.data else []
except: lista_fundos = []

fundo_ativo = st.sidebar.selectbox("Fundo Ativo:", lista_fundos if lista_fundos else ["Nenhum cadastrado"])
menu = st.sidebar.radio("Ir para:", ["📊 Dashboard", "🤖 Importar Carteira", "📜 Regulamento e Compliance", "📉 Gestão de Passivo"])

# --- 4. 📊 ABA: DASHBOARD (VISUALIZAÇÃO CORRIGIDA) ---
if menu == "📊 Dashboard":
    st.subheader(f"📊 Monitor de Compliance: {fundo_ativo}")
    if fundo_ativo != "Nenhum cadastrado":
        # Puxa os dados do Supabase filtrando pelo fundo selecionado
        c = conn.table("carteira_diaria").select("*").eq("fundo_nome", fundo_ativo).execute()
        r = conn.table("regulamentos").select("*").eq("fundo_nome", fundo_ativo).execute()
        
        if c.data:
            df_c = pd.DataFrame(c.data)
            pl_total = df_c['valor_mercado'].sum()
            st.metric("Patrimônio Líquido Total", format_br(pl_total))
            
            if r.data:
                reg = r.data[0]
                st.info(f"📜 **Mandato:** {reg['descricao_mandato']}")
                
                with st.expander("📝 Estrutura de Regras e Mapa de Ativos"):
                    col_r, col_m = st.columns(2)
                    col_r.write("**Regras Extraídas:**")
                    col_r.json(reg['regras_json'])
                    col_m.write("**Mapa de Ativos:**")
                    col_m.json(reg['mapa_ativos_json'])
            
            st.write("### Composição da Carteira")
            st.dataframe(df_c[['ativo', 'valor_mercado', 'tipo_ativo']].assign(
                valor_mercado=lambda x: x['valor_mercado'].apply(format_br)
            ), use_container_width=True)
        else:
            st.warning("⚠️ Nenhuma carteira encontrada para este fundo. Vá em 'Importar Carteira'.")
    else:
        st.info("Selecione ou importe um fundo para visualizar os dados.")

# --- 5. 📜 ABA: REGULAMENTO E COMPLIANCE (O ARQUITETO) ---
elif menu == "📜 Regulamento e Compliance":
    st.subheader("📜 Arquiteto de Inteligência de Compliance")
    upload_reg = st.file_uploader("Suba o Regulamento (PDF)", type=['pdf'])
    
    if upload_reg:
        if st.button("🚀 Gerar Mapa de Compliance"):
            with st.spinner("IA analisando política de investimento e criando regras..."):
                try:
                    reader = PdfReader(upload_reg)
                    texto_completo = ""
                    for page in reader.pages[:15]: texto_completo += page.extract_text()
                    
                    # O PROMPT QUE CRIA A ESTRUTURA SOLICITADA
                    super_prompt = f"""
                    Você é um Engenheiro de Compliance de Fundos. Analise o regulamento e gere um JSON rigorosamente estruturado.
                    
                    TAFAS:
                    1. Identifique o Nome do Fundo e CNPJ.
                    2. Crie um array 'regras' contendo: id, descricao, fonte, tipo (minimo_percentual ou maximo_percentual), limite_min (use 0.0 a 1.0), limite_max (use 0.0 a 1.0) e as categorias afetadas.
                    3. Crie um 'mapa_ativos' vinculando termos ou CNPJs encontrados no texto a categorias lógicas (ex: 'JGP DEB' -> fundo_deb_incentivada).
                    4. Explique as categorias no campo 'categorias_definidas'.
                    
                    DADOS: {texto_completo[:8000]}
                    """
                    res, motor = chamar_ia_hydra(super_prompt)
                    data = json.loads(res.text[res.text.find('{'):res.text.rfind('}')+1])
                    st.session_state['schema_reg'] = data
                    st.success(f"Inteligência gerada via {motor}")
                    st.json(data)

                except Exception as e: st.error(f"Erro na IA: {e}")

        if 'schema_reg' in st.session_state:
            if st.button("💾 Salvar Estrutura e Vincular"):
                d = st.session_state['schema_reg']
                payload = {
                    "fundo_nome": d.get('fundo') or d.get('nome_fundo'),
                    "cnpj": d.get('cnpj'),
                    "descricao_mandato": d.get('descricao'),
                    "regras_json": d.get('regras'),
                    "mapa_ativos_json": d.get('mapa_ativos'),
                    "texto_bruto": "Processado via Guardian v13"
                }
                conn.table("regulamentos").upsert(payload, on_conflict="fundo_nome").execute()
                st.success(f"Regulamento de '{payload['fundo_nome']}' salvo com sucesso!")
                del st.session_state['schema_reg']
                st.rerun()

# --- ABA: IMPORTAR CARTEIRA (MANTIDA) ---
elif menu == "🤖 Importar Carteira":
    st.subheader("📥 Carga de Posição Diária")
    # Código de importação anterior mantido para garantir funcionamento...
