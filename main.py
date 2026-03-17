import streamlit as st
import pandas as pd
from st_supabase_connection import SupabaseConnection
import google.generativeai as genai
import json
from pypdf import PdfReader

# --- 1. SETUP E FORMATAÇÃO ---
st.set_page_config(page_title="Guardian Ultra v20", layout="wide", page_icon="🛡️")

def format_br(valor, prefixo="R$ "):
    try:
        val = float(valor)
        return f"{prefixo}{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except: return str(valor)

# --- 2. CONEXÃO IA HYDRA ---
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

# --- 3. SIDEBAR: SELEÇÃO CRUZADA ---
st.sidebar.title("🛡️ Guardian Ultra v20")

# Buscamos fundos que aparecem na carteira ou no regulamento
try:
    res_c = conn.table("carteira_diaria").select("fundo_nome").execute()
    res_r = conn.table("regulamentos").select("fundo_nome").execute()
    nomes_c = [i['fundo_nome'] for i in res_c.data] if res_c.data else []
    nomes_r = [i['fundo_nome'] for i in res_r.data] if res_r.data else []
    lista_total = sorted(list(set(nomes_c + nomes_r)))
except: lista_total = []

fundo_ativo = st.sidebar.selectbox("Fundo Ativo:", lista_total if lista_total else ["Nenhum"])
menu = st.sidebar.radio("Ir para:", ["📊 Dashboard Compliance", "🤖 Importar Carteira", "📜 Regulamento e Leis"])

# --- 4. 📊 DASHBOARD (VÍNCULO E CLASSIFICAÇÃO) ---
if menu == "📊 Dashboard Compliance":
    st.subheader(f"📊 Monitoramento: {fundo_ativo}")
    
    if fundo_ativo != "Nenhum":
        # Puxa dados da carteira e do regulamento
        c = conn.table("carteira_diaria").select("*").eq("fundo_nome", fundo_ativo).execute()
        r = conn.table("regulamentos").select("*").ilike("fundo_nome", f"%{fundo_ativo}%").execute()
        
        if not c.data:
            st.warning("⚠️ Carteira não encontrada para este nome exato no banco.")
            # Sugestão de match se houver nome parecido
            if nomes_c:
                st.info(f"Dica: Existem carteiras salvas com o nome: {nomes_c[0]}")
        
        if c.data and r.data:
            reg = r.data[0]
            df_c = pd.DataFrame(c.data)
            pl_total = df_c['valor_mercado'].sum()
            
            # --- INTELIGÊNCIA DE VÍNCULO: MAPA DE ATIVOS ---
            # Reclassificamos os ativos da carteira usando o dicionário do regulamento
            mapa = reg.get('mapa_ativos_json', {})
            
            def classificar(nome_ativo):
                nome_ativo_upper = str(nome_ativo).upper()
                for chave, tag in mapa.items():
                    if str(chave).upper() in nome_ativo_upper:
                        return tag
                return "Outros"

            df_c['categoria_compliance'] = df_c['ativo'].apply(classificar)
            
            # --- EXIBIÇÃO DE MÉTRICAS ---
            st.metric("Patrimônio Líquido Total", format_br(pl_total))
            
            st.write("### ✅ Enquadramento de Regras (Matemático)")
            for regra in reg['regras_json']:
                # Soma financeira baseada na nova categoria compliance
                v_soma = df_c[df_c['categoria_compliance'].isin(regra['categorias'])]['valor_mercado'].sum()
                perc = v_soma / pl_total if pl_total > 0 else 0
                
                # Validação
                if regra['tipo'] == 'minimo_percentual':
                    valido = perc >= regra['limite_min']
                    alvo = f"Mínimo {regra['limite_min']*100:.1f}%"
                else:
                    valido = perc <= regra['limite_max']
                    alvo = f"Máximo {regra['limite_max']*100:.1f}%"
                
                cor = "green" if valido else "red"
                st.markdown(f"**{regra['id']}**: :{cor}[{perc*100:.2f}%] ({alvo})")

            with st.expander("📄 Ver Itens da Carteira e Tags de Compliance"):
                st.dataframe(df_c[['ativo', 'valor_mercado', 'categoria_compliance']])
        elif c.data and not r.data:
            st.error("❌ Regulamento não vinculado. Vá em 'Regulamento e Compliance' e salve as regras para este fundo.")

