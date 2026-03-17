import streamlit as st
import pandas as pd
from st_supabase_connection import SupabaseConnection
import google.generativeai as genai
import json
import re
from datetime import datetime
from pypdf import PdfReader

# --- 1. CONFIGURAÇÃO ---
st.set_page_config(page_title="Guardian Ultra - Stable", layout="wide", page_icon="🛡️")

def format_br(valor, prefixo="R$ "):
    try:
        val = float(valor)
        return f"{prefixo}{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except: return str(valor)

def extrair_data_arquivo(nome_arquivo):
    # Procura formato DD_MM_YYYY ou DD-MM-YYYY no nome do arquivo
    match = re.search(r'(\d{2})[_\-](\d{2})[_\-](\d{4})', nome_arquivo)
    if match:
        dia, mes, ano = match.groups()
        return f"{ano}-{mes}-{dia}"
    return datetime.today().strftime('%Y-%m-%d')

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
    raise Exception("Modelos fora do ar.")

conn = st.connection("supabase", type=SupabaseConnection)

# --- 3. SIDEBAR E NAVEGAÇÃO ---
st.sidebar.title("🛡️ Guardian Ultra")
try:
    res_f = conn.table("regulamentos").select("fundo_nome").execute()
    lista_regulamentos = sorted(list(set([i['fundo_nome'] for i in res_f.data]))) if res_f.data else []
except: lista_regulamentos = []

fundo_ativo = st.sidebar.selectbox("Fundo Ativo:", lista_regulamentos if lista_regulamentos else ["Nenhum"])
menu = st.sidebar.radio("Ir para:", ["📊 Dashboard", "🤖 Importar Carteira", "📜 Regulamento"])

# --- 4. 📊 DASHBOARD ---
if menu == "📊 Dashboard":
    st.subheader(f"📊 Compliance: {fundo_ativo}")
    if fundo_ativo != "Nenhum":
        # Puxa as datas disponíveis para esse fundo específico
        res_datas = conn.table("carteira_diaria").select("data").eq("fundo_nome", fundo_ativo).execute()
        if res_datas.data:
            datas_disp = sorted(list(set([d['data'] for d in res_datas.data])), reverse=True)
            data_selecionada = st.selectbox("📅 Selecione a Data da Posição:", datas_disp)
            
            # Puxa carteira e regulamento com base no Fundo E Data
            c = conn.table("carteira_diaria").select("*").eq("fundo_nome", fundo_ativo).eq("data", data_selecionada).execute()
            r = conn.table("regulamentos").select("*").eq("fundo_nome", fundo_ativo).execute()
            
            if c.data and r.data:
                reg = r.data[0]
                df_c = pd.DataFrame(c.data)
                pl_total = df_c['valor_mercado'].sum()
                
                # --- O Vínculo de Inteligência (Mapa de Ativos) ---
                mapa = reg.get('mapa_ativos_json', {})
                def classificar_ativo(nome):
                    nome_up = str(nome).upper()
                    for chave, tag in mapa.items():
                        if str(chave).upper() in nome_up: return tag
                    return "Outros"
                
                df_c['categoria_compliance'] = df_c['ativo'].apply(classificar_ativo)
                
                st.metric(f"Patrimônio Líquido ({data_selecionada})", format_br(pl_total))
                st.write("### ✅ Enquadramento (Gavetas Matemáticas)")
                
                for regra in reg.get('regras_json', []):
                    ativos_regra = df_c[df_c['categoria_compliance'].isin(regra['categorias'])]
                    perc = ativos_regra['valor_mercado'].sum() / pl_total if pl_total > 0 else 0
                    
                    if regra['tipo'] == 'minimo_percentual':
                        valido = perc >= regra.get('limite_min', 0)
                        alvo = f"Mín. {regra.get('limite_min', 0)*100:.1f}%"
                    else:
                        valido = perc <= regra.get('limite_max', 1)
                        alvo = f"Máx. {regra.get('limite_max', 1)*100:.1f}%"
                    
                    cor = "green" if valido else "red"
                    st.markdown(f"**{regra.get('id', 'Regra')}**: :{cor}[{perc*100:.2f}%] ({alvo})")

                st.write("### 📄 Posição da Carteira")
                st.dataframe(df_c[['ativo', 'valor_mercado', 'tipo_ativo', 'categoria_compliance']].assign(valor_mercado=lambda x: x['valor_mercado'].apply(format_br)))
        else:
            st.warning("Nenhuma carteira importada para este fundo.")
    else:
        st.info("Cadastre um regulamento primeiro.")

