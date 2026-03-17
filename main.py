import streamlit as st
import pandas as pd
from st_supabase_connection import SupabaseConnection
import google.generativeai as genai
import json
from pypdf import PdfReader

# --- 1. CONFIGURAÇÃO E FORMATAÇÃO ---
st.set_page_config(page_title="Guardian Sniper v15", layout="wide", page_icon="🛡️")

def format_br(valor, prefixo="R$ "):
    try:
        val = float(valor)
        return f"{prefixo}{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except: return str(valor)

# --- 2. CONEXÃO IA HÍBRIDA ---
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

# --- 3. SIDEBAR: NAVEGAÇÃO ---
st.sidebar.title("🛡️ Guardian Sniper")
try:
    # Busca nomes de fundos que já possuem regulamento cadastrado
    res_f = conn.table("regulamentos").select("fundo_nome").execute()
    lista_fundos = sorted(list(set([i['fundo_nome'] for i in res_f.data]))) if res_f.data else []
except: lista_fundos = []

fundo_ativo = st.sidebar.selectbox("Fundo Ativo:", lista_fundos if lista_fundos else ["Nenhum cadastrado"])
menu = st.sidebar.radio("Ir para:", ["📊 Dashboard", "🤖 Importar Carteira", "📜 Regulamento e Compliance", "📉 Gestão de Passivo"])

# --- 4. 📊 ABA: DASHBOARD ---
if menu == "📊 Dashboard":
    st.subheader(f"📊 Compliance de Risco: {fundo_ativo}")
    if fundo_ativo != "Nenhum cadastrado":
        r = conn.table("regulamentos").select("*").eq("fundo_nome", fundo_ativo).execute()
        c = conn.table("carteira_diaria").select("*").eq("fundo_nome", fundo_ativo).execute()
        
        if r.data and c.data:
            reg = r.data[0]
            df_c = pd.DataFrame(c.data)
            pl_total = df_c['valor_mercado'].sum()
            
            c1, c2, c3 = st.columns(3)
            c1.metric("Patrimônio Líquido", format_br(pl_total))
            c2.metric("Público-Alvo", reg['publico_alvo'])
            c3.metric("Responsabilidade", reg['responsabilidade_cotista'])
            
            st.divider()
            
            col_a, col_b = st.columns(2)
            with col_a:
                st.write("### 🏢 Limites por Emissor")
                st.table(reg['limites_emissor'])
            with col_b:
                st.write("### 📈 Limites por Modalidade")
                st.table(reg['limites_modalidade'])
                
            with st.expander("🚫 Vedações e Derivativos"):
                st.write("**Regras de Derivativos:**", reg['derivativos_regras'])
                st.write("**Vedações Principais:**", reg['vedacoes'])
        else:
            st.info("Aguardando carga de carteira para este fundo.")

# --- 5. 🤖 ABA: IMPORTAR CARTEIRA ---
elif menu == "🤖 Importar Carteira":
    st.subheader("📥 Carga de Posição Diária")
    upload_c = st.file_uploader("Suba o Excel", type=['xlsx'])
    if upload_c and st.button("🚀 Processar Carteira"):
        with st.spinner("IA Analisando ativos..."):
            df = pd.read_excel(upload_c)
            # Prompt simplificado para carteira
            prompt_c = f"Extraia em JSON: {{'nome_fundo': 'NOME', 'ativos': [{{'ativo': 'NOME', 'valor_mercado': 0.0, 'tipo_ativo': 'TIPO'}}]}} DADOS: {df.head(250).to_string()}"
            res, motor = chamar_ia_hydra(prompt_c)
            data = json.loads(res.text[res.text.find('{'):res.text.rfind('}')+1])
            st.session_state['temp_c'] = data
            st.success(f"Extraído via {motor}")
            st.table(pd.DataFrame(data['ativos']).assign(valor_mercado=lambda x: x['valor_mercado'].apply(format_br)))

    if 'temp_c' in st.session_state and st.button("💾 Gravar no Banco"):
        d = st.session_state['temp_c']
        for a in d['ativos']: a['fundo_nome'] = d['nome_fundo']
        conn.table("carteira_diaria").insert(d['ativos']).execute()
        st.success("Carteira salva!")
        del st.session_state['temp_c']
        st.rerun()

# --- 6. 📜 ABA: REGULAMENTO (O NOVO PROMPT SNIPER) ---
elif menu == "📜 Regulamento e Compliance":
    st.subheader("📜 Perícia de Regulamentos (Resolução CVM 175)")
    upload_reg = st.file_uploader("Suba o Regulamento (PDF)", type=['pdf'])
    
    if upload_reg and st.button("🚀 Iniciar Análise Sniper"):
        with st.spinner("IA executando leitura técnica do Anexo I..."):
            try:
                reader = PdfReader(upload_reg)
                texto = "".join([p.extract_text() for p in reader.pages[:20]])
                
                # O SEU NOVO PROMPT SNIPER
                sniper_prompt = f"""
                Você é um Analista de Compliance Sênior especialista em fundos brasileiros (Resolução CVM 175). 
                Seu objetivo é ler o regulamento e o Anexo I fornecidos e extrair EXATAMENTE os limites de risco e investimento em formato JSON.

                Instruções Críticas:
                1. Busque pelas tabelas de 'Limites por Emissor', 'Limites por Modalidade' e 'Parâmetros de Derivativos/Alavancagem'.
                2. Se o fundo for um 'Fundo de Investimento em Cotas' (FIC), verifique se o limite se aplica à classe ou à classe investida.
                3. Identifique o regime de responsabilidade dos cotistas (Limitada ou Ilimitada).
                4. Extraia as regras de 'Concentração Máxima' e 'Vedações'.

                Estrutura de Saída (JSON):
                {{
                  "fundo": "Nome Completo e CNPJ",
                  "publico_alvo": "...",
                  "responsabilidade_cotista": "Limitada/Ilimitada",
                  "limites_emissor": [{{ "emissor": "...", "limite_individual": "...", "limite_conjunto": "..." }}],
                  "limites_modalidade": [{{ "ativo": "...", "limite_max": "..." }}],
                  "derivativos": {{ "permite_alavancagem": "Sim/Não", "margem_maxima": "...", "objetivo": "Hedge/Alavancagem" }},
                  "vedacoes_principais": ["item 1", "item 2"]
                }}

                Responda APENAS o código JSON puro, sem textos explicativos.
                TEXTO DO REGULAMENTO: {texto[:10000]}
                """
                res, motor = chamar_ia_hydra(sniper_prompt)
                reg_data = json.loads(res.text[res.text.find('{'):res.text.rfind('}')+1])
                st.session_state['sniper_reg'] = reg_data
                st.success(f"Análise concluída via {motor}")
                st.json(reg_data)
            except Exception as e: st.error(f"Erro na Perícia: {e}")

    if 'sniper_reg' in st.session_state and st.button("💾 Salvar Regulamento e Vincular"):
        d = st.session_state['sniper_reg']
        payload = {
            "fundo_nome": d['fundo'],
            "cnpj": "Identificado no JSON",
            "publico_alvo": d['publico_alvo'],
            "responsabilidade_cotista": d['responsabilidade_cotista'],
            "limites_emissor": d['limites_emissor'],
            "limites_modalidade": d['limites_modalidade'],
            "derivativos_regras": d['derivativos'],
            "vedacoes": d['vedacoes_principais']
        }
        conn.table("regulamentos").upsert(payload, on_conflict="fundo_nome").execute()
        st.success(f"Cérebro de Compliance de '{d['fundo']}' ativado!")
        del st.session_state['sniper_reg']
        st.rerun()