# --- 5. 🤖 IMPORTAR CARTEIRA (CONSERTADO) ---
elif menu == "🤖 Importar Carteira":
    st.subheader("📥 Carga de Posição Diária")
    upload_c = st.file_uploader("Suba o Excel", type=['xlsx'])
    
    if upload_c and st.button("🚀 Processar Carteira"):
        with st.spinner("IA classificando ativos..."):
            df = pd.read_excel(upload_c)
            contexto = df.dropna(how='all').head(300).to_string()
            prompt = f"JSON: {{'nome_fundo': 'NOME', 'resumo': {{'pl': 0.0, 'cota': 0.0}}, 'ativos': [{{'ativo': 'NOME', 'valor_mercado': 0.0, 'tipo_ativo': 'TAG'}}], 'despesas': [{{'item': 'NOME', 'valor': 0.0}}]}} DADOS: {contexto}"
            res, motor = chamar_ia_hydra(prompt)
            data = json.loads(res.text[res.text.find('{'):res.text.rfind('}')+1])
            st.session_state['temp_c'] = data
            st.success(f"Extraído via {motor}")
            st.table(pd.DataFrame(data['ativos']).head(10))

    if 'temp_c' in st.session_state and st.button("💾 Gravar no Banco de Dados"):
        d = st.session_state['temp_c']
        fn = d['nome_fundo']
        for a in d['ativos']: a['fundo_nome'] = fn
        conn.table("carteira_diaria").insert(d['ativos']).execute()
        st.success(f"Carteira de {fn} salva! Agora vincule o Regulamento.")
        del st.session_state['temp_c']
        st.rerun()

# --- 6. 📜 REGULAMENTO E COMPLIANCE (ESTRUTURADO) ---
elif menu == "📜 Regulamento e Compliance":
    st.subheader("📜 Arquiteto de Compliance")
    upload_reg = st.file_uploader("Suba o PDF do Regulamento", type=['pdf'])
    
    if upload_reg and st.button("🚀 Mapear Regras"):
        with st.spinner("Analisando Anexo I..."):
            reader = PdfReader(upload_reg)
            texto = "".join([p.extract_text() for p in reader.pages[:40]])
            
            prompt_reg = f"""
            Auditor CVM 175: Transforme o regulamento em JSON matemático.
            LIMITES: Decimais (95% = 0.95). 
            MAPA_ATIVOS: Vincule nomes (ex: JGP DEB) às categorias.
            JSON: {{ "fundo": "NOME", "regras": [{{ "id": "ID", "tipo": "minimo_percentual", "limite_min": 0.0, "categorias": ["CAT"] }}], "mapa_ativos": {{ "TERMO": "CAT" }} }}
            TEXTO: {texto[:25000]}
            """
            res, motor = chamar_ia_hydra(prompt_reg)
            data = json.loads(res.text[res.text.find('{'):res.text.rfind('}')+1])
            st.session_state['schema_v20'] = data
            st.json(data)

    if 'schema_v20' in st.session_state and st.button("💾 Ativar Cérebro Compliance"):
        d = st.session_state['schema_v20']
        payload = {
            "fundo_nome": d['fundo'],
            "regras_json": d['regras'],
            "mapa_ativos_json": d['mapa_ativos']
        }
        conn.table("regulamentos").upsert(payload, on_conflict="fundo_nome").execute()
        st.success("Regras ativadas! Vá ao Dashboard.")
        del st.session_state['schema_v20']
