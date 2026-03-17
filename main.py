import streamlit as st
import pandas as pd
from st_supabase_connection import SupabaseConnection
import google.generativeai as genai
import json
from pypdf import PdfReader

# --- CONFIGURAÇÃO E FORMATAÇÃO ---
st.set_page_config(page_title="Guardian Ultra v11", layout="wide", page_icon="🛡️")

def format_br(valor, prefixo="R$ "):
    try:
        val = float(valor)
        return f"{prefixo}{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except: return str(valor)

# --- CONEXÃO IA HÍBRIDA (HYDRA) ---
gemini_key = st.secrets.get("GEMINI_API_KEY")
if gemini_key:
    genai.configure(api_key=gemini_key)

MODELOS = [
    'models/gemini-1.5-flash', 
    'models/gemini-3.1-flash-lite-preview',
    'models/gemini-2.5-flash-lite'
]

def chamar_ia_hydra(prompt):
    for m in MODELOS:
        try:
            model = genai.GenerativeModel(m)
            return model.generate_content(prompt), m
        except: continue
    raise Exception("Sistema Hydra: Todos os modelos falharam ou cota atingida.")

conn = st.connection("supabase", type=SupabaseConnection)

# --- SIDEBAR ---
st.sidebar.title("🛡️ Guardian Ultra")
try:
    res_f = conn.table("carteira_diaria").select("fundo_nome").execute()
    lista_fundos = sorted(list(set([i['fundo_nome'] for i in res_f.data]))) if res_f.data else []
except: lista_fundos = []

fundo_ativo = st.sidebar.selectbox("Fundo Ativo:", lista_fundos if lista_fundos else ["Nenhum cadastrado"])
menu = st.sidebar.radio("Ir para:", ["📊 Dashboard", "🤖 Importar Carteira", "📜 Regulamento", "📉 Gestão de Passivo"])

# --- ABA 📊 DASHBOARD (COMPLIANCE DINÂMICO) ---
if menu == "📊 Dashboard":
    st.subheader(f"📊 Painel de Compliance: {fundo_ativo}")
    if fundo_ativo != "Nenhum cadastrado":
        c = conn.table("carteira_diaria").select("*").eq("fundo_nome", fundo_ativo).order("data", desc=True).limit(200).execute()
        r = conn.table("regulamentos").select("*").eq("fundo_nome", fundo_ativo).execute()
        
        if c.data:
            df_c = pd.DataFrame(c.data)
            pl_total = df_c['valor_mercado'].sum()
            
            # Busca metas extraídas pela IA no regulamento ou usa padrão
            meta_inc = r.data[0]['meta_incentivadas'] if r.data else 85.0
            
            # Cálculo de Incentivadas (Filtro flexível no tipo_ativo)
            v_inc = df_c[df_c['tipo_ativo'].str.contains('Incentivada|Debênture|Infra|12.431', case=False, na=False)]['valor_mercado'].sum()
            perc_inc = (v_inc / pl_total) * 100 if pl_total > 0 else 0
            
            col1, col2, col3 = st.columns(3)
            col1.metric("Patrimônio Líquido", format_br(pl_total))
            
            status = "normal" if perc_inc >= meta_inc else "inverse"
            col2.metric(f"Enquadramento (Meta {meta_inc}%)", f"{perc_inc:.2f}%", 
                        delta=f"{perc_inc - meta_inc:.2f}% vs Meta", delta_color=status)
            
            if r.data and r.data[0].get('regras_json'):
                with st.expander("📝 Todas as Regras Extraídas do Regulamento"):
                    st.json(r.data[0]['regras_json'])
            
            st.divider()
            st.write("### Alocação Atual")
            st.bar_chart(df_c.groupby('tipo_ativo')['valor_mercado'].sum())
        else:
            st.info("Importe a carteira para ver a análise.")

# --- ABA 🤖 IMPORTAR CARTEIRA ---
elif menu == "🤖 Importar Carteira":
    st.subheader("📥 Carga de Ativos")
    # [Mantém o código do Hydra anterior para importar carteiras Excel]
    st.write("Suba o Excel diário da carteira.")

# --- ABA 📜 REGULAMENTO (A "SAFAZ") ---
elif menu == "📜 Regulamento":
    st.subheader("📜 Inteligência de Regulamentos (Lei 12.431)")
    upload_reg = st.file_uploader("Suba o Regulamento (PDF)", type=['pdf'])
    
    if upload_reg:
        if st.button("🚀 Analisar Cláusulas de Compliance"):
            with st.spinner("IA lendo PDF e mapeando limites..."):
                try:
                    # Extração real do PDF
                    reader = PdfReader(upload_reg)
                    texto_completo = ""
                    for page in reader.pages[:15]: # Lemos as primeiras 15 páginas
                        texto_completo += page.extract_text()
                    
                    # PROMPT OTIMIZADO PARA APRENDIZADO
                    prompt_reg = f"""
                    Você é um Advogado de Compliance de Fundos Sênior. Analise o regulamento.
                    Não use parâmetros padrão. Aprenda as regras específicas com base no texto.
                    Procure pelo anexo e pelas tabelas de 'Limites de Concentração Máxima' e 'Limites de Investimento em Classes de Cotas'.
                    Identifique limites operacionais e de diversificação percentuais (máximos e mínimos).
                    Verifique se o fundo é incentivado (Lei 12.431) e extraia o percentual mínimo de ativos de infraestrutura (ex: 85% ou 95%).
                    
                    Retorne APENAS JSON:
                    {{
                      "nome_fundo": "NOME",
                      "regras": {{ "min_incentivadas": 85.0, "max_emissor": 20.0, "detalhes": "JSON flexível com todas as regras encontradas" }}
                    }}
                    TEXTO: {texto_completo[:8000]}
                    """
                    res, motor = chamar_ia_hydra(prompt_reg)
                    reg_data = json.loads(res.text[res.text.find('{'):res.text.rfind('}')+1])
                    st.session_state['temp_reg'] = reg_data
                    st.success(f"Regulamento analisado via {motor}")
                except Exception as e:
                    st.error(f"Erro no processamento IA: {e}")

        if 'temp_reg' in st.session_state:
            reg = st.session_state['temp_reg']
            st.write(f"### Regras Extraídas para: {reg['nome_fundo']}")
            st.json(reg['regras'])
            
            # Lógica de Substituição Inteligente
            exists = conn.table("regulamentos").select("id").eq("fundo_nome", reg['nome_fundo']).execute()
            pode_salvar = True
            
            if exists.data:
                st.warning(f"O fundo '{reg['nome_fundo']}' já existe. Deseja substituir?")
                pode_salvar = st.checkbox("Confirmar substituição das regras")
            
            if pode_salvar and st.button("💾 Salvar Regulamento"):
                payload = {
                    "fundo_nome": reg['nome_fundo'],
                    "meta_incentivadas": reg['regras'].get('min_incentivadas', 85.0),
                    "limite_emissor": reg['regras'].get('max_emissor', 20.0),
                    "regras_json": reg['regras'],
                    "texto_regulamento": "Conteúdo extraído via IA Hydra"
                }
                conn.table("regulamentos").upsert(payload, on_conflict="fundo_nome").execute()
                st.success("Regulamento salvo!")
                del st.session_state['temp_reg']
                st.rerun()
