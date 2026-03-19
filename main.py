import streamlit as st
import pandas as pd
from st_supabase_connection import SupabaseConnection
import google.generativeai as genai
import json
import re
import requests
import base64
from datetime import datetime
from pypdf import PdfReader

# --- 1. CONFIGURAÇÃO E ESTILO ---
st.set_page_config(page_title="Guardian Ultra v33", layout="wide", page_icon="🛡️")

st.markdown("""
    <style>
    .card-checker { border-left: 4px solid #f39c12; padding: 15px; background-color: #2c2c2c; margin-bottom: 10px; border-radius: 5px;}
    .desenquadrado { color: #ff4b4b; font-weight: bold; }
    </style>
""", unsafe_allow_html=True)

def format_br(valor, prefixo="R$ "):
    try:
        val = float(valor)
        return f"{prefixo}{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except: return str(valor)

def extrair_data_arquivo(nome_arquivo):
    match = re.search(r'(\d{2})[_\-](\d{2})[_\-](\d{4})', nome_arquivo)
    if match: return f"{match.group(3)}-{match.group(2)}-{match.group(1)}"
    return datetime.today().strftime('%Y-%m-%d')

def extrair_json_seguro(texto_ia):
    try:
        inicio = texto_ia.find('{')
        fim = texto_ia.rfind('}') + 1
        return json.loads(texto_ia[inicio:fim])
    except: return {}

# --- 2. CONEXÃO IA E APIs ---
gemini_key = st.secrets.get("GEMINI_API_KEY")
anbima_client_id = st.secrets.get("ANBIMA_CLIENT_ID")
anbima_client_secret = st.secrets.get("ANBIMA_CLIENT_SECRET")

if gemini_key: genai.configure(api_key=gemini_key)
MODELOS = ['models/gemini-1.5-flash', 'models/gemini-3.1-flash-lite-preview']

def chamar_ia_hydra(prompt):
    for m in MODELOS:
        try:
            model = genai.GenerativeModel(m)
            return model.generate_content(prompt), m
        except: continue
    raise Exception("Modelos IA indisponíveis.")

def obter_token_anbima():
    if not anbima_client_id or not anbima_client_secret: return None
    url = "https://api.anbima.com.br/oauth/access-token"
    auth_str = f"{anbima_client_id}:{anbima_client_secret}"
    b64_auth_str = base64.b64encode(auth_str.encode()).decode()
    headers = {"Authorization": f"Basic {b64_auth_str}", "Content-Type": "application/json"}
    payload = {"grant_type": "client_credentials"}
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=5)
        if resp.status_code == 200: return resp.json().get("access_token")
    except: return None
    return None

def consultar_fundo_anbima(cnpj):
    token = obter_token_anbima()
    if not token: return None
    cnpj_limpo = re.sub(r'[^0-9]', '', cnpj)
    url = f"https://api.anbima.com.br/feed/fundos/v2/fundos/{cnpj_limpo}"
    headers = {"client_id": anbima_client_id, "access_token": token}
    try:
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code == 200:
            dados = resp.json()
            nome = dados.get('informacoes_cadastrais', {}).get('denominacao_social', cnpj)
            classe = dados.get('informacoes_cadastrais', {}).get('classe_anbima', 'Fundo')
            return f"{nome} ({classe})"
    except: return None
    return None

def consultar_brasil_api(cnpj):
    cnpj_limpo = re.sub(r'[^0-9]', '', cnpj)
    url = f"https://brasilapi.com.br/api/cnpj/v1/{cnpj_limpo}"
    try:
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            dados = resp.json()
            return dados.get("razao_social", cnpj)
    except: return None
    return None

conn = st.connection("supabase", type=SupabaseConnection)

# --- 3. SIDEBAR ---
st.sidebar.title("🛡️ Guardian Terminal")
try:
    res_f = conn.table("regulamentos").select("fundo_nome").execute()
    lista_regulamentos = sorted(list(set([i['fundo_nome'] for i in res_f.data]))) if res_f.data else []
except: lista_regulamentos = []

