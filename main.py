import streamlit as st
import pandas as pd
from st_supabase_connection import SupabaseConnection
import google.generativeai as genai
import json
from pypdf import PdfReader

# --- 1. SETUP ---
st.set_page_config(page_title="Guardian Ultra v19", layout="wide", page_icon="🛡️")

def format_br(valor, prefixo="R$ "):
    try:
        val = float(valor)
        return f"{prefixo}{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except: return str(valor)

# --- 2. IA ---
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
    raise Exception("IA Offline.")

conn = st.connection("supabase", type=SupabaseConnection)

# --- 3. SIDEBAR ---
st.sidebar.title("🛡️ Guardian Ultra v19")
try:
    res_f = conn.table("regulamentos").select("fundo_nome").execute()
    lista_fundos = sorted(list(set([i['fundo_nome'] for i in res_f.data]))) if res_f.data else []
except: lista_fundos = []

fundo_ativo = st.sidebar.selectbox("Fundo em Análise:", lista_fundos if lista_fundos else ["Nenhum"])
menu = st.sidebar.radio("Navegação:", ["📊 Dashboard", "🤖 Importar Carteira", "📜 Regulamento e Compliance"])

# --- 4. DASHBOARD ---
if menu == "📊 Dashboard":
    st.subheader(f"📊 Compliance: {fundo_ativo}")
    if fundo_ativo != "Nenhum":
        c = conn.table("carteira_diaria").select("*").eq("fundo_nome", fundo_ativo).execute()
        r = conn.table("regulamentos").select("*").eq("fundo_nome", fundo_ativo).execute()
        
        if c.data:
            df_c = pd.DataFrame(c.data)
            pl_total = df_c['valor_mercado'].sum()
            st.metric("Patrimônio Líquido Total", format_br(pl_total))
            
            if r.data:
                reg = r.data[0]
                st.write("### ✅ Validação de Limites")
                for regra in reg['regras_json']:
                    v_soma = df_c[df_c['tipo_ativo'].str.lower().isin([cat.lower() for cat in regra['categorias']])]['valor_mercado'].sum()
                    perc = v_soma / pl_total if pl_total > 0 else 0
                    valido = (perc >= regra['limite_min']) if regra['tipo'] == 'minimo_percentual' else (perc <= regra['limite_max'])
                    cor = "green" if valido else "red"
                    st.markdown(f"**{regra['id']}**: :{cor}[{perc*100:.2f}%] (Meta: {regra['tipo'].replace('_', ' ')})")
            
            st.write("### 📄 Posição Atual")
            st.dataframe(df_c[['ativo', 'valor_mercado', 'tipo_ativo']])
        else: st.warning("Sem carteira no banco para este fundo.")

# --- 5. IMPORTAÇÃO (MOTOR CLASSIFICADOR) ---
elif menu == "🤖 Importar Carteira":
    st.subheader("📥 Carga de Dados e Inteligência de Ativos")
    upload_c = st.file_uploader("Excel da Carteira", type=['xlsx'])
    
    if upload_c and st.button("🚀 Processar com IA"):
        with st.spinner("Analisando e Classificando Ativos..."):
            df = pd.read_excel(upload_c)
            contexto = df.dropna(how='all').head(400).to_string()
            
            # PROMPT BLINDADO PARA TIPO_ATIVO
            prompt_c = f"""
            Você é um Analista de Risco. Extraia Nome do Fundo, PL, Cota, Ativos e Despesas.
            CLASSIFICAÇÃO DO TIPO_ATIVO: Identifique se é 'Debênture Incentivada', 'LFT', 'Cota de FIDC', 'Ação' ou 'Disponibilidade'. Não use apenas 'Cota'.
            
            JSON: {{
              'nome_fundo': 'NOME', 
              'resumo': {{'pl': 0.0, 'cota': 0.0}}, 
              'ativos': [{{'ativo': 'NOME', 'valor_mercado': 0.0, 'tipo_ativo': 'CLASSIFICAÇÃO REAL'}}], 
              'despesas': [{{'item': 'NOME', 'valor': 0.0}}]
            }}
            DADOS: {contexto}
            """
            res, motor = chamar_ia_hydra(prompt_c)
            data = json.loads(res.text[res.text.find('{'):res.text.rfind('}')+1])
            
            for d in data['despesas']: d['valor'] = -abs(float(d['valor']))
            st.session_state['temp_c'] = data
            st.success(f"Extraído via {motor}")
            
            c1, c2 = st.columns(2)
            c1.metric("PL Identificado", format_br(data['resumo']['pl']))
            c2.metric("Cota", f"R$ {data['resumo']['cota']:.6f}")
            
            st.write("### Prévia de Classificação")
            st.table(pd.DataFrame(data['ativos']).assign(valor_mercado=lambda x: x['valor_mercado'].apply(format_br)))

    if 'temp_c' in st.session_state and st.button("💾 Gravar no Supabase"):
        d = st.session_state['temp_c']
        fn = d['nome_fundo']
        for a in d['ativos']: a['fundo_nome'] = fn
        for ds in d['despesas']: ds['fundo_nome'] = fn
        
        # INSERT REAL NO BANCO
        conn.table("carteira_diaria").insert(d['ativos']).execute()
        if d['despesas']: conn.table("despesas_diarias").insert(d['despesas']).execute()
        st.success(f"Dados de {fn} gravados com sucesso!")
        del st.session_state['temp_c']
        st.rerun()

# --- 6. REGULAMENTO (CONSERTO DO PAYLOAD) ---
elif menu == "📜 Regulamento e Compliance":
    st.subheader("📜 Arquiteto de Compliance")
    upload_reg = st.file_uploader("PDF do Regulamento", type=['pdf'])
    
    if upload_reg and st.button("🚀 Mapear Fundo"):
        with st.spinner("Lendo Anexo I..."):
            reader = PdfReader(upload_reg)
            texto = "".join([p.extract_text() for p in reader.pages[:40]])
            
            super_prompt = f"""
            Auditor CVM 175: Transforme o regulamento em motor matemático JSON.
            IMPORTANTE: 95% vira 0.95. Identifique se é 'minimo_percentual' ou 'maximo_percentual'.
            JSON: {{
              "fundo": "NOME", "cnpj": "CNPJ", "mandato": "MANDATO",
              "regras": [{{ "id": "ID", "tipo": "minimo_percentual", "limite_min": 0.0, "categorias": ["CAT"] }}],
              "mapa_ativos": {{ "TERMO": "CAT" }},
              "categorias_definidas": {{ "CAT": "DESC" }}
            }}
            TEXTO: {texto[:25000]}
            """
            res, motor = chamar_ia_hydra(super_prompt)
            data = json.loads(res.text[res.text.find('{'):res.text.rfind('}')+1])
            st.session_state['schema_v19'] = data
            st.json(data)

    if 'schema_v19' in st.session_state and st.button("💾 Ativar Compliance no Banco"):
        d = st.session_state['schema_v19']
        payload = {
            "fundo_nome": d.get('fundo'),
            "cnpj": d.get('cnpj'),
            "descricao_mandato": d.get('mandato'),
            "regras_json": d['regras'],
            "mapa_ativos_json": d['mapa_ativos'],
            "categorias_definidas": d['categorias_definidas']
        }
        conn.table("regulamentos").upsert(payload, on_conflict="fundo_nome").execute()
        st.success("Regulamento salvo no Supabase!")
        del st.session_state['schema_v19']
        st.rerun()
