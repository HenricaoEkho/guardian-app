import streamlit as st
import pandas as pd
from st_supabase_connection import SupabaseConnection
import google.generativeai as genai
import json
from pypdf import PdfReader

# --- CONFIGURAÇÃO ---
st.set_page_config(page_title="Guardian Joker v12", layout="wide", page_icon="🛡️")

def format_br(valor, prefixo="R$ "):
    try:
        val = float(valor)
        return f"{prefixo}{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except: return str(valor)

# --- CONEXÃO IA HYDRA ---
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
    raise Exception("Sistema Hydra: Falha na comunicação com a IA.")

conn = st.connection("supabase", type=SupabaseConnection)

# --- SIDEBAR ---
st.sidebar.title("🛡️ Guardian Joker")
try:
    res_f = conn.table("carteira_diaria").select("fundo_nome").execute()
    lista_fundos = sorted(list(set([i['fundo_nome'] for i in res_f.data]))) if res_f.data else []
except: lista_fundos = []

fundo_ativo = st.sidebar.selectbox("Fundo Ativo:", lista_fundos if lista_fundos else ["Nenhum cadastrado"])
menu = st.sidebar.radio("Ir para:", ["📊 Dashboard", "🤖 Importar Carteira", "📜 Regulamento e Compliance", "📉 Gestão de Passivo"])

# --- 📜 ABA: REGULAMENTO E COMPLIANCE (O CORINGA) ---
if menu == "📜 Regulamento e Compliance":
    st.subheader("📜 Inteligência de Regulamentos e Leis")
    st.info("A IA analisará a política de investimento e limites de risco, independente da classe do fundo.")
    
    upload_reg = st.file_uploader("Suba o Regulamento (PDF)", type=['pdf'])
    
    if upload_reg:
        if st.button("🚀 Analisar Regras de Investimento"):
            with st.spinner("IA mapeando limites de enquadramento..."):
                try:
                    reader = PdfReader(upload_reg)
                    texto_completo = ""
                    for page in reader.pages[:15]: texto_completo += page.extract_text()
                    
                    # PROMPT "CORINGA" - Sem forçar leis específicas
                    prompt_reg = f"""
                    Aja como um Auditor de Compliance Multimercado. 
                    Analise o texto e identifique a 'Política de Investimento' e 'Limites de Concentração'.
                    
                    INSTRUÇÕES:
                    1. Identifique a classe do fundo (Ações, Renda Fixa, FIDC, etc).
                    2. Mapeie TODOS os limites percentuais de concentração por emissor e por modalidade.
                    3. Se houver menção a leis (ex: Lei 12.431 para infraestrutura ou Resolução 175), extraia as metas.
                    
                    Retorne APENAS JSON:
                    {{
                      "nome_fundo": "NOME_IDENTIFICADO",
                      "classe_fundo": "TIPO",
                      "limites_principais": {{
                        "meta_minima_ativo_alvo": 0.0,
                        "max_por_emissor": 0.0,
                        "alavancagem_permitida": false
                      }},
                      "regras_detalhadas": {{ "chave": "valor" }}
                    }}
                    TEXTO: {texto_completo[:8000]}
                    """
                    res, motor = chamar_ia_hydra(prompt_reg)
                    reg_data = json.loads(res.text[res.text.find('{'):res.text.rfind('}')+1])
                    st.session_state['temp_reg'] = reg_data
                    st.success(f"Análise finalizada via {motor}")
                except Exception as e: st.error(f"Erro: {e}")

        if 'temp_reg' in st.session_state:
            reg = st.session_state['temp_reg']
            st.write(f"### Regras de {reg['nome_fundo']} ({reg['classe_fundo']})")
            st.json(reg['limites_principais'])
            
            if st.button("💾 Salvar Regulamento e Vincular"):
                payload = {
                    "fundo_nome": reg['nome_fundo'],
                    "meta_incentivadas": reg['limites_principais'].get('meta_minima_ativo_alvo'),
                    "limite_emissor": reg['limites_principais'].get('max_por_emissor'),
                    "regras_json": reg
                }
                conn.table("regulamentos").upsert(payload, on_conflict="fundo_nome").execute()
                st.success("Regras salvas no banco de dados!")
                del st.session_state['temp_reg']
                st.rerun()

# --- 📊 ABA: DASHBOARD ---
elif menu == "📊 Dashboard":
    st.subheader(f"📊 Compliance: {fundo_ativo}")
    if fundo_ativo != "Nenhum cadastrado":
        c = conn.table("carteira_diaria").select("*").eq("fundo_nome", fundo_ativo).execute()
        r = conn.table("regulamentos").select("*").eq("fundo_nome", fundo_ativo).execute()
        
        if c.data and r.data:
            df_c = pd.DataFrame(c.data)
            reg = r.data[0]
            pl_total = df_c['valor_mercado'].sum()
            
            # Dashboard dinâmico baseado na meta salva
            meta = reg['meta_incentivadas'] if reg['meta_incentivadas'] else 0
            # Busca ativos que batem com o tipo principal do fundo
            v_alvo = df_c[df_c['tipo_ativo'].str.contains('Incentivada|Ação|Cota', case=False, na=False)]['valor_mercado'].sum()
            perc = (v_alvo / pl_total) * 100 if pl_total > 0 else 0
            
            col1, col2 = st.columns(2)
            col1.metric("PL Total", format_br(pl_total))
            status = "normal" if perc >= meta else "inverse"
            col2.metric(f"Enquadramento Alvo (Meta {meta}%)", f"{perc:.2f}%", delta=f"{perc-meta:.2f}%", delta_color=status)
            
            with st.expander("📝 Detalhes do Regulamento Salvo"):
                st.json(reg['regras_json'])