fundo_ativo = st.sidebar.selectbox("Fundo Ativo:", lista_regulamentos if lista_regulamentos else ["Nenhum"])
menu = st.sidebar.radio("Navegação:", ["📊 Dashboard", "🤖 Importar Carteira", "📉 Mesa de Operações", "📜 Regulamento"])

# --- 4. 📊 DASHBOARD ---
if menu == "📊 Dashboard":
    st.subheader(f"📊 Monitoramento em Tempo Real: {fundo_ativo}")
    if fundo_ativo != "Nenhum":
        res_datas = conn.table("carteira_diaria").select("data").eq("fundo_nome", fundo_ativo).execute()
        if res_datas.data:
            datas_disp = sorted(list(set([d['data'] for d in res_datas.data])), reverse=True)
            data_selecionada = st.selectbox("📅 Data da Posição:", datas_disp)
            
            c = conn.table("carteira_diaria").select("*").eq("fundo_nome", fundo_ativo).eq("data", data_selecionada).execute()
            d = conn.table("despesas_diarias").select("*").eq("fundo_nome", fundo_ativo).eq("data", data_selecionada).execute()
            r = conn.table("regulamentos").select("*").eq("fundo_nome", fundo_ativo).execute()
            
            if c.data and r.data:
                reg = r.data[0]
                df_c = pd.DataFrame(c.data)
                df_d = pd.DataFrame(d.data) if d.data else pd.DataFrame(columns=['item', 'valor'])
                
                total_ativos = df_c['valor_mercado'].sum()
                total_despesas = df_d['valor'].sum() if not df_d.empty else 0
                pl_liquido = total_ativos + total_despesas
                
                col1, col2, col3 = st.columns(3)
                col1.metric("Total Ativos", format_br(total_ativos))
                col2.metric("Despesas Provisionadas", format_br(total_despesas))
                col3.metric(f"Patrimônio Líquido ({data_selecionada})", format_br(pl_liquido))
                
                st.write("### ✅ Enquadramento Legal")
                for regra in reg.get('regras_json', []):
                    # Só soma na regra os ativos que a IA classificou CORRETAMENTE na gaveta (sem "Desenquadrado")
                    ativos_regra = df_c[df_c['gaveta_matematica'].isin(regra['categorias'])]
                    v_soma = ativos_regra['valor_mercado'].sum()
                    perc = v_soma / pl_liquido if pl_liquido > 0 else 0
                    
                    if regra['tipo'] == 'minimo_percentual':
                        valido = perc >= regra.get('limite_min', 0)
                        alvo = f"Mínimo exigido: {regra.get('limite_min', 0)*100:.1f}%"
                    else:
                        valido = perc <= regra.get('limite_max', 1)
                        alvo = f"Máximo permitido: {regra.get('limite_max', 1)*100:.1f}%"
                    
                    cor = "green" if valido else "red"
                    st.markdown(f"**{regra.get('id', 'Regra')}**: :{cor}[{perc*100:.2f}%] ({alvo})")

                st.write("### 📄 Carteira Consolidada")
                df_view = df_c[['ativo', 'valor_mercado', 'tipo_ativo', 'gaveta_matematica']].copy()
                df_view['% PL'] = (df_view['valor_mercado'] / pl_liquido * 100).apply(lambda x: f"{x:.2f}%")
                df_view['valor_mercado'] = df_view['valor_mercado'].apply(format_br)
                
                # Destaca os desenquadrados na tabela
                def colorir_desenquadrado(val):
                    color = '#ff4b4b' if val == 'Desenquadrado' else ''
                    return f'color: {color}'
                
                st.dataframe(df_view[['ativo', 'valor_mercado', '% PL', 'tipo_ativo', 'gaveta_matematica']].style.map(colorir_desenquadrado, subset=['gaveta_matematica']), use_container_width=True)
                
                if not df_d.empty:
                    with st.expander("💸 Visualizar Despesas"):
                        df_d_view = df_d[['item', 'valor']].copy()
                        df_d_view['% PL'] = (df_d_view['valor'] / pl_liquido * 100).apply(lambda x: f"{x:.4f}%")
                        df_d_view['valor'] = df_d_view['valor'].apply(format_br)
                        st.dataframe(df_d_view, use_container_width=True)
        else: st.warning("Nenhuma carteira importada para este fundo.")

