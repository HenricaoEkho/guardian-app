import streamlit as st
import pandas as pd
from st_supabase_connection import SupabaseConnection
import google.generativeai as genai
import json
from pypdf import PdfReader

# --- CONFIGURAÇÃO E FORMATAÇÃO ---
st.set_page_config(page_title="Guardian Ultra v10", layout="wide", page_icon="🛡️")

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
    'models/gemini-2.5-flash-lite', 
    'models/gemini-3.1-flash-lite-preview'
]

def chamar_ia_hydra(prompt):
    for m in MODELOS:
        try:
            model = genai.GenerativeModel(m)
            return model.generate_content(prompt), m
        except: continue
    raise Exception("Sistema Hydra: Todos os modelos falharam.")

conn = st.connection("supabase", type=SupabaseConnection)

# --- SIDEBAR: NAVEGAÇÃO E SELEÇÃO DE FUNDO ---
st.sidebar.title("🛡️ Guardian Ultra")
try:
    res_f = conn.table("carteira_diaria").select("fundo_nome").execute()
    lista_fundos = sorted(list(set([i['fundo_nome'] for i in res_f.data]))) if res_f.data else []
except: lista_fundos = []

fundo_ativo = st.sidebar.selectbox("Fundo em Análise:", lista_fundos if lista_fundos else ["Nenhum cadastrado"])
menu = st.sidebar.radio("Ir para:", ["📊 Dashboard", "🤖 Importar Carteira", "📜 Regulamento", "📉 Gestão de Passivo"])

# --- ABA 1: DASHBOARD (COMPLIANCE) ---
if menu == "📊 Dashboard":
    st.subheader(f"📊 Painel de Compliance: {fundo_ativo}")
    if fundo_ativo != "Nenhum cadastrado":
        c = conn.table("carteira_diaria").select("*").eq("fundo_nome", fundo_ativo).execute()
        r = conn.table("regulamentos").select("*").eq("fundo_nome", fundo_ativo).execute()
        
        if c.data:
            df_c = pd.DataFrame(c.data)
            pl_total = df_c['valor_mercado'].sum()
            
            # Busca metas do regulamento ou usa padrão
            meta_inc = r.data[0]['meta_incentivadas'] if r.data else 85.0
            
            v_inc = df_c[df_c['tipo_ativo'].str.contains('Incentivada', case=False, na=False)]['valor_mercado'].sum()
            perc_inc = (v_inc / pl_total) * 100 if pl_total > 0 else 0
            
            col1, col2, col3 = st.columns(3)
            col1.metric("Patrimônio Líquido", format_br(pl_total))
            
            status = "normal" if perc_inc >= meta_inc else "inverse"
            col2.metric(f"Enquadramento (Mín {meta_inc}%)", f"{perc_inc:.2f}%", 
                        delta=f"{perc_inc - meta_inc:.2f}%", delta_color=status)
            
            if r.data and r.data[0].get('regras_json'):
                with st.expander("📝 Todas as Regras Extraídas do Regulamento"):
                    st.json(r.data[0]['regras_json'])
            
            st.divider()
            st.write("### Composição Atual")
            st.bar_chart(df_c.groupby('tipo_ativo')['valor_mercado'].sum())
        else:
            st.info("Importe uma carteira para ver a análise.")

