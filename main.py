import streamlit as st
import pandas as pd
from st_supabase_connection import SupabaseConnection
import google.generativeai as genai
import json
from pypdf import PdfReader

# --- 1. CONFIGURAÇÃO ---
st.set_page_config(page_title="Guardian Auditor v17", layout="wide", page_icon="🛡️")

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
    raise Exception("Falha nos modelos de IA.")

conn = st.connection("supabase", type=SupabaseConnection)

# --- 3. SIDEBAR ---
st.sidebar.title("🛡️ Guardian Auditor v17")
try:
    res_f = conn.table("regulamentos").select("fundo_nome").execute()
    lista_fundos = sorted(list(set([i['fundo_nome'] for i in res_f.data]))) if res_f.data else []
except: lista_fundos = []

fundo_ativo = st.sidebar.selectbox("Fundo em Análise:", lista_fundos if lista_fundos else ["Nenhum"])
menu = st.sidebar.radio("Navegação:", ["📊 Dashboard", "🤖 Importar Carteira", "📜 Regulamento e Compliance"])

# --- 4. 📊 DASHBOARD (CRUZAMENTO DE GAVETAS) ---
if menu == "📊 Dashboard":
    st.subheader(f"📊 Compliance de Portfólio: {fundo_ativo}")
    if fundo_ativo != "Nenhum":
        r = conn.table("regulamentos").select("*").eq("fundo_nome", fundo_ativo).execute()
        c = conn.table("carteira_diaria").select("*").eq("fundo_nome", fundo_ativo).execute()
        
        if r.data and c.data:
            reg = r.data[0]
            df_c = pd.DataFrame(c.data)
            pl_total = df_c['valor_mercado'].sum()
            st.metric("Patrimônio Líquido (PL)", format_br(pl_total))
            
            st.write("### ✅ Validação de Regras")
            # Aqui fazemos a conta matemática usando o JSON de regras
            for regra in reg['regras_json']:
                # Soma tudo o que a IA tagueou no mapa de ativos
                ativos_da_regra = df_c[df_c['tipo_ativo'].isin(regra['categorias'])]
                soma_financeira = ativos_da_regra['valor_mercado'].sum()
                percentual_atual = (soma_financeira / pl_total) if pl_total > 0 else 0
                
                # Validação Lógica
                if regra['tipo'] == 'minimo_percentual':
                    valido = percentual_atual >= regra['limite_min']
                    rotulo = f"Mínimo {regra['limite_min']*100:.1f}%"
                else:
                    valido = percentual_atual <= regra['limite_max']
                    rotulo = f"Máximo {regra['limite_max']*100:.1f}%"
                
                cor = "green" if valido else "red"
                st.markdown(f"**{regra['id']}**: :{cor}[{percentual_atual*100:.2f}%] ({rotulo})")

            st.write("### 📄 Itens Detectados na Carteira")
            st.dataframe(df_c[['ativo', 'valor_mercado', 'tipo_ativo']])
        else: st.warning("⚠️ Carregue o Regulamento e a Carteira para este fundo.")

# --- 5. 🤖 IMPORTAR CARTEIRA ---
elif menu == "🤖 Importar Carteira":
    st.subheader("📥 Carga de Posição Diária")
    upload_c = st.file_uploader("Suba o Excel", type=['xlsx'])
    if upload_c and st.button("🚀 Processar Carteira"):
        with st.spinner("Classificando ativos via IA..."):
            df = pd.read_excel(upload_c)
            # IA extrai os dados brutos. No futuro, ela consultará o mapa_ativos_json do banco.
            prompt = f"Extraia em JSON: {{'nome_fundo': 'NOME', 'ativos': [{{'ativo': 'NOME', 'valor_mercado': 0.0, 'tipo_ativo': 'CATEGORIA'}}]}} DADOS: {df.head(250).to_string()}"
            res, motor = chamar_ia_hydra(prompt)
            data = json.loads(res.text[res.text.find('{'):res.text.rfind('}')+1])
            st.session_state['temp_c'] = data
            st.table(pd.DataFrame(data['ativos']))

    if 'temp_c' in st.session_state and st.button("💾 Gravar no Supabase"):
        d = st.session_state['temp_c']
        for a in d['ativos']: a['fundo_nome'] = d['nome_fundo']
        conn.table("carteira_diaria").insert(d['ativos']).execute()
        st.success("Carteira salva!")
        del st.session_state['temp_c']

# --- 6. 📜 REGULAMENTO (O MOTOR SNIPER v17) ---
elif menu == "📜 Regulamento e Compliance":
    st.subheader("📜 Arquiteto de Compliance e Dicionários")
    upload_reg = st.file_uploader("Suba o PDF (JGP, FIC FIDC, etc)", type=['pdf'])
    
    if upload_reg and st.button("🚀 Mapear Inteligência do Fundo"):
        with st.spinner("Lendo Anexo I e Política de Investimento..."):
            try:
                reader = PdfReader(upload_reg)
                texto = ""
                # Lemos as 50 primeiras páginas para garantir que pegamos o Anexo I
                for page in reader.pages[:50]: texto += page.extract_text()
                
                # PROMPT COM CONSTRAINT ABSOLUTA
                super_prompt = f"""
                Você é um Auditor de Risco e Compliance Sênior. 
                Sua tarefa é fatiar o regulamento em um motor matemático JSON rigoroso.

                DIRETRIZES DE EXTRAÇÃO:
                1. FOQUE APENAS na 'Política de Investimento' e 'Limites de Concentração/Diversificação'.
                2. TIPO: 'Não pode exceder' vira maximo_percentual. 'Deve investir no mínimo' vira minimo_percentual.
                3. LIMITES: Retorne sempre decimais (Ex: 95% vira 0.95).
                4. MAPA_ATIVOS: Crie um dicionário mapeando CNPJs, termos (ex: JGP DEB) e ativos citados para as categorias/tags que você criou.

                JSON ESPERADO (FRAMEWORK GUARDIAN):
                {{
                  "fundo": "NOME OFICIAL", "cnpj": "CNPJ", "mandato": "Resumo curto",
                  "regras": [
                    {{ "id": "min_infra", "tipo": "minimo_percentual", "limite_min": 0.95, "categorias": ["infra_incentivada"] }}
                  ],
                  "mapa_ativos": {{ "CNPJ_OU_NOME": "infra_incentivada" }},
                  "categorias_definidas": {{ "infra_incentivada": "Debêntures Incentivadas Lei 12.431" }}
                }}
                TEXTO: {texto[:28000]}
                """
                res, motor = chamar_ia_hydra(super_prompt)
                data = json.loads(res.text[res.text.find('{'):res.text.rfind('}')+1])
                st.session_state['schema_v17'] = data
                st.success(f"Dicionário gerado via {motor}")
                st.json(data)
            except Exception as e: st.error(f"Erro: {e}")

    if 'schema_v17' in st.session_state and st.button("💾 Ativar Cérebro no Banco"):
        d = st.session_state['schema_v17']
        payload = {
            "fundo_nome": d['fundo'], "cnpj": d.get('cnpj'), "descricao_mandato": d['mandato'],
            "regras_json": d['regras'], "mapa_ativos_json": d['mapa_ativos'], 
            "categorias_definidas": d['categorias_definidas']
        }
        conn.table("regulamentos").upsert(payload, on_conflict="fundo_nome").execute()
        st.success("Cérebro de Compliance Ativado!")
        del st.session_state['schema_v17']
        st.rerun()
