import streamlit as st
import pandas as pd
from st_supabase_connection import SupabaseConnection
import google.generativeai as genai
import json
from pypdf import PdfReader

# --- 1. CONFIGURAÇÃO ---
st.set_page_config(page_title="Guardian Auditor v16", layout="wide", page_icon="🛡️")

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
    raise Exception("Modelos de IA indisponíveis.")

conn = st.connection("supabase", type=SupabaseConnection)

# --- 3. SIDEBAR ---
st.sidebar.title("🛡️ Guardian Auditor v16")
try:
    res_f = conn.table("regulamentos").select("fundo_nome").execute()
    lista_fundos = sorted(list(set([i['fundo_nome'] for i in res_f.data]))) if res_f.data else []
except: lista_fundos = []

fundo_ativo = st.sidebar.selectbox("Fundo Ativo:", lista_fundos if lista_fundos else ["Nenhum"])
menu = st.sidebar.radio("Ir para:", ["📊 Dashboard", "🤖 Importar Carteira", "📜 Regulamento e Compliance"])

# --- 4. 📊 DASHBOARD (COMPLIANCE MATEMÁTICO) ---
if menu == "📊 Dashboard":
    st.subheader(f"📊 Compliance em Tempo Real: {fundo_ativo}")
    if fundo_ativo != "Nenhum":
        r = conn.table("regulamentos").select("*").eq("fundo_nome", fundo_ativo).execute()
        c = conn.table("carteira_diaria").select("*").eq("fundo_nome", fundo_ativo).execute()
        
        if r.data and c.data:
            reg = r.data[0]
            df_c = pd.DataFrame(c.data)
            pl_total = df_c['valor_mercado'].sum()
            
            st.metric("PL Total do Fundo", format_br(pl_total))
            
            # Executa a validação das Gavetas Matemáticas
            st.write("### ✅ Status de Enquadramento")
            for regra in reg['regras_matematicas']:
                # Soma ativos que batem com as categorias da regra
                v_soma = df_c[df_c['tipo_ativo'].isin(regra['categorias'])]['valor_mercado'].sum()
                perc_atual = v_soma / pl_total if pl_total > 0 else 0
                
                # Lógica matemática pura
                if regra['tipo'] == 'minimo_percentual':
                    sucesso = perc_atual >= regra['limite_min']
                    desc = f"Mínimo de {regra['limite_min']*100:.0f}%"
                elif regra['tipo'] == 'maximo_percentual':
                    sucesso = perc_atual <= regra['limite_max']
                    desc = f"Máximo de {regra['limite_max']*100:.0f}%"
                
                cor = "green" if sucesso else "red"
                st.markdown(f"**{regra['id']}**: :{cor}[{perc_atual*100:.2f}%] ({desc})")

            st.write("### 📄 Detalhes da Carteira")
            st.dataframe(df_c[['ativo', 'valor_mercado', 'tipo_ativo']])
        else: st.info("Aguardando carga de dados.")

# --- 5. 🤖 IMPORTAÇÃO (DICIONÁRIO RAIZ) ---
elif menu == "🤖 Importar Carteira":
    st.subheader("📥 Carga de Posição Diária")
    upload_c = st.file_uploader("Suba o Excel", type=['xlsx'])
    if upload_c and st.button("🚀 Processar"):
        with st.spinner("Classificando ativos via Dicionário do Regulamento..."):
            df = pd.read_excel(upload_c)
            # IA usa o mapa_ativos do regulamento para classificar o Excel
            prompt_c = f"Extraia Nome do Fundo e Ativos em JSON. JSON: {{'nome_fundo': 'NOME', 'ativos': [{{'ativo': 'NOME', 'valor_mercado': 0.0, 'tipo_ativo': 'TAG'}}]}} DADOS: {df.head(200).to_string()}"
            res, motor = chamar_ia_hydra(prompt_c)
            data = json.loads(res.text[res.text.find('{'):res.text.rfind('}')+1])
            st.session_state['temp_c'] = data
            st.table(pd.DataFrame(data['ativos']))

    if 'temp_c' in st.session_state and st.button("💾 Gravar"):
        for a in st.session_state['temp_c']['ativos']: a['fundo_nome'] = st.session_state['temp_c']['nome_fundo']
        conn.table("carteira_diaria").insert(st.session_state['temp_c']['ativos']).execute()
        st.success("Salvo!")
        del st.session_state['temp_c']

# --- 6. 📜 REGULAMENTO (MOTOR DE EXTRAÇÃO SEMÂNTICA) ---
elif menu == "📜 Regulamento e Compliance":
    st.subheader("📜 Arquiteto de Compliance Sniper")
    upload_reg = st.file_uploader("Suba o PDF (Ex: JGP ou FIC FIDC)", type=['pdf'])
    
    if upload_reg and st.button("🚀 Gerar JSON de Compliance"):
        with st.spinner("Fatiando texto jurídico em gavetas matemáticas..."):
            reader = PdfReader(upload_reg)
            texto = "".join([p.extract_text() for p in reader.pages[:50]])
            
            # O PROMPT CONSTRUTOR DE DICIONÁRIOS
            prompt_auditoria = f"""
            Você é um Analista de Risco e Compliance Sênior da CVM. 
            Seu objetivo é transformar o regulamento em um motor matemático JSON.

            REGRAS DE EXTRAÇÃO:
            1. FOQUE APENAS em 'Política de Investimento' e 'Limites de Concentração'. 
            2. TIPO: 'O fundo não pode exceder' vira maximo_percentual. 'Deve investir no mínimo' vira minimo_percentual.
            3. LIMITES: Retorne sempre FLOATS (ex: 95% = 0.95).
            4. MAPA_ATIVOS: Crie um dicionário vinculando CNPJs, códigos ISIN ou nomes curtos (ex: JGP DEB) às categorias (gavetas) que você criou.

            SAÍDA ESPERADA:
            {{
              "fundo": "NOME OFICIAL", "cnpj": "CNPJ",
              "descricao": "Mandato sumário",
              "regras": [
                {{ "id": "id_regra", "tipo": "minimo_percentual", "limite_min": 0.95, "categorias": ["infra_incentivada"] }}
              ],
              "mapa_ativos": {{ "CNPJ/ISIN/NOME": "categoria_gaveta" }},
              "categorias_definidas": {{ "categoria_gaveta": "Descrição legível" }}
            }}
            TEXTO DO REGULAMENTO: {texto[:25000]}
            """
            res, motor = chamar_ia_hydra(prompt_auditoria)
            data = json.loads(res.text[res.text.find('{'):res.text.rfind('}')+1])
            st.session_state['schema_v16'] = data
            st.success(f"Motor gerado via {motor}")
            st.json(data)

    if 'schema_v16' in st.session_state and st.button("💾 Ativar Motor no Banco"):
        d = st.session_state['schema_v16']
        payload = {
            "fundo_nome": d['fundo'], "cnpj": d.get('cnpj'), "descricao_mandato": d['descricao'],
            "regras_json": d['regras'], "mapa_ativos_json": d['mapa_ativos'], 
            "categorias_definidas": d['categorias_definidas']
        }
        conn.table("regulamentos").upsert(payload, on_conflict="fundo_nome").execute()
        st.success("Compliance ativado!")
        del st.session_state['schema_v16']
        st.rerun()