# --- 5. 🤖 IMPORTAR CARTEIRA (O FIM DO FORCED FIT) ---
elif menu == "🤖 Importar Carteira":
    st.subheader("📥 Carga Inicial e Classificação")
    if not lista_regulamentos:
        st.error("⚠️ Cadastre o Regulamento do fundo primeiro.")
    else:
        fundo_vinculo = st.selectbox("🔗 Vincular à carteira do fundo:", lista_regulamentos)
        upload_c = st.file_uploader("Arquivo Excel", type=['xlsx'])
        
        if upload_c and st.button("🚀 Processar Arquivo"):
            data_arq = extrair_data_arquivo(upload_c.name)
            with st.spinner("Motor de IA lendo mercado e regulamento (Aplicando travas)..."):
                r_vinculo = conn.table("regulamentos").select("categorias_definidas").eq("fundo_nome", fundo_vinculo).execute()
                chaves_permitidas = list(r_vinculo.data[0].get('categorias_definidas', {}).keys()) if (r_vinculo.data and r_vinculo.data[0].get('categorias_definidas')) else []

                df = pd.read_excel(upload_c)
                
                # PROMPT COM FEW-SHOT EXAMPLES (Exemplos rígidos para ela não alucinar)
                prompt_c = f"""
                Você é um Analista de Risco de Compliance IMPLACÁVEL.
                Sua tarefa é analisar a carteira de investimentos enviada e encaixá-la nas gavetas do regulamento.
                As ÚNICAS chaves de gaveta permitidas são: {chaves_permitidas}.

                REGRAS DE OURO:
                1. 'tipo_ativo': Qual a natureza REAL e TÉCNICA do ativo? (Ex: Fundo Multimercado, LFT, Fundo de Ações, FIDC). Se tiver 'FIM', é Multimercado.
                2. 'gaveta_matematica': Se a natureza do ativo NÃO FOR A EXATA DEFINIÇÃO da gaveta, escreva 'Desenquadrado'. É PROIBIDO forçar encaixes.

                EXEMPLOS PRÁTICOS (SIGA ESTRITAMENTE):
                - Se ativo é "SPX HRNT Fundo Multimercado" e gavetas são ["cotas_fic_fidc", "caixa"], a gaveta DEVE SER "Desenquadrado".
                - Se ativo é "Fundo de Debêntures" e as gavetas são ["cotas_fic_fidc"], a gaveta DEVE SER "Desenquadrado".
                - Se ativo é "FIDC Multiplica" e gavetas são ["cotas_fic_fidc"], a gaveta DEVE SER "cotas_fic_fidc".
                - Se ativo é "Tesouro Selic" e gavetas são ["ativos_liquidez"], a gaveta DEVE SER "ativos_liquidez".
                
                JSON DE SAÍDA: {{'resumo': {{'pl': 0.0, 'cota': 0.0}}, 'ativos': [{{'ativo': 'NOME', 'valor_mercado': 0.0, 'tipo_ativo': 'NATUREZA_REAL', 'gaveta_matematica': 'CHAVE_EXATA_OU_DESENQUADRADO'}}], 'despesas': [{{'item': 'NOME', 'valor': 0.0}}]}}
                DADOS: {df.dropna(how='all').head(300).to_string()}
                """
                res, motor = chamar_ia_hydra(prompt_c)
                data = extrair_json_seguro(res.text)
                
                if data:
                    for d in data.get('despesas', []): d['valor'] = -abs(float(d.get('valor', 0)))
                    st.session_state['temp_c'] = {'data': data, 'data_arq': data_arq, 'fundo': fundo_vinculo}
                    st.success("Análise de Risco Concluída!")
                    st.dataframe(pd.DataFrame(data.get('ativos', [])))
                else: st.error("A IA retornou um formato inválido. Tente novamente.")

        if 'temp_c' in st.session_state and st.button("💾 Gravar no Database"):
            tc = st.session_state['temp_c']
            fn, dt, d = tc['fundo'], tc['data_arq'], tc['data']
            for a in d.get('ativos', []): a['fundo_nome'] = fn; a['data'] = dt
            for ds in d.get('despesas', []): ds['fundo_nome'] = fn; ds['data'] = dt
            if d.get('ativos'): conn.table("carteira_diaria").insert(d['ativos']).execute()
            if d.get('despesas'): conn.table("despesas_diarias").insert(d['despesas']).execute()
            st.success("Carteira gravada com sucesso!")
            del st.session_state['temp_c']
            st.rerun()

