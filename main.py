import streamlit as st
import pandas as pd
from st_supabase_connection import SupabaseConnection
import google.generativeai as genai
import json
from pypdf import PdfReader

# --- 1. CONFIGURAÇÃO E ESTILO ---
st.set_page_config(page_title="Guardian Ultra v18", layout="wide", page_icon="🛡️")

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
st.sidebar.title("🛡️ Guardian Ultra v18")
try:
    res_f = conn.table("regulamentos").select("fundo_nome").execute()
    lista_fundos = sorted(list(set([i['fundo_nome'] for i in res_f.data]))) if res_f.data else []
except: lista_fundos = []

fundo_ativo = st.sidebar.selectbox("Fundo em Análise:", lista_fundos if lista_fundos else ["Nenhum"])
menu = st.sidebar.radio("Ir para:", ["📊 Dashboard", "🤖 Importar Carteira", "📜 Regulamento e Compliance"])

# --- 4. 📊 DASHBOARD ---
if menu == "📊 Dashboard":
    st.subheader(f"📊 Compliance: {fundo_ativo}")
    if fundo_ativo != "Nenhum":
        c = conn.table("carteira_diaria").select("*").eq("fundo_nome", fundo_ativo).execute()
        r = conn.table("regulamentos").select("*").eq("fundo_nome", fundo_ativo).execute()
        
        if c.data:
            df_c = pd.DataFrame(c.data)
            pl_total = df_c['valor_mercado'].sum()
            st.metric("PL Total do Fundo", format_br(pl_total))
            
            if r.data:
                reg = r.data[0]
                st.write("### ✅ Status das Gavetas Matemáticas")
                for regra in reg['regras_json']:
                    v_soma = df_c[df_c['tipo_ativo'].isin(regra['categorias'])]['valor_mercado'].sum()
                    perc = v_soma / pl_total if pl_total > 0 else 0
                    
                    if regra['tipo'] == 'minimo_percentual':
                        valido = perc >= regra['limite_min']
                        txt = f"Mínimo {regra['limite_min']*100:.1f}%"
                    else:
                        valido = perc <= regra['limite_max']
                        txt = f"Máximo {regra['limite_max']*100:.1f}%"
                    
                    cor = "green" if valido else "red"
                    st.markdown(f"**{regra['id']}**: :{cor}[{perc*100:.2f}%] ({txt})")
            
            st.write("### 📄 Detalhes da Posição")
            st.dataframe(df_c[['ativo', 'valor_mercado', 'tipo_ativo']].assign(valor_mercado=lambda x: x['valor_mercado'].apply(format_br)))
        else: st.warning("Sem dados de carteira.")

# --- 5. 🤖 IMPORTAR CARTEIRA (VOLTA DAS DESPESAS) ---
elif menu == "🤖 Importar Carteira":
    st.subheader("📥 Carga de Dados e Despesas")
    upload_c = st.file_uploader("Excel da Carteira", type=['xlsx'])
    
    if upload_c and st.button("🚀 Iniciar Processamento"):
        with st.spinner("IA fatiando ativos e despesas..."):
            df = pd.read_excel(upload_c)
            contexto = df.dropna(how='all').head(300).to_string()
            
            prompt_c = f"""
            Analista de Compliance: Extraia Nome do Fundo, PL, Cota, Ativos e Despesas.
            JSON: {{'nome_fundo': 'NOME', 'resumo': {{'pl': 0.0, 'cota': 0.0}}, 'ativos': [{{'ativo': 'NOME', 'valor_mercado': 0.0, 'tipo_ativo': 'TAG'}}], 'despesas': [{{'item': 'NOME', 'valor': 0.0}}]}}
            DADOS: {contexto}
            """
            res, motor = chamar_ia_hydra(prompt_c)
            data = json.loads(res.text[res.text.find('{'):res.text.rfind('}')+1])
            
            # Negativa as despesas automaticamente
            for d in data['despesas']: d['valor'] = -abs(float(d['valor']))
            
            st.session_state['temp_c'] = data
            st.success(f"Extraído via {motor}")
            
            c1, c2 = st.columns(2)
            c1.metric("PL Identificado", format_br(data['resumo']['pl']))
            c2.metric("Cota", f"R$ {data['resumo']['cota']:.6f}")
            
            st.write("### Prévia de Ativos")
            st.table(pd.DataFrame(data['ativos']).assign(valor_mercado=lambda x: x['valor_mercado'].apply(format_br)))

    if 'temp_c' in st.session_state and st.button("💾 Gravar Ativos e Despesas"):
        d = st.session_state['temp_c']
        fundo = d['nome_fundo']
        for a in d['ativos']: a['fundo_nome'] = fundo
        for ds in d['despesas']: ds['fundo_nome'] = fundo
        
        conn.table("carteira_diaria").insert(d['ativos']).execute()
        conn.table("despesas_diarias").insert(d['despesas']).execute()
        st.success("Tudo salvo!")
        del st.session_state['temp_c']

# --- 6. 📜 REGULAMENTO (CONSERTADO O SALVAMENTO) ---
elif menu == "📜 Regulamento e Compliance":
    st.subheader("📜 Arquiteto de Compliance")
    upload_reg = st.file_uploader("PDF do Regulamento", type=['pdf'])
    
    if upload_reg and st.button("🚀 Mapear Inteligência"):
        with st.spinner("Criando dicionário e regras..."):
            reader = PdfReader(upload_reg)
            texto = "".join([p.extract_text() for p in reader.pages[:40]])
            
            prompt_auditoria = f"""
            Auditor CVM 175: Fatie o regulamento em motor matemático JSON.
            1. TIPO: maximo_percentual ou minimo_percentual.
            2. LIMITES: Decimais (95% = 0.95).
            3. MAPA_ATIVOS: CNPJs/Nomes -> categorias.
            TEXTO: {texto[:25000]}
            """
            res, motor = chamar_ia_hydra(prompt_auditoria)
            st.session_state['schema_v18'] = json.loads(res.text[res.text.find('{'):res.text.rfind('}')+1])
            st.json(st.session_state['schema_v18'])

    if 'schema_v18' in st.session_state and st.button("💾 Ativar Cérebro no Banco"):
        d = st.session_state['schema_v18']
        payload = {
            "fundo_nome": d.get('fundo') or d.get('nome_fundo'),
            "cnpj": d.get('cnpj'),
            "descricao_mandato": d.get('mandato') or d.get('descricao'), # Consertado!
            "regras_json": d.get('regras'),
            "mapa_ativos_json": d.get('mapa_ativos'),
            "categorias_definidas": d.get('categorias_definidas')
        }
        conn.table("regulamentos").upsert(payload, on_conflict="fundo_nome").execute()
        st.success("Regulamento vinculado!")
        del st.session_state['schema_v18']
        st.rerun()