# --- 5. 🤖 IMPORTAR CARTEIRA (COM VÍNCULO E DESPESAS REAIS) ---
elif menu == "🤖 Importar Carteira":
    st.subheader("📥 Carga de Dados")
    
    if not lista_regulamentos:
        st.error("⚠️ Cadastre um Regulamento primeiro para poder vincular a carteira.")
    else:
        fundo_vinculo = st.selectbox("🔗 A qual fundo esta carteira pertence?", lista_regulamentos)
        upload_c = st.file_uploader("Excel da Carteira", type=['xlsx'])
        
        if upload_c and st.button("🚀 Processar"):
            data_arq = extrair_data_arquivo(upload_c.name)
            st.info(f"📅 Data identificada no arquivo: {data_arq}")
            
            with st.spinner("IA classificando ativos e despesas..."):
                df = pd.read_excel(upload_c)
                contexto = df.dropna(how='all').head(300).to_string()
                
                prompt_c = f"""
                Analista de Backoffice: Extraia PL, Cota, Ativos e Despesas.
                ATENÇÃO PARA TIPO_ATIVO: Não use 'Cota'. Identifique a natureza: 'Debênture', 'LFT / Tesouro', 'FIDC', 'Ações', 'Disponibilidade'.
                
                JSON: {{
                  'resumo': {{'pl': 0.0, 'cota': 0.0}}, 
                  'ativos': [{{'ativo': 'NOME', 'valor_mercado': 0.0, 'tipo_ativo': 'CLASSIFICAÇÃO REAL'}}], 
                  'despesas': [{{'item': 'NOME_DESPESA', 'valor': 0.0}}]
                }}
                DADOS: {contexto}
                """
                res, motor = chamar_ia_hydra(prompt_c)
                data = json.loads(res.text[res.text.find('{'):res.text.rfind('}')+1])
                
                for d in data.get('despesas', []): d['valor'] = -abs(float(d['valor']))
                
                st.session_state['temp_c'] = {'data': data, 'data_arq': data_arq, 'fundo': fundo_vinculo}
                
                c1, c2 = st.columns(2)
                c1.metric("PL Identificado", format_br(data['resumo']['pl']))
                c2.metric("Cota", f"R$ {data['resumo']['cota']:.6f}")
                
                st.write("### Ativos")
                st.dataframe(pd.DataFrame(data['ativos']))
                if data.get('despesas'):
                    st.write("### Despesas")
                    st.dataframe(pd.DataFrame(data['despesas']))

        if 'temp_c' in st.session_state and st.button("💾 Gravar Carteira"):
            tc = st.session_state['temp_c']
            fn, dt, d = tc['fundo'], tc['data_arq'], tc['data']
            
            for a in d.get('ativos', []): 
                a['fundo_nome'] = fn
                a['data'] = dt
            for ds in d.get('despesas', []): 
                ds['fundo_nome'] = fn
                ds['data'] = dt
            
            if d.get('ativos'): conn.table("carteira_diaria").insert(d['ativos']).execute()
            if d.get('despesas'): conn.table("despesas_diarias").insert(d['despesas']).execute()
            
            st.success(f"Posição do dia {dt} para {fn} gravada com sucesso!")
            del st.session_state['temp_c']

# --- 6. 📜 REGULAMENTO (À PROVA DE ERROS) ---
elif menu == "📜 Regulamento":
    st.subheader("📜 Arquiteto de Compliance")
    upload_reg = st.file_uploader("Suba o PDF", type=['pdf'])
    
    if upload_reg and st.button("🚀 Mapear Fundo"):
        with st.spinner("Analisando Anexo e Política de Investimento..."):
            try:
                reader = PdfReader(upload_reg)
                texto = "".join([p.extract_text() for p in reader.pages[:40]])
                
                super_prompt = f"""
                Analista de Risco: Transforme o regulamento em JSON rigoroso.
                TIPO: 'minimo_percentual' ou 'maximo_percentual'. LIMITES: Use 0.0 a 1.0 (ex: 95% = 0.95).
                JSON: {{ "fundo": "NOME_DO_FUNDO", "cnpj": "CNPJ", "mandato": "Mandato", "regras": [{{ "id": "ID", "tipo": "minimo_percentual", "limite_min": 0.0, "categorias": ["CAT"] }}], "mapa_ativos": {{ "TERMO": "CAT" }}, "categorias_definidas": {{ "CAT": "DESC" }} }}
                TEXTO: {texto[:25000]}
                """
                res, motor = chamar_ia_hydra(super_prompt)
                data = json.loads(res.text[res.text.find('{'):res.text.rfind('}')+1])
                st.session_state['schema_reg'] = data
                st.json(data)
            except Exception as e: st.error(f"Erro na extração: {e}")

    if 'schema_reg' in st.session_state and st.button("💾 Salvar Regulamento"):
        d = st.session_state['schema_reg']
        # Uso do .get() garante que se a IA omitir algo, o código não quebra
        payload = {
            "fundo_nome": d.get('fundo', 'FUNDO_SEM_NOME'),
            "cnpj": d.get('cnpj', ''),
            "descricao_mandato": d.get('mandato', ''),
            "regras_json": d.get('regras', []),
            "mapa_ativos_json": d.get('mapa_ativos', {}),
            "categorias_definidas": d.get('categorias_definidas', {})
        }
        try:
            conn.table("regulamentos").upsert(payload, on_conflict="fundo_nome").execute()
            st.success("Regulamento estruturado e salvo!")
            del st.session_state['schema_reg']
            st.rerun()
        except Exception as e:
            st.error(f"Erro de banco de dados: {e}")