# --- 6. 📉 MESA DE OPERAÇÕES ---
elif menu == "📉 Mesa de Operações":
    st.subheader(f"📉 OMS (Order Management System): {fundo_ativo}")
    if fundo_ativo != "Nenhum":
        res_datas = conn.table("carteira_diaria").select("data").eq("fundo_nome", fundo_ativo).execute()
        if res_datas.data:
            datas_disp = sorted(list(set([d['data'] for d in res_datas.data])), reverse=True)
            data_sel = st.selectbox("📅 Refletir operações na carteira do dia:", datas_disp)
            
            c_ativos = conn.table("carteira_diaria").select("*").eq("fundo_nome", fundo_ativo).eq("data", data_sel).execute()
            df_ativos = pd.DataFrame(c_ativos.data) if c_ativos.data else pd.DataFrame()
            
            aba1, aba2 = st.tabs(["🔀 Lançar Ordem (Maker)", "📋 Fila de Aprovação & Histórico (Checker)"])
            
            with aba1:
                with st.container(border=True):
                    st.markdown("#### 📝 Lançamento de Ordem")
                    tipo_ativo_boleta = st.radio("Selecione o tipo de ordem:", ["Ativo Existente na Carteira", "Novo Ativo (Pré-Trade c/ Consulta)"], horizontal=True)
                    st.divider()
                    
                    with st.form("form_boleta_oms"):
                        col_t, col_a, col_v = st.columns([1, 2, 1])
                        tipo_mov = col_t.selectbox("Natureza", ["Compra", "Venda"])
                        valor_mov = col_v.number_input("Volume Financeiro (R$)", min_value=0.01, step=10000.0, format="%.2f")
                        
                        if "Existente" in tipo_ativo_boleta:
                            ativo_mov = col_a.selectbox("Ativo Alvo", df_ativos['ativo'].tolist() if not df_ativos.empty else [])
                            if st.form_submit_button("Gerar Boleta Pendente"):
                                linha_ativo = df_ativos[df_ativos['ativo'] == ativo_mov].iloc[0]
                                payload = {
                                    "fundo_nome": fundo_ativo, "data": data_sel, "tipo": tipo_mov, 
                                    "ativo": ativo_mov, "valor": valor_mov, 
                                    "tipo_ativo_ia": linha_ativo['tipo_ativo'], "gaveta_ia": linha_ativo['gaveta_matematica'],
                                    "status": "Pendente"
                                }
                                conn.table("movimentacoes_ativo").insert(payload).execute()
                                st.success(f"Ordem de {tipo_mov} de {ativo_mov} enviada para o Checker.")
                        else:
                            ativo_mov = col_a.text_input("Ticker ou CNPJ (Ex: 51.556.428/0001-56)")
                            if st.form_submit_button("Consultar e Analisar Risco") and ativo_mov:
                                with st.spinner("Buscando CNPJ e cruzando com o Compliance..."):
                                    identificacao_real = ativo_mov
                                    if re.search(r'\d', ativo_mov):
                                        cnpj_limpo = re.sub(r'[^0-9]', '', ativo_mov)
                                        if len(cnpj_limpo) == 14:
                                            res_anbima = consultar_fundo_anbima(cnpj_limpo)
                                            if res_anbima:
                                                identificacao_real = res_anbima
                                                st.info(f"✅ ANBIMA Localizou: **{identificacao_real}**")
                                            else:
                                                res_rfb = consultar_brasil_api(cnpj_limpo)
                                                if res_rfb:
                                                    identificacao_real = res_rfb
                                                    st.info(f"✅ Receita Federal Localizou: **{identificacao_real}**")
                                                else: st.warning("⚠️ CNPJ não achado. Usando IA pura.")
                                    
                                    r_vinculo = conn.table("regulamentos").select("categorias_definidas").eq("fundo_nome", fundo_ativo).execute()
                                    chaves = list(r_vinculo.data[0].get('categorias_definidas', {}).keys()) if r_vinculo.data else []
                                    
                                    # PROMPT FEW-SHOT PRÉ-TRADE
                                    prompt_pre = f"""
                                    O gestor está boletando: '{identificacao_real}'.
                                    1. 'tipo_ativo': Diga a natureza TÉCNICA real desse ativo (ex: Fundo Multimercado, Debênture). SE ler 'FIM' ou 'Multimercado', classifique como Multimercado.
                                    2. 'gaveta_matematica': As ÚNICAS gavetas permitidas são: {chaves}. 
                                    - Se a natureza do ativo NÃO BATER com a gaveta, retorne 'Desenquadrado'.
                                    - Ex: Se ativo é Fundo Multimercado e a gaveta é 'cotas_fic_fidc', retorne 'Desenquadrado'.
                                    
                                    JSON EXATO: {{ "tipo_ativo": "NATUREZA", "gaveta_matematica": "CHAVE_OU_DESENQUADRADO" }}
                                    """
                                    res, motor = chamar_ia_hydra(prompt_pre)
                                    classif = extrair_json_seguro(res.text)
                                    
                                    tipo_ia = classif.get('tipo_ativo', 'Desconhecido')
                                    gaveta_ia = classif.get('gaveta_matematica', 'Desenquadrado')
                                    
                                    payload = {
                                        "fundo_nome": fundo_ativo, "data": data_sel, "tipo": "Compra", 
                                        "ativo": identificacao_real, "valor": valor_mov, 
                                        "tipo_ativo_ia": tipo_ia, "gaveta_ia": gaveta_ia,
                                        "status": "Pendente"
                                    }
                                    conn.table("movimentacoes_ativo").insert(payload).execute()
                                    
                                    cor = "red" if gaveta_ia == 'Desenquadrado' else "green"
                                    st.info(f"🧠 **Diagnóstico IA:** Natureza: **{tipo_ia}**. Gaveta: :{cor}[**{gaveta_ia}**].")
                                    st.success("Ordem aguardando aprovação no Checker.")

            with aba2:
                hist = conn.table("movimentacoes_ativo").select("*").eq("fundo_nome", fundo_ativo).order("data", desc=True).execute()
                if hist.data:
                    df_hist = pd.DataFrame(hist.data)
                    pendentes = [op for op in hist.data if op['status'] == 'Pendente']
                    
                    if pendentes:
                        st.markdown("### ⚠️ Fila de Aprovação (Double Check)")
                        for op in pendentes:
                            st.markdown(f'<div class="card-checker">', unsafe_allow_html=True)
                            st.markdown(f"**Ordem #{op['id'].split('-')[0]}** | **{op['tipo']}** de {op['ativo']}")
                            
                            c_info1, c_info2 = st.columns(2)
                            c_info1.markdown(f"💰 **Volume Financeiro:** {format_br(op['valor'])}")
                            
                            cor_g = "red" if op['gaveta_ia'] == 'Desenquadrado' else "green"
                            c_info2.markdown(f"🔍 **Natureza Real:** {op['tipo_ativo_ia']}<br>🗄️ **Enquadramento no Fundo:** <span style='color:{cor_g}'><b>{op['gaveta_ia']}</b></span>", unsafe_allow_html=True)
                            
                            col_btn1, col_btn2, col_btn3 = st.columns([1, 1, 2])
                            if col_btn1.button("✅ Aprovar", key=f"apr_{op['id']}"):
                                ativo_existente = df_ativos[df_ativos['ativo'] == op['ativo']]
                                if not ativo_existente.empty:
                                    id_carteira = ativo_existente.iloc[0]['id']
                                    val_atual = float(ativo_existente.iloc[0]['valor_mercado'])
                                    novo_val = val_atual + float(op['valor']) if op['tipo'] == "Compra" else val_atual - float(op['valor'])
                                    conn.table("carteira_diaria").update({"valor_mercado": novo_val}).eq("id", id_carteira).execute()
                                else:
                                    conn.table("carteira_diaria").insert({"data": op['data'], "fundo_nome": fundo_ativo, "ativo": op['ativo'], "valor_mercado": float(op['valor']), "tipo_ativo": op['tipo_ativo_ia'], "gaveta_matematica": op['gaveta_ia']}).execute()
                                
                                conn.table("movimentacoes_ativo").update({"status": "Confirmada"}).eq("id", op['id']).execute()
                                st.rerun()
                                
                            if col_btn2.button("❌ Recusar", key=f"rec_{op['id']}"):
                                conn.table("movimentacoes_ativo").update({"status": "Cancelada"}).eq("id", op['id']).execute()
                                st.rerun()
                                
                            with col_btn3.expander("✏️ Editar Valor"):
                                novo_v = st.number_input("Corrigir", value=float(op['valor']), key=f"ed_{op['id']}")
                                if st.button("Salvar", key=f"btn_ed_{op['id']}"):
                                    conn.table("movimentacoes_ativo").update({"valor": novo_v}).eq("id", op['id']).execute()
                                    st.rerun()
                            st.markdown('</div>', unsafe_allow_html=True)
                    
                    st.divider()
                    st.markdown("### 📋 Trade Blotter (Histórico Geral)")
                    df_view_hist = df_hist[['data', 'tipo', 'ativo', 'valor', 'tipo_ativo_ia', 'gaveta_ia', 'status']].copy()
                    df_view_hist['valor'] = df_view_hist['valor'].apply(format_br)
                    st.dataframe(df_view_hist, use_container_width=True)
                else: st.info("O Order Book está vazio para este fundo.")
        else: st.warning("Importe a carteira base primeiro.")

