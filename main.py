import streamlit as st
import pandas as pd
from st_supabase_connection import SupabaseConnection
import google.generativeai as genai
import json
from pypdf import PdfReader

# --- 1. CONFIGURAÇÃO E FORMATAÇÃO ---
st.set_page_config(page_title="Guardian Ultra v13.1", layout="wide", page_icon="🛡️")

def format_br(valor, prefixo="R$ "):
    try:
        val = float(valor)
        return f"{prefixo}{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except: return str(valor)

# --- 2. CONEXÃO IA HÍBRIDA (HYDRA) ---
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

# --- 3. SIDEBAR: NAVEGAÇÃO ---
st.sidebar.title("🛡️ Guardian Ultra v13.1")
try:
    # Busca nomes únicos de fundos no banco
    res_f = conn.table("carteira_diaria").select("fundo_nome").execute()
    lista_fundos = sorted(list(set([i['fundo_nome'] for i in res_f.data]))) if res_f.data else []
except: lista_fundos = []

fundo_ativo = st.sidebar.selectbox("Selecione o Fundo:", lista_fundos if lista_fundos else ["Nenhum cadastrado"])
menu = st.sidebar.radio("Ir para:", ["📊 Dashboard", "🤖 Importar Carteira", "📜 Regulamento e Compliance", "📉 Gestão de Passivo"])

# --- 4. 📊 ABA: DASHBOARD ---
if menu == "📊 Dashboard":
    st.subheader(f"📊 Monitor de Compliance: {fundo_ativo}")
    if fundo_ativo != "Nenhum cadastrado":
        c = conn.table("carteira_diaria").select("*").eq("fundo_nome", fundo_ativo).execute()
        r = conn.table("regulamentos").select("*").eq("fundo_nome", fundo_ativo).execute()
        
        if c.data:
            df_c = pd.DataFrame(c.data)
            pl_total = df_c['valor_mercado'].sum()
            st.metric("Patrimônio Líquido Total", format_br(pl_total))
            
            if r.data:
                reg = r.data[0]
                st.info(f"📜 **Mandato:** {reg['descricao_mandato']}")
                
                # Exemplo de visualização de enquadramento simplificado
                # Busca se existe regra de mínimo de 95% (0.95)
                meta_95 = 0.95 
                v_alvo = df_c[df_c['tipo_ativo'].str.contains('Incentivada|Infra|Master', case=False, na=False)]['valor_mercado'].sum()
                perc = v_alvo / pl_total if pl_total > 0 else 0
                
                st.metric("Enquadramento Alvo (Mín 95%)", f"{perc*100:.2f}%", delta=f"{(perc-meta_95)*100:.2f}%")

                with st.expander("📝 Detalhes do Cérebro de Compliance"):
                    col_r, col_m = st.columns(2)
                    col_r.json(reg['regras_json'])
                    col_m.json(reg['mapa_ativos_json'])
            
            st.write("### Composição da Carteira")
            st.dataframe(df_c[['ativo', 'valor_mercado', 'tipo_ativo']].assign(
                valor_mercado=lambda x: x['valor_mercado'].apply(format_br)
            ), use_container_width=True)
        else: st.warning("⚠️ Nenhuma carteira encontrada.")
    else: st.info("Selecione um fundo na barra lateral.")

