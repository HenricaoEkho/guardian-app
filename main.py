import streamlit as st
import pandas as pd
from st_supabase_connection import SupabaseConnection
import google.generativeai as genai
import json
from pypdf import PdfReader

# --- 1. CONFIGURAÇÃO E FORMATAÇÃO BR ---
st.set_page_config(page_title="Guardian Joker v12", layout="wide", page_icon="🛡️")

def format_br(valor, prefixo="R$ "):
    try:
        val = float(valor)
        return f"{prefixo}{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except: return str(valor)

# --- 2. CONEXÃO IA HÍBRIDA (HYDRA) ---
gemini_key = st.secrets.get("GEMINI_API_KEY")
if gemini_key:
    genai.configure(api_key=gemini_key)

MODELOS = ['models/gemini-1.5-flash', 'models/gemini-3.1-flash-lite-preview', 'models/gemini-2.5-flash-lite']

def chamar_ia_hydra(prompt):
    for m in MODELOS:
        try:
            model = genai.GenerativeModel(m)
            return model.generate_content(prompt), m
        except: continue
    raise Exception("Sistema Hydra: Falha crítica na comunicação com os modelos de IA.")

conn = st.connection("supabase", type=SupabaseConnection)

# --- 3. SIDEBAR E NAVEGAÇÃO ---
st.sidebar.title("🛡️ Guardian Joker")
try:
    res_f = conn.table("carteira_diaria").select("fundo_nome").execute()
    lista_fundos = sorted(list(set([i['fundo_nome'] for i in res_f.data]))) if res_f.data else []
except: lista_fundos = []

fundo_ativo = st.sidebar.selectbox("Fundo Ativo:", lista_fundos if lista_fundos else ["Nenhum cadastrado"])
menu = st.sidebar.radio("Ir para:", ["📊 Dashboard", "🤖 Importar Carteira", "📜 Regulamento e Compliance", "📉 Gestão de Passivo"])

# --- 4. 📜 ABA: REGULAMENTO E COMPLIANCE (O CORINGA) ---
if menu == "📜 Regulamento e Compliance":
    st.subheader("📜 Inteligência de Regulamentos e Leis")
    st.info("A IA analisará a política de investimento e limites de risco de qualquer classe de fundo.")
    
    upload_reg = st.file_uploader("Suba o Regulamento (PDF)", type=['pdf'])
    
    if upload_reg:
        if st.button("🚀 Analisar Regras de Investimento"):
            with st.spinner("IA mapeando limites de enquadramento..."):
                try:
                    reader = PdfReader(upload_reg)
                    texto_completo = ""
                    # Lemos as páginas iniciais e anexos onde residem os limites [cite: 25, 173]
                    for page in reader.pages[:15]: texto_completo += page.extract_text()
                    
                    prompt_reg = f"""
                    Aja como um Auditor de Compliance Multimercado. Analise o regulamento de forma agnóstica.
                    
                    INSTRUÇÕES:
                    1. Identifique a Categoria do fundo (Ex: Infraestrutura Lei 12.431, Ações, Renda Fixa).
                    2. Localize a 'Política de Investimento' e 'Limites de Concentração'.
                    3. Extraia a meta mínima do ativo alvo (ex: 85% para infraestrutura).
                    4. Extraia o limite máximo por emissor único e alavancagem.
                    
                    Retorne APENAS JSON:
                    {{
                      "nome_fundo": "NOME_IDENTIFICADO",
                      "classe_fundo": "CATEGORIA",
                      "limites": {{
                        "meta_minima_ativo_alvo": 0.0,
                        "max_por_emissor": 0.0,
                        "alavancagem_permitida": false,
                        "detalhes": "Dicionário com todas as regras de diversificação encontradas"
                      }}
                    }}
                    TEXTO: {texto_completo[:8000]}
                    """
                    res, motor = chamar_ia_hydra(prompt_reg)
                    reg_data = json.loads(res.text[res.text.find('{'):res.text.rfind('}')+1])
                    st.session_state['temp_reg'] = reg_data
                    st.success(f"Análise finalizada via {motor}")

                except Exception as e: st.error(f"Erro no processamento: {e}")

        if 'temp_reg' in st.session_state:
            reg = st.session_state['temp_reg']
            st.write(f"### Regras de {reg['nome_fundo']} ({reg['classe_fundo']})")
            st.json(reg['limites'])
            
            if st.button("💾 Salvar Regulamento e Vincular"):
                payload = {
                    "fundo_nome": reg['nome_fundo'],
                    "meta_incentivadas": reg['limites'].get('meta_minima_ativo_alvo'),
                    "limite_emissor": reg['limites'].get('max_por_emissor'),
                    "regras_json": reg
                }
                conn.table("regulamentos").upsert(payload, on_conflict="fundo_nome").execute()
                st.success("Regras salvas e vinculadas ao Dashboard!")
                del st.session_state['temp_reg']
                st.rerun()

# --- 5. 📊 ABA: DASHBOARD (ADAPTÁVEL) ---
elif menu == "📊 Dashboard":
    st.subheader(f"📊 Compliance Dinâmico: {fundo_ativo}")
    if fundo_ativo != "Nenhum cadastrado":
        c = conn.table("carteira_diaria").select("*").eq("fundo_nome", fundo_ativo).execute()
        r = conn.table("regulamentos").select("*").eq("fundo_nome", fundo_ativo).execute()
        
        if c.data and r.data:
            df_c = pd.DataFrame(c.data)
            reg = r.data[0]
            pl_total = df_c['valor_mercado'].sum()
            
            # Dashboard usa a meta salva no regulamento específico (ex: 85% para JGP) [cite: 269]
            meta = reg['meta_incentivadas'] if reg['meta_incentivadas'] else 0.0
            v_alvo = df_c[df_c['tipo_ativo'].str.contains('Incentivada|Infra|Debênture|12.431', case=False, na=False)]['valor_mercado'].sum()
            perc = (v_alvo / pl_total) * 100 if pl_total > 0 else 0
            
            col1, col2 = st.columns(2)
            col1.metric("Patrimônio Líquido", format_br(pl_total))
            status = "normal" if perc >= meta else "inverse"
            col2.metric(f"Enquadramento (Meta {meta}%)", f"{perc:.2f}%", delta=f"{perc-meta:.2f}%", delta_color=status)
            
            with st.expander("📝 Detalhes das Regras Extraídas"):
                st.json(reg['regras_json'])
        else:
            st.info("Aguardando upload de Carteira e Regulamento.")

# --- ABA: IMPORTAR CARTEIRA (MANTIDA) ---
elif menu == "🤖 Importar Carteira":
    st.subheader("📥 Carga de Dados Diária")
    # [Código de importação Hydra de ativos e despesas mantido aqui]
