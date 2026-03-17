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
    raise Exception("Falha nos modelos de IA.")

conn = st.connection("supabase", type=SupabaseConnection)

# --- SIDEBAR ---
st.sidebar.title("🛡️ Guardian Auditor")
try:
    res_f = conn.table("regulamentos").select("fundo_nome").execute()
    lista_fundos = sorted(list(set([i['fundo_nome'] for i in res_f.data]))) if res_f.data else []
except: lista_fundos = []

fundo_ativo = st.sidebar.selectbox("Fundo em Análise:", lista_fundos if lista_fundos else ["Nenhum"])
menu = st.sidebar.radio("Navegação:", ["📊 Dashboard", "🤖 Importar Carteira", "📜 Regulamento e Compliance"])

# --- 📊 DASHBOARD (ALINHADO COM O NOVO JSON) ---
if menu == "📊 Dashboard":
    st.subheader(f"📊 Compliance: {fundo_ativo}")
    if fundo_ativo != "Nenhum":
        r = conn.table("regulamentos").select("*").eq("fundo_nome", fundo_ativo).execute()
        c = conn.table("carteira_diaria").select("*").eq("fundo_nome", fundo_ativo).execute()
        
        if r.data and c.data:
            reg = r.data[0]
            df_c = pd.DataFrame(c.data)
            pl_total = df_c['valor_mercado'].sum()
            
            # Puxa a primeira regra de mínimo do JSON
            regra_min = next((x for x in reg['regras_json'] if x['tipo'] == 'minimo_percentual'), None)
            
            if regra_min:
                meta = regra_min['limite_min']
                cats = regra_min['categorias']
                # Filtra ativos que pertencem às categorias da regra
                v_alvo = df_c[df_c['tipo_ativo'].str.lower().isin([c.lower() for c in cats])]['valor_mercado'].sum()
                perc = v_alvo / pl_total if pl_total > 0 else 0
                
                c1, c2 = st.columns(2)
                c1.metric("PL Total", format_br(pl_total))
                status = "normal" if perc >= meta else "inverse"
                c2.metric(f"Enquadramento ({regra_min['id']})", f"{perc*100:.2f}%", 
                          delta=f"{(perc-meta)*100:.2f}% vs Meta {meta*100:.0f}%", delta_color=status)
            
            st.write("### Itens da Carteira")
            st.dataframe(df_c[['ativo', 'valor_mercado', 'tipo_ativo']])
        else: st.info("Aguardando dados de Carteira e Regulamento.")

# --- 🤖 IMPORTAR CARTEIRA ---
elif menu == "🤖 Importar Carteira":
    st.subheader("📥 Carga de Posição")
    # [Código de importação mantido...]

# --- 📜 REGULAMENTO (O PROMPT "ANTI-CAGADA") ---
elif menu == "📜 Regulamento e Compliance":
    st.subheader("📜 Perícia de Regulamentos (Assertiva)")
    upload_reg = st.file_uploader("Suba o PDF (Ex: FIC FIDC)", type=['pdf'])
    
    if upload_reg and st.button("🚀 Iniciar Perícia"):
        with st.spinner("IA identificando classe e limites reais..."):
            try:
                reader = PdfReader(upload_reg)
                texto = "".join([p.extract_text() for p in reader.pages[:20]])
                
                # O PROMPT QUE SEGUE SEU EXEMPLO JSON
                prompt_auditoria = f"""
                Você é um Engenheiro de Compliance de Fundos. Analise o regulamento de forma RIGOROSA.
                
                OBJETIVO: Gerar um JSON de inteligência sem alucinar leis que não estão no texto.
                
                TAREFAS:
                1. Identifique o Nome do Fundo e o CNPJ.
                2. Determine a CLASSE (Ex: FIC-FIDC [cite: 380]).
                3. Busque a 'Política de Investimento' e 'Limites de Concentração'[cite: 537, 562].
                4. Localize o percentual MÍNIMO de enquadramento (Ex: 67% em FIC-FIDC ).
                5. Crie um 'mapa_ativos' vinculando termos da carteira às categorias das regras.
                
                ESTRUTURA DE SAÍDA (SIGA SEU EXEMPLO):
                {{
                  "fundo": "NOME", "cnpj": "CNPJ", "descricao": "Mandato",
                  "regras": [
                    {{ "id": "min_fidc", "tipo": "minimo_percentual", "limite_min": 0.67, "categorias": ["fidc"] }}
                  ],
                  "mapa_ativos": {{ "NOME/TERMO": "fidc" }},
                  "categorias_definidas": {{ "fidc": "Fundo de Investimento em Direitos Creditórios" }}
                }}
                TEXTO: {texto[:10000]}
                """
                res, motor = chamar_ia_hydra(prompt_auditoria)
                data = json.loads(res.text[res.text.find('{'):res.text.rfind('}')+1])
                st.session_state['pericia_reg'] = data
                st.json(data)
                st.success(f"Análise via {motor}")
            except Exception as e: st.error(f"Erro: {e}")

    if 'pericia_reg' in st.session_state and st.button("💾 Salvar Inteligência"):
        d = st.session_state['pericia_reg']
        payload = {
            "fundo_nome": d['fundo'],
            "cnpj": d.get('cnpj'),
            "classe_fundo": d.get('classe'),
            "regras_json": d['regras'],
            "mapa_ativos_json": d['mapa_ativos'],
            "categorias_definidas": d.get('categorias_definidas')
        }
        conn.table("regulamentos").upsert(payload, on_conflict="fundo_nome").execute()
        st.success("Regras de FIC-FIDC salvas com sucesso!")
        del st.session_state['pericia_reg']
        st.rerun()
