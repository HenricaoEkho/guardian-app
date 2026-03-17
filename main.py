import streamlit as st
import pandas as pd
from st_supabase_connection import SupabaseConnection
import google.generativeai as genai
import json
from pypdf import PdfReader

# --- 1. CONFIGURAÇÃO E FORMATAÇÃO ---
st.set_page_config(page_title="Guardian Ultra v11", layout="wide", page_icon="🛡️")

def format_br(valor, prefixo="R$ "):
    try:
        val = float(valor)
        return f"{prefixo}{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except: return str(valor)

# --- 2. CONEXÃO IA HÍBRIDA (HYDRA) ---
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

# --- 3. SIDEBAR: NAVEGAÇÃO E FILTROS ---
st.sidebar.title("🛡️ Guardian Ultra v11")
try:
    res_f = conn.table("carteira_diaria").select("fundo_nome").execute()
    lista_fundos = sorted(list(set([i['fundo_nome'] for i in res_f.data]))) if res_f.data else []
except: lista_fundos = []

fundo_ativo = st.sidebar.selectbox("Fundo Ativo:", lista_fundos if lista_fundos else ["Nenhum cadastrado"])
menu = st.sidebar.radio("Ir para:", ["📊 Dashboard", "🤖 Importar Carteira", "📜 Regulamento", "📉 Gestão de Passivo"])

# --- 📊 ABA DASHBOARD (COMPLIANCE DINÂMICO) ---
if menu == "📊 Dashboard":
    st.subheader(f"📊 Painel de Compliance: {fundo_ativo}")
    if fundo_ativo != "Nenhum cadastrado":
        c = conn.table("carteira_diaria").select("*").eq("fundo_nome", fundo_ativo).order("data", desc=True).limit(200).execute()
        r = conn.table("regulamentos").select("*").eq("fundo_nome", fundo_ativo).execute()
        
        if c.data:
            df_c = pd.DataFrame(c.data)
            pl_total = df_c['valor_mercado'].sum()
            
            # Puxa metas extraídas pela IA no regulamento
            meta_inc = r.data[0]['meta_incentivadas'] if r.data else 85.0
            
            # Cálculo de Incentivadas (Filtro por texto no tipo_ativo)
            v_inc = df_c[df_c['tipo_ativo'].str.contains('Incentivada|Debênture|Infra', case=False, na=False)]['valor_mercado'].sum()
            perc_inc = (v_inc / pl_total) * 100 if pl_total > 0 else 0
            
            col1, col2, col3 = st.columns(3)
            col1.metric("Patrimônio Líquido", format_br(pl_total))
            
            status = "normal" if perc_inc >= meta_inc else "inverse"
            col2.metric(f"Enquadramento (Meta {meta_inc}%)", f"{perc_inc:.2f}%", 
                        delta=f"{perc_inc - meta_inc:.2f}% vs Meta", delta_color=status)
            
            if r.data and r.data[0].get('regras_json'):
                with st.expander("📝 Regras Específicas Detectadas pela IA"):
                    st.json(r.data[0]['regras_json'])
            
            st.divider()
            st.write("### Alocação Atual")
            st.bar_chart(df_c.groupby('tipo_ativo')['valor_mercado'].sum())
        else:
            st.info("Aguardando carga de carteira.")

