import streamlit as st
import pandas as pd
from st_supabase_connection import SupabaseConnection
import google.generativeai as genai
import json
from pypdf import PdfReader

# --- CONFIGURAÇÃO ---
st.set_page_config(page_title="Guardian Auditor v14", layout="wide", page_icon="🛡️")

def format_br(valor, prefixo="R$ "):
    try:
        val = float(valor)
        return f"{prefixo}{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except: return str(valor)

# --- CONEXÃO IA ---
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
    raise Exception("Falha total nos modelos de IA.")

conn = st.connection("supabase", type=SupabaseConnection)

# --- SIDEBAR ---
st.sidebar.title("🛡️ Guardian Auditor")
try:
    res_f = conn.table("carteira_diaria").select("fundo_nome").execute()
    lista_fundos = sorted(list(set([i['fundo_nome'] for i in res_f.data]))) if res_f.data else []
except: lista_fundos = []

fundo_ativo = st.sidebar.selectbox("Selecionar Fundo:", lista_fundos if lista_fundos else ["Nenhum cadastrado"])
menu = st.sidebar.radio("Navegação:", ["📊 Dashboard", "🤖 Importar Carteira", "📜 Regulamento e Compliance"])

# --- 📊 DASHBOARD (SINCRONIA TOTAL) ---
if menu == "📊 Dashboard":
    st.subheader(f"📊 Painel de Compliance: {fundo_ativo}")
    if fundo_ativo != "Nenhum cadastrado":
        c = conn.table("carteira_diaria").select("*").eq("fundo_nome", fundo_ativo).execute()
        r = conn.table("regulamentos").select("*").eq("fundo_nome", fundo_ativo).execute()
        
        if c.data:
            df_c = pd.DataFrame(c.data)
            pl_total = df_c['valor_mercado'].sum()
            st.metric("Patrimônio Líquido Total", format_br(pl_total))
            
            if r.data:
                reg = r.data[0]
                meta = reg['meta_minima_alvo'] if reg['meta_minima_alvo'] else 0.0
                
                # Identifica ativos que batem com o mandato (Incentivadas, Master, etc)
                v_alvo = df_c[df_c['tipo_ativo'].str.contains('Incentivada|Infra|Master|Debênture', case=False, na=False)]['valor_mercado'].sum()
                perc = v_alvo / pl_total if pl_total > 0 else 0
                
                status = "normal" if perc >= meta else "inverse"
                st.metric(f"Enquadramento Alvo (Meta {meta*100:.1f}%)", f"{perc*100:.2f}%", 
                          delta=f"{(perc-meta)*100:.2f}% vs Regulamento", delta_color=status)
            
            st.write("### Itens em Carteira")
            st.dataframe(df_c[['ativo', 'valor_mercado', 'tipo_ativo']].assign(valor_mercado=lambda x: x['valor_mercado'].apply(format_br)))
        else: st.warning("⚠️ Sem carteira importada para este fundo.")

# --- 🤖 IMPORTAÇÃO ---
elif menu == "🤖 Importar Carteira":
    st.subheader("📥 Carga Diária de Ativos")
    upload_c = st.file_uploader("Suba o Excel", type=['xlsx'])
    if upload_c and st.button("🚀 Processar"):
        with st.spinner("IA Extraindo..."):
            df = pd.read_excel(upload_c)
            prompt = f"JSON: {{'nome_fundo': 'NOME', 'ativos': [{{'ativo': 'NOME', 'valor_mercado': 0.0, 'tipo_ativo': 'TIPO'}}]}} DADOS: {df.head(250).to_string()}"
            res, motor = chamar_ia_hydra(prompt)
            data = json.loads(res.text[res.text.find('{'):res.text.rfind('}')+1])
            st.session_state['temp_c'] = data
            st.success(f"Extraído via {motor}")
            st.table(pd.DataFrame(data['ativos']))

    if 'temp_c' in st.session_state and st.button("💾 Salvar"):
        d = st.session_state['temp_c']
        for a in d['ativos']: a['fundo_nome'] = d['nome_fundo']
        conn.table("carteira_diaria").insert(d['ativos']).execute()
        st.success("Salvo!")
        del st.session_state['temp_c']
        st.rerun()

# --- 📜 REGULAMENTO (O PROMPT ANTIVÍES) ---
elif menu == "📜 Regulamento e Compliance":
    st.subheader("📜 Perícia de Regulamentos")
    upload_reg = st.file_uploader("Suba o PDF do Regulamento", type=['pdf'])
    
    if upload_reg and st.button("🚀 Iniciar Perícia IA"):
        with st.spinner("Analisando cláusulas permanentes..."):
            try:
                reader = PdfReader(upload_reg)
                texto = "".join([p.extract_text() for p in reader.pages[:20]])
                
                # O PROMPT PERFEITO: Diferencia carência de regra permanente
                auditoria_prompt = f"""
                Você é um Perito de Compliance da CVM. Analise o regulamento sem nenhum viés prévio.
                
                REGRAS DE OURO:
                1. IGNORE prazos de carência (ex: carência de 2 anos para 67%). Busque o limite PERMANENTE.
                2. LOCALIZE no Anexo I o 'Limite Mínimo de Ativos de Infraestrutura'[cite: 173, 269].
                3. BUSQUE no capítulo de tributação o limite para isenção (Lei 12.431), geralmente 95%.
                4. MAPEIE no Anexo I a tabela de 'Limites de Concentração Máxima' (Emissor Único, FII, FIDC)[cite: 316, 319].
                
                Retorne APENAS JSON:
                {{
                  "fundo": "NOME_OFICIAL",
                  "classe": "CATEGORIA",
                  "meta_permanente": 0.0, 
                  "limite_emissor": 0.0,
                  "mapa_ativos": {{ "CNPJ/NOME": "CATEGORIA" }},
                  "resumo_regras": [{{ "id": "id", "limite": 0.0, "texto": "descrição" }}]
                }}
                TEXTO: {texto[:10000]}
                """
                res, motor = chamar_ia_hydra(auditoria_prompt)
                data = json.loads(res.text[res.text.find('{'):res.text.rfind('}')+1])
                st.session_state['pericia_reg'] = data
                st.json(data)
            except Exception as e: st.error(f"Erro: {e}")

    if 'pericia_reg' in st.session_state and st.button("💾 Salvar Inteligência"):
        d = st.session_state['pericia_reg']
        payload = {
            "fundo_nome": d['fundo'],
            "classe_fundo": d['classe'],
            "meta_minima_alvo": d['meta_permanente'],
            "limite_emissor": d['limite_emissor'],
            "regras_json": d['resumo_regras'],
            "mapa_ativos_json": d['mapa_ativos']
        }
        conn.table("regulamentos").upsert(payload, on_conflict="fundo_nome").execute()
        st.success("Cérebro do Fundo Atualizado!")
        del st.session_state['pericia_reg']
        st.rerun()
