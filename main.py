import streamlit as st
import pandas as pd
from st_supabase_connection import SupabaseConnection
import google.generativeai as genai
import json
from pypdf import PdfReader

# --- 1. CONFIGURAÇÃO ---
st.set_page_config(page_title="Guardian Ultra v13.2", layout="wide", page_icon="🛡️")

def format_br(valor, prefixo="R$ "):
    try:
        val = float(valor)
        return f"{prefixo}{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except: return str(valor)

# --- 2. CONEXÃO IA ---
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
    raise Exception("Sistema Hydra: Todos os modelos falharam.")

conn = st.connection("supabase", type=SupabaseConnection)

# --- 3. SIDEBAR ---
st.sidebar.title("🛡️ Guardian Ultra v13.2")
try:
    res_f = conn.table("carteira_diaria").select("fundo_nome").execute()
    lista_fundos = sorted(list(set([i['fundo_nome'] for i in res_f.data]))) if res_f.data else []
except: lista_fundos = []

fundo_ativo = st.sidebar.selectbox("Fundo Ativo:", lista_fundos if lista_fundos else ["Nenhum cadastrado"])
menu = st.sidebar.radio("Ir para:", ["📊 Dashboard", "🤖 Importar Carteira", "📜 Regulamento e Compliance", "📉 Gestão de Passivo"])

# --- 4. 📊 DASHBOARD ---
if menu == "📊 Dashboard":
    st.subheader(f"📊 Monitor de Compliance: {fundo_ativo}")
    if fundo_ativo != "Nenhum cadastrado":
        c = conn.table("carteira_diaria").select("*").eq("fundo_nome", fundo_ativo).execute()
        r = conn.table("regulamentos").select("*").eq("fundo_nome", fundo_ativo).execute()
        
        if c.data:
            df_c = pd.DataFrame(c.data)
            st.metric("PL Total", format_br(df_c['valor_mercado'].sum()))
            
            if r.data:
                reg = r.data[0]
                # Busca no regras_json a regra id: 'min_deb_incentivadas'
                meta = 0.0
                for regra in reg['regras_json']:
                    if 'min' in regra['id']: meta = regra['limite_min']
                
                v_alvo = df_c[df_c['tipo_ativo'].str.contains('Incentivada|Infra|Debênture', case=False, na=False)]['valor_mercado'].sum()
                perc = v_alvo / df_c['valor_mercado'].sum() if not df_c.empty else 0
                
                st.metric(f"Compliance (Meta {meta*100:.0f}%)", f"{perc*100:.2f}%", delta=f"{(perc-meta)*100:.2f}%")
            
            st.dataframe(df_c[['ativo', 'valor_mercado', 'tipo_ativo']])
        else: st.warning("Sem dados de carteira.")

# --- 5. 🤖 IMPORTAR CARTEIRA ---
elif menu == "🤖 Importar Carteira":
    st.subheader("📥 Carga de Posição Diária")
    upload_c = st.file_uploader("Suba o Excel", type=['xlsx'])
    if upload_c and st.button("🚀 Processar Carteira"):
        with st.spinner("IA Extraindo..."):
            df = pd.read_excel(upload_c)
            res, motor = chamar_ia_hydra(f"JSON: {{'nome_fundo': 'NOME', 'ativos': [{{'ativo': 'NOME', 'valor_mercado': 0.0, 'tipo_ativo': 'TIPO'}}]}} DADOS: {df.head(200).to_string()}")
            data = json.loads(res.text[res.text.find('{'):res.text.rfind('}')+1])
            st.session_state['temp_c'] = data
            st.success(f"Extraído via {motor}")
            st.table(pd.DataFrame(data['ativos']))

# --- 6. 📜 REGULAMENTO E COMPLIANCE (O PROMPT "MUUITO EFICAZ") ---
elif menu == "📜 Regulamento e Compliance":
    st.subheader("📜 Arquiteto de Compliance")
    upload_reg = st.file_uploader("Suba o PDF", type=['pdf'])
    
    if upload_reg and st.button("🚀 Mapear Compliance"):
        with st.spinner("Analisando Anexo I e limites..."):
            try:
                reader = PdfReader(upload_reg)
                texto = "".join([p.extract_text() for p in reader.pages[:20]])
                
                # SUPER PROMPT PARA CAPTURAR 85%/95% E IGNORAR 67%
                super_prompt = f"""
                Você é um Engenheiro de Compliance de Fundos (Resolução CVM 175). Analise o regulamento.
                
                INSTRUÇÕES CRÍTICAS:
                1. Ignore regras de 'carência' ou 'período inicial' (ex: 67% nos primeiros anos). Busque o limite PERMANENTE.
                2. Diferencie: 
                   - Limite Tributário (Lei 12.431): Geralmente 95% em ativos de infraestrutura.
                   - Limite de Política de Investimento (Capítulo 6 do Anexo I): Geralmente 85% ou 95%.
                3. Priorize o maior rigor (se houver conflito entre 85% e 95%, registre o 95% como meta tributária).
                4. Crie o 'mapa_ativos' mapeando CNPJs citados para categorias.
                
                JSON ESPERADO:
                {{
                  "fundo": "NOME", "cnpj": "CNPJ", "descricao": "Mandato",
                  "regras": [
                    {{ "id": "min_deb_incentivadas", "limite_min": 0.95, "tipo": "minimo_percentual", "categorias": ["incentivadas"] }}
                  ],
                  "mapa_ativos": {{ "CNPJ_OU_NOME": "categoria" }}
                }}
                TEXTO: {texto[:10000]}
                """
                res, motor = chamar_ia_hydra(super_prompt)
                data = json.loads(res.text[res.text.find('{'):res.text.rfind('}')+1])
                st.session_state['schema_reg'] = data
                st.json(data)
            except Exception as e: st.error(f"Erro: {e}")

    if 'schema_reg' in st.session_state and st.button("💾 Salvar Estrutura"):
        d = st.session_state['schema_reg']
        payload = {{
            "fundo_nome": d.get('fundo'), "cnpj": d.get('cnpj'), "descricao_mandato": d.get('descricao'),
            "regras_json": d.get('regras'), "mapa_ativos_json": d.get('mapa_ativos'), "texto_bruto": "v13.2"
        }}
        conn.table("regulamentos").upsert(payload, on_conflict="fundo_nome").execute()
        st.success("Salvo!")