# --- 7. 📜 REGULAMENTO ---
elif menu == "📜 Regulamento":
    st.subheader("📜 Arquiteto de Risco (CVM 175)")
    upload_reg = st.file_uploader("Suba o PDF", type=['pdf'])
    
    if upload_reg and st.button("🚀 Mapear Cérebro de Compliance"):
        with st.spinner("Análise Profunda ativada..."):
            try:
                reader = PdfReader(upload_reg)
                texto = "".join([p.extract_text() for p in reader.pages[:60]])
                
                prompt_reg = f"""
                Auditor de Risco Sênior CVM. Transforme em JSON.
                1. FOQUE nas regras PERMANENTES.
                2. IGNORE carências iniciais.
                JSON EXATO: {{ "fundo": "NOME COMPLETO", "cnpj": "CNPJ", "mandato": "Mandato", "regras": [{{ "id": "minimo", "tipo": "minimo_percentual", "limite_min": 0.67, "categorias": ["chave_1"] }}], "categorias_definidas": {{ "chave_1": "Descricao" }} }}
                TEXTO: {texto[:35000]}
                """
                res, motor = chamar_ia_hydra(prompt_reg)
                data = extrair_json_seguro(res.text)
                if data:
                    st.session_state['schema_reg'] = data
                    st.json(data)
                else: st.error("IA falhou na extração.")
            except Exception as e: st.error(f"Erro: {e}")

    if 'schema_reg' in st.session_state and st.button("💾 Ativar Compliance"):
        d = st.session_state['schema_reg']
        payload = {
            "fundo_nome": d.get('fundo', 'Fundo Sem Nome'), "cnpj": d.get('cnpj', ''), "descricao_mandato": d.get('mandato', ''),
            "regras_json": d.get('regras', []), "categorias_definidas": d.get('categorias_definidas', {})
        }
        conn.table("regulamentos").upsert(payload, on_conflict="fundo_nome").execute()
        st.success("Motor matemático ativado!")
        del st.session_state['schema_reg']
        st.rerun()