# --- 🤖 ABA IMPORTAR CARTEIRA ---
elif menu == "🤖 Importar Carteira":
    st.subheader("📥 Carga de Ativos e Despesas")
    upload_c = st.file_uploader("Suba o Excel diário", type=['xlsx'])
    if upload_c:
        if st.button("🚀 Processar Carteira"):
            with st.spinner("IA extraindo ativos e despesas..."):
                try:
                    df = pd.read_excel(upload_c)
                    contexto = df.dropna(how='all').head(300).to_string()
                    prompt = f"""
                    Analista de Backoffice: Extraia Nome do Fundo, PL, Cota, Ativos e Despesas.
                    JSON: {{'nome_fundo': 'NOME', 'resumo': {{'pl': 0.0, 'cota': 0.0}}, 'ativos': [{{'ativo': 'NOME', 'valor_mercado': 0.0, 'tipo_ativo': 'TIPO'}}], 'despesas': [{{'item': 'NOME', 'valor': 0.0}}]}}
                    DADOS: {contexto}
                    """
                    res, motor = chamar_ia_hydra(prompt)
                    data = json.loads(res.text[res.text.find('{'):res.text.rfind('}')+1])
                    st.session_state['temp_c'] = data
                    st.success(f"Extraído via {motor}")
                    st.write(f"Fundo Detectado: **{data['nome_fundo']}**")
                    st.table(pd.DataFrame(data['ativos']).assign(valor_mercado=lambda x: x['valor_mercado'].apply(format_br)))
                except Exception as e: st.error(f"Erro: {e}")

        if 'temp_c' in st.session_state:
            if st.button("💾 Gravar no Supabase"):
                d = st.session_state['temp_c']
                for a in d['ativos']: a['fundo_nome'] = d['nome_fundo']
                desp = [{"fundo_nome": d['nome_fundo'], "item": ds['item'], "valor": -abs(ds['valor'])} for ds in d['despesas']]
                conn.table("carteira_diaria").insert(d['ativos']).execute()
                conn.table("despesas_diarias").insert(desp).execute()
                st.success("Integrado com sucesso!")
                del st.session_state['temp_c']
                st.rerun()

# --- 📜 ABA REGULAMENTO (A SAFAZ) ---
elif menu == "📜 Regulamento":
    st.subheader("📜 Inteligência de Regulamentos (Lei 12.431)")
    upload_reg = st.file_uploader("Suba o Regulamento (PDF)", type=['pdf'])
    
    if upload_reg:
        if st.button("🚀 Analisar Cláusulas de Compliance"):
            with st.spinner("IA lendo PDF e mapeando limites..."):
                try:
                    reader = PdfReader(upload_reg)
                    texto_completo = ""
                    for page in reader.pages[:15]: texto_completo += page.extract_text()
                    
                    # PROMPT OTIMIZADO PARA O JGP/INCENTIVADOS
                    prompt_reg = f"""
                    Aja como Compliance Officer. Analise o regulamento e identifique:
                    - NOME_FUNDO: Nome completo.
                    - LIMITES: Mínimo em Incentivados (Lei 12.431), Máximo Emissor Único, FIDC, FII, FIAGRO.
                    - OPERACIONAL: Alavancagem permitida? Resgate (D+?).
                    
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
                    st.success(f"Analisado via {motor}")
                except Exception as e: st.error(f"Erro no PDF: {e}")

        if 'temp_reg' in st.session_state:
            reg = st.session_state['temp_reg']
            st.write(f"### Regras Extraídas: {reg['nome_fundo']}")
            st.json(reg['regras'])
            
            # Lógica de Substituição Automática
            exists = conn.table("regulamentos").select("id").eq("fundo_nome", reg['nome_fundo']).execute()
            pode_salvar = True
            if exists.data:
                st.warning(f"O regulamento para '{reg['nome_fundo']}' já existe.")
                pode_salvar = st.checkbox("Sim, desejo substituir o regulamento anterior.")
            
            if pode_salvar and st.button("💾 Salvar Regulamento"):
                payload = {
                    "fundo_nome": reg['nome_fundo'],
                    "meta_incentivadas": reg['regras'].get('min_incentivadas', 85.0),
                    "limite_emissor": reg['regras'].get('max_emissor', 20.0),
                    "regras_json": reg['regras'],
                    "texto_regulamento": "Extraído via Guardian AI"
                }
                conn.table("regulamentos").upsert(payload, on_conflict="fundo_nome").execute()
                st.success("Regras salvas e vinculadas!")
                del st.session_state['temp_reg']
                st.rerun()