# --- 5. 🤖 ABA: IMPORTAR CARTEIRA ---
elif menu == "🤖 Importar Carteira":
    st.subheader("📥 Carga de Posição Diária (Excel)")
    upload_c = st.file_uploader("Suba o Excel da Carteira", type=['xlsx'])
    
    if upload_c:
        if st.button("🚀 Processar Carteira com IA"):
            with st.spinner("Analisando ativos e despesas..."):
                try:
                    df = pd.read_excel(upload_c)
                    contexto = df.dropna(how='all').head(300).to_string()
                    
                    prompt_c = f"""
                    Analista de Backoffice: Extraia Nome do Fundo, PL, Cota, Ativos e Despesas.
                    JSON: {{'nome_fundo': 'NOME', 'resumo': {{'pl': 0.0, 'cota': 0.0}}, 'ativos': [{{'ativo': 'NOME', 'valor_mercado': 0.0, 'tipo_ativo': 'TIPO'}}], 'despesas': [{{'item': 'NOME', 'valor': 0.0}}]}}
                    DADOS: {contexto}
                    """
                    res, motor = chamar_ia_hydra(prompt_c)
                    data = json.loads(res.text[res.text.find('{'):res.text.rfind('}')+1])
                    st.session_state['temp_c'] = data
                    st.success(f"Extraído via {motor}")
                    st.write(f"📌 Fundo Identificado: **{data['nome_fundo']}**")
                    st.table(pd.DataFrame(data['ativos']).assign(valor_mercado=lambda x: x['valor_mercado'].apply(format_br)))
                except Exception as e: st.error(f"Erro: {e}")

    if 'temp_c' in st.session_state:
        if st.button("💾 Gravar no Supabase"):
            d = st.session_state['temp_c']
            fundo = d['nome_fundo']
            for a in d['ativos']: a['fundo_nome'] = fundo
            desp = [{"fundo_nome": fundo, "item": ds['item'], "valor": -abs(ds['valor'])} for ds in d['despesas']]
            
            conn.table("carteira_diaria").insert(d['ativos']).execute()
            conn.table("despesas_diarias").insert(desp).execute()
            st.success("Carteira Gravada com Sucesso!")
            del st.session_state['temp_c']
            st.rerun()

# --- 6. 📜 ABA: REGULAMENTO E COMPLIANCE ---
elif menu == "📜 Regulamento e Compliance":
    st.subheader("📜 Arquiteto de Inteligência de Compliance")
    upload_reg = st.file_uploader("Suba o Regulamento (PDF)", type=['pdf'])
    
    if upload_reg:
        if st.button("🚀 Gerar Mapa de Compliance"):
            with st.spinner("IA criando mapa de regras e ativos..."):
                try:
                    reader = PdfReader(upload_reg)
                    texto_completo = ""
                    for page in reader.pages[:15]: texto_completo += page.extract_text()
                    
                    # PROMPT ESTRUTURADO (JGP/INCENTIVADOS)
                    super_prompt = f"""
                    Você é um Engenheiro de Compliance de Fundos. Analise o regulamento e gere um JSON estruturado.
                    
                    TAREFAS:
                    1. Identifique o Nome do Fundo e CNPJ[cite: 8, 22].
                    2. Identifique se é um fundo da Lei 12.431 (Incentivado)[cite: 21, 97].
                    3. Crie um array 'regras' com: id, descricao, fonte, tipo (minimo_percentual ou maximo_percentual), limite_min (use 0.0 a 1.0), limite_max (use 0.0 a 1.0) e categorias afetadas[cite: 97, 269].
                    4. Crie um 'mapa_ativos' vinculando termos ou CNPJs no texto a categorias (ex: 'JGP DEB' -> fundo_deb_incentivada).
                    
                    TEXTO: {texto_completo[:8000]}
                    """
                    res, motor = chamar_ia_hydra(super_prompt)
                    data = json.loads(res.text[res.text.find('{'):res.text.rfind('}')+1])
                    st.session_state['schema_reg'] = data
                    st.success(f"Inteligência gerada via {motor}")
                    st.json(data)
                except Exception as e: st.error(f"Erro na IA: {e}")

        if 'schema_reg' in st.session_state:
            if st.button("💾 Salvar Estrutura e Vincular"):
                d = st.session_state['schema_reg']
                payload = {
                    "fundo_nome": d.get('fundo') or d.get('nome_fundo'),
                    "cnpj": d.get('cnpj'),
                    "descricao_mandato": d.get('descricao'),
                    "regras_json": d.get('regras'),
                    "mapa_ativos_json": d.get('mapa_ativos'),
                    "texto_bruto": "Processado via Guardian v13.1"
                }
                conn.table("regulamentos").upsert(payload, on_conflict="fundo_nome").execute()
                st.success("Regulamento Salvo!")
                del st.session_state['schema_reg']
                st.rerun()

# --- 7. 📉 ABA: PASSIVO ---
elif menu == "📉 Gestão de Passivo":
    st.subheader(f"📉 Movimentações de Cotistas: {fundo_ativo}")
    st.info("Espaço para registro de resgates futuros e projeção de liquidez.")
