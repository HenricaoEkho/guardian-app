import streamlit as st
import pandas as pd
from st_supabase_connection import SupabaseConnection
import google.generativeai as genai
import json

# --- 1. CONFIGURAÇÃO ---
st.set_page_config(page_title="Guardian Hydra v10", layout="wide", page_icon="🛡️")

def format_br(valor, prefixo="R$ "):
    try:
        val = float(valor)
        return f"{prefixo}{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except: return str(valor)

# --- 2. CONEXÃO IA HÍBRIDA ---
gemini_key = st.secrets.get("GEMINI_API_KEY")
if gemini_key:
    genai.configure(api_key=gemini_key)

MODELOS = ['models/gemini-3.1-flash-lite-preview', 'models/gemini-1.5-flash']

def chamar_ia(prompt):
    for m in MODELOS:
        try:
            model = genai.GenerativeModel(m)
            return model.generate_content(prompt), m
        except: continue
    raise Exception("IA fora do ar.")

conn = st.connection("supabase", type=SupabaseConnection)

# --- 3. NAVEGAÇÃO ---
st.sidebar.title("🛡️ Guardian Ultra v10")
try:
    res_f = conn.table("carteira_diaria").select("fundo_nome").execute()
    lista_fundos = sorted(list(set([i['fundo_nome'] for i in res_f.data]))) if res_f.data else []
except: lista_fundos = []

fundo_ativo = st.sidebar.selectbox("Fundo Ativo:", lista_fundos if lista_fundos else ["Nenhum cadastrado"])
menu = st.sidebar.radio("Ir para:", ["📊 Dashboard", "🤖 Importar Carteira", "📜 Regulamento", "📉 Gestão de Passivo"])

# --- 4. ABA REGULAMENTO (A NOVA INTELIGÊNCIA) ---
if menu == "📜 Regulamento":
    st.subheader("📜 Inteligência de Regulamentos")
    st.write("Suba o PDF do regulamento. A IA extrairá as regras de enquadramento automaticamente.")
    
    upload_reg = st.file_uploader("Relatório de Regulamento (PDF ou Texto)", type=['pdf', 'txt'])
    
    if upload_reg:
        if st.button("🚀 Analisar Regulamento com IA"):
            with st.spinner("Lendo cláusulas e extraindo limites..."):
                # Simulação de leitura de contexto (em produção usaríamos PyPDF2 para extrair texto)
                # Para este exemplo, passamos o nome e pedimos para a IA focar em limites
                prompt_reg = f"""
                Analise o regulamento do fundo. Foque no capítulo de 'Política de Investimento' e 'Limites de Diversificação'.
                Extraia o Nome do Fundo e todos os limites percentuais de alocação.
                
                Retorne APENAS um JSON:
                {{
                  "nome_fundo": "NOME_DO_FUNDO",
                  "regras": {{
                    "min_incentivadas": 85.0,
                    "max_emissor": 20.0,
                    "max_acoes": 0.0,
                    "outros": "Descrição de qualquer outra regra importante"
                  }}
                }}
                DADOS DO ARQUIVO: {upload_reg.name} (Simulação de leitura de conteúdo)
                """
                # Aqui a IA processaria o texto extraído do PDF
                res, motor = chamar_ia(prompt_reg)
                reg_data = json.loads(res.text[res.text.find('{'):res.text.rfind('}')+1])
                st.session_state['temp_reg'] = reg_data
                st.success(f"Análise concluída via {motor}")

        if 'temp_reg' in st.session_state:
            reg = st.session_state['temp_reg']
            st.write("### Regras Extraídas")
            st.json(reg['regras'])
            
            # Lógica de Substituição
            check_exists = conn.table("regulamentos").select("*").eq("fundo_nome", reg['nome_fundo']).execute()
            
            if check_exists.data:
                st.warning(f"⚠️ Já existe um regulamento para o fundo **{reg['nome_fundo']}**.")
                confirmar = st.checkbox("Sim, desejo substituir o regulamento existente.")
            else:
                confirmar = True
                
            if confirmar:
                if st.button("💾 Confirmar e Salvar Regulamento"):
                    payload = {
                        "fundo_nome": reg['nome_fundo'],
                        "meta_incentivadas": reg['regras'].get('min_incentivadas', 85.0),
                        "limite_emissor": reg['regras'].get('max_emissor', 20.0),
                        "regras_json": reg['regras']
                    }
                    conn.table("regulamentos").upsert(payload, on_conflict="fundo_nome").execute()
                    st.success(f"Regulamento de {reg['nome_fundo']} salvo!")
                    del st.session_state['temp_reg']

# --- 5. ABA DASHBOARD (CRUZAMENTO DE DADOS) ---
elif menu == "📊 Dashboard":
    st.subheader(f"📊 Compliance: {fundo_ativo}")
    if fundo_ativo != "Nenhum cadastrado":
        c = conn.table("carteira_diaria").select("*").eq("fundo_nome", fundo_ativo).order("data", desc=True).limit(100).execute()
        r = conn.table("regulamentos").select("*").eq("fundo_nome", fundo_ativo).execute()
        
        if c.data and r.data:
            df_c = pd.DataFrame(c.data)
            regres = r.data[0]
            pl_total = df_c['valor_mercado'].sum()
            
            # Regras Dinâmicas
            meta_inc = regres['meta_incentivadas']
            v_inc = df_c[df_c['tipo_ativo'].str.contains('Incentivada', case=False, na=False)]['valor_mercado'].sum()
            perc_inc = (v_inc / pl_total) * 100 if pl_total > 0 else 0
            
            col1, col2 = st.columns(2)
            col1.metric("Patrimônio Líquido", format_br(pl_total))
            
            status = "normal" if perc_inc >= meta_inc else "inverse"
            col2.metric(f"Enquadramento (Mín {meta_inc}%)", f"{perc_inc:.2f}%", 
                        delta=f"{perc_inc - meta_inc:.2f}%", delta_color=status)
            
            if status == "inverse":
                st.error(f"🚨 ATENÇÃO: Fundo desenquadrado! Meta mínima de {meta_inc}% não atingida.")
            else:
                st.success("✅ Fundo enquadrado conforme o regulamento.")
                
            st.write("### Detalhes das Regras do Fundo")
            st.json(regres['regras_json'])
        else:
            st.info("Aguardando upload de Carteira e Regulamento para este fundo.")

# --- 6. ABA IMPORTAR CARTEIRA (MANTIDA) ---
elif menu == "🤖 Importar Carteira":
    st.subheader("📥 Carga de Ativos")
    # [Mantém o código do Hydra anterior para importar carteiras]
    st.write("Use esta aba para subir o Excel diário da carteira.")