# --- ABA 2: IMPORTAR CARTEIRA ---
elif menu == "🤖 Importar Carteira":
    st.subheader("📥 Carga de Ativos e Despesas")
    upload_c = st.file_uploader("Suba o Excel diário", type=['xlsx'])
    if upload_c:
        if st.button("🚀 Processar Carteira"):
            with st.spinner("IA extraindo dados..."):
                df = pd.read_excel(upload_c)
                contexto = df.dropna(how='all').head(300).to_string()
                prompt = f"Analise e extraia para JSON: {{'nome_fundo': 'NOME', 'resumo': {{'pl': 0.0, 'cota': 0.0}}, 'ativos': [{{'ativo': 'NOME', 'valor_mercado': 0.0, 'tipo_ativo': 'TIPO'}}], 'despesas': [{{'item': 'NOME', 'valor': 0.0}}]}} DADOS: {contexto}"
                res, motor = chamar_ia_hydra(prompt)
                data = json.loads(res.text[res.text.find('{'):res.text.rfind('}')+1])
                st.session_state['temp_c'] = data
                st.success(f"Extraído via {motor}")
                st.write(f"Fundo: {data['nome_fundo']}")
                st.table(pd.DataFrame(data['ativos']).assign(valor_mercado=lambda x: x['valor_mercado'].apply(format_br)))

        if 'temp_c' in st.session_state:
            if st.button("💾 Gravar no Supabase"):
                d = st.session_state['temp_c']
                for a in d['ativos']: a['fundo_nome'] = d['nome_fundo']
                desp = [{"fundo_nome": d['nome_fundo'], "item": ds['item'], "valor": -abs(ds['valor'])} for ds in d['despesas']]
                conn.table("carteira_diaria").insert(d['ativos']).execute()
                conn.table("despesas_diarias").insert(desp).execute()
                st.success("Carteira Gravada!")
                del st.session_state['temp_c']
                st.rerun()

# --- ABA 3: REGULAMENTO (A "SAFAZ") ---
elif menu == "📜 Regulamento":
    st.subheader("📜 Inteligência de Regulamentos")
    upload_reg = st.file_uploader("Suba o Regulamento (PDF)", type=['pdf'])
    
    if upload_reg:
        if st.button("🚀 Ler e Extrair Regras"):
            with st.spinner("IA lendo PDF e identificando cláusulas..."):
                # Extração de texto do PDF
                reader = PdfReader(upload_reg)
                texto_completo = ""
                for page in reader.pages[:10]: # Lemos as primeiras 10 páginas (onde ficam as regras)
                    texto_completo += page.extract_text()
                
                prompt_reg = f"""
                Você é um Advogado de Compliance. Extraia do texto do regulamento:
                1. NOME_FUNDO: Nome oficial.
                2. REGRAS: Identifique limites de % (Incentivadas, Emissor Único, Ações, etc).
                
                Retorne APENAS JSON:
                {{
                  "nome_fundo": "NOME",
                  "regras": {{ "min_incentivadas": 85.0, "max_emissor": 20.0, "outras_regras": "texto" }}
                }}
                TEXTO: {texto_completo[:5000]}
                """
                res, motor = chamar_ia_hydra(prompt_reg)
                reg_data = json.loads(res.text[res.text.find('{'):res.text.rfind('}')+1])
                st.session_state['temp_reg'] = reg_data
                st.success(f"Regulamento analisado via {motor}")

        if 'temp_reg' in st.session_state:
            reg = st.session_state['temp_reg']
            st.write(f"### Regras de {reg['nome_fundo']}")
            st.json(reg['regras'])
            
            # Lógica de Substituição
            exists = conn.table("regulamentos").select("id").eq("fundo_nome", reg['nome_fundo']).execute()
            confirmar = True
            if exists.data:
                st.warning(f"O fundo '{reg['nome_fundo']}' já possui regras. Deseja sobrescrever?")
                confirmar = st.checkbox("Sim, substituir regras antigas")
            
            if confirmar and st.button("💾 Salvar Regulamento"):
                payload = {
                    "fundo_nome": reg['nome_fundo'],
                    "meta_incentivadas": reg['regras'].get('min_incentivadas', 85.0),
                    "limite_emissor": reg['regras'].get('max_emissor', 20.0),
                    "regras_json": reg['regras'],
                    "texto_regulamento": "Conteúdo extraído do PDF"
                }
                conn.table("regulamentos").upsert(payload, on_conflict="fundo_nome").execute()
                st.success("Regulamento salvo!")
                del st.session_state['temp_reg']
