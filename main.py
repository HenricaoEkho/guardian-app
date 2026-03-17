import streamlit as st
import pandas as pd
from st_supabase_connection import SupabaseConnection
import google.generativeai as genai
import json
from pypdf import PdfReader

# --- 1. CONFIGURAÇÃO ---
st.set_page_config(page_title="Guardian Sniper v15.1", layout="wide", page_icon="🛡️")

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
    raise Exception("Modelos fora de linha.")

conn = st.connection("supabase", type=SupabaseConnection)

# --- 3. SIDEBAR ---
st.sidebar.title("🛡️ Guardian Sniper")
try:
    res_f = conn.table("regulamentos").select("fundo_nome").execute()
    lista_fundos = sorted(list(set([i['fundo_nome'] for i in res_f.data]))) if res_f.data else []
except: lista_fundos = []

fundo_ativo = st.sidebar.selectbox("Fundo Ativo:", lista_fundos if lista_fundos else ["Nenhum"])
menu = st.sidebar.radio("Navegação:", ["📊 Dashboard", "🤖 Importar Carteira", "📜 Regulamento e Compliance"])

# --- 4. 📊 DASHBOARD ---
if menu == "📊 Dashboard":
    st.subheader(f"📊 Painel de Compliance: {fundo_ativo}")
    if fundo_ativo != "Nenhum":
        r = conn.table("regulamentos").select("*").eq("fundo_nome", fundo_ativo).execute()
        c = conn.table("carteira_diaria").select("*").eq("fundo_nome", fundo_ativo).execute()
        
        if r.data and c.data:
            reg = r.data[0]
            df_c = pd.DataFrame(c.data)
            
            c1, c2, c3 = st.columns(3)
            c1.metric("PL Total", format_br(df_c['valor_mercado'].sum()))
            c2.metric("Público", reg['publico_alvo'])
            c3.metric("Cotista", reg['responsabilidade_cotista'])
            
            st.write("### 🏢 Limites por Emissor")
            st.table(reg['limites_emissor'])
            st.write("### 📈 Limites por Modalidade")
            st.table(reg['limites_modalidade'])
        else: st.info("Faltam dados de Carteira ou Regulamento.")

# --- 5. 🤖 IMPORTAÇÃO ---
elif menu == "🤖 Importar Carteira":
    st.subheader("📥 Carga de Posição")
    upload_c = st.file_uploader("Suba o Excel", type=['xlsx'])
    if upload_c and st.button("🚀 Processar"):
        with st.spinner("IA Analisando..."):
            df = pd.read_excel(upload_c)
            p = f"JSON: {{'nome_fundo': 'NOME', 'ativos': [{{'ativo': 'NOME', 'valor_mercado': 0.0, 'tipo_ativo': 'TIPO'}}]}} DADOS: {df.head(300).to_string()}"
            res, motor = chamar_ia_hydra(p)
            data = json.loads(res.text[res.text.find('{'):res.text.rfind('}')+1])
            st.session_state['temp_c'] = data
            st.success(f"Extraído via {motor}")
            st.table(pd.DataFrame(data['ativos']))

    if 'temp_c' in st.session_state and st.button("💾 Gravar"):
        d = st.session_state['temp_c']
        for a in d['ativos']: a['fundo_nome'] = d['nome_fundo']
        conn.table("carteira_diaria").insert(d['ativos']).execute()
        st.success("Salvo!")
        del st.session_state['temp_c']

# --- 6. 📜 REGULAMENTO (O PROMPT QUE VOCÊ TESTOU E FUNCIONOU) ---
elif menu == "📜 Regulamento e Compliance":
    st.subheader("📜 Perícia Sniper (Visão Total)")
    upload_reg = st.file_uploader("Suba o PDF do Regulamento", type=['pdf'])
    
    if upload_reg and st.button("🚀 Iniciar Análise Sniper"):
        with st.spinner("Lendo TODAS as páginas para não perder as tabelas..."):
            try:
                reader = PdfReader(upload_reg)
                texto_completo = ""
                # Lemos até 60 páginas (regulamento inteiro do FIC FIDC deve caber)
                for page in reader.pages[:60]:
                    texto_completo += page.extract_text()
                
                # SEU PROMPT VITORIOSO
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
                TEXTO DO REGULAMENTO: {texto_completo[:30000]}
                """
                res, motor = chamar_ia_hydra(sniper_prompt)
                reg_data = json.loads(res.text[res.text.find('{'):res.text.rfind('}')+1])
                st.session_state['sniper_reg'] = reg_data
                st.success(f"Análise concluída via {motor} (Páginas lidas: {len(reader.pages)})")
                st.json(reg_data)
            except Exception as e: st.error(f"Erro: {e}")

    if 'sniper_reg' in st.session_state and st.button("💾 Salvar Inteligência"):
        d = st.session_state['sniper_reg']
        payload = {
            "fundo_nome": d['fundo'],
            "cnpj": "Extracted",
            "publico_alvo": d['publico_alvo'],
            "responsabilidade_cotista": d['responsabilidade_cotista'],
            "limites_emissor": d['limites_emissor'],
            "limites_modalidade": d['limites_modalidade'],
            "derivativos_regras": d['derivativos'],
            "vedacoes": d['vedacoes_principais']
        }
        conn.table("regulamentos").upsert(payload, on_conflict="fundo_nome").execute()
        st.success(f"Regulamento de {d['fundo']} salvo!")
        del st.session_state['sniper_reg']
        st.rerun()
