import streamlit as st
import pandas as pd
from st_supabase_connection import SupabaseConnection
import google.generativeai as genai
import json
import re
from datetime import datetime
from pypdf import PdfReader

# --- 1. CONFIGURAÇÃO ---
st.set_page_config(page_title="Guardian Ultra v22", layout="wide", page_icon="🛡️")

def format_br(valor, prefixo="R$ "):
    try:
        val = float(valor)
        return f"{prefixo}{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except: return str(valor)

def extrair_data_arquivo(nome_arquivo):
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
    raise Exception("Modelos IA fora do ar.")

conn = st.connection("supabase", type=SupabaseConnection)

# --- 3. SIDEBAR ---
st.sidebar.title("🛡️ Guardian Ultra v22")
try:
    res_f = conn.table("regulamentos").select("fundo_nome").execute()
    lista_regulamentos = sorted(list(set([i['fundo_nome'] for i in res_f.data]))) if res_f.data else []
except: lista_regulamentos = []

fundo_ativo = st.sidebar.selectbox("Fundo Ativo:", lista_regulamentos if lista_regulamentos else ["Nenhum"])
menu = st.sidebar.radio("Ir para:", ["📊 Dashboard", "🤖 Importar Carteira", "📜 Regulamento"])

# --- 4. 📊 DASHBOARD (COMPLIANCE IMPLACÁVEL) ---
if menu == "📊 Dashboard":
    st.subheader(f"📊 Compliance: {fundo_ativo}")
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
                
                # PL REAL (Ativos + Despesas que já estão negativas)
                total_ativos = df_c['valor_mercado'].sum()
                total_despesas = df_d['valor'].sum() if not df_d.empty else 0
                pl_liquido = total_ativos + total_despesas
                
                col1, col2, col3 = st.columns(3)
                col1.metric("Total Ativos", format_br(total_ativos))
                col2.metric("Total Despesas", format_br(total_despesas))
                col3.metric(f"PL Líquido ({data_selecionada})", format_br(pl_liquido))
                
                # --- A PONTE DE COMPLIANCE ---
                mapa_ativos = reg.get('mapa_ativos_json', {}) or {}
                
                def definir_gaveta_compliance(linha):
                    # 1. Verifica se o ativo está mapeado especificamente pelo nome no regulamento
                    nome_up = str(linha['ativo']).upper()
                    for chave_mapa, categoria_regra in mapa_ativos.items():
                        if str(chave_mapa).upper() in nome_up:
                            return categoria_regra
                    # 2. Se não estiver mapeado, usa a natureza real que a IA identificou na importação
                    return linha['tipo_ativo']

                df_c['gaveta_matematica'] = df_c.apply(definir_gaveta_compliance, axis=1)

                st.write("### ✅ Enquadramento do Regulamento")
                for regra in reg.get('regras_json', []):
                    # Filtra a carteira baseando-se na gaveta que bate com a regra
                    ativos_regra = df_c[df_c['gaveta_matematica'].isin(regra['categorias'])]
                    v_soma = ativos_regra['valor_mercado'].sum()
                    perc = v_soma / pl_liquido if pl_liquido > 0 else 0
                    
                    if regra['tipo'] == 'minimo_percentual':
                        valido = perc >= regra.get('limite_min', 0)
                        alvo = f"Mín. {regra.get('limite_min', 0)*100:.1f}%"
                    else:
                        valido = perc <= regra.get('limite_max', 1)
                        alvo = f"Máx. {regra.get('limite_max', 1)*100:.1f}%"
                    
                    cor = "green" if valido else "red"
                    st.markdown(f"**{regra.get('id', 'Regra')}**: :{cor}[{perc*100:.2f}%] ({alvo})")

                col_t1, col_t2 = st.columns(2)
                with col_t1:
                    st.write("### 📄 Carteira: Natureza Real vs Compliance")
                    # Mostra a verdade (tipo_ativo) e como o sistema enquadrou (gaveta_matematica)
                    df_view = df_c[['ativo', 'valor_mercado', 'tipo_ativo', 'gaveta_matematica']].copy()
                    df_view['valor_mercado'] = df_view['valor_mercado'].apply(format_br)
                    st.dataframe(df_view, use_container_width=True)
                with col_t2:
                    st.write("### 💸 Despesas")
                    if not df_d.empty:
                        st.dataframe(df_d[['item', 'valor']].assign(valor=lambda x: x['valor'].apply(format_br)), use_container_width=True)
                    else:
                        st.info("Nenhuma despesa registrada.")
        else:
            st.warning("Importe a carteira para este fundo na data selecionada.")

# --- 5. 🤖 IMPORTAR CARTEIRA (A VERDADE NUA E CRUA) ---
elif menu == "🤖 Importar Carteira":
    st.subheader("📥 Carga de Dados e Identificação de Mercado")
    
    if not lista_regulamentos:
        st.error("⚠️ Cadastre um Regulamento primeiro para poder vincular a carteira.")
    else:
        fundo_vinculo = st.selectbox("🔗 A qual fundo esta carteira pertence?", lista_regulamentos)
        upload_c = st.file_uploader("Excel da Carteira", type=['xlsx'])
        
        if upload_c and st.button("🚀 Extrair a Verdade da Carteira"):
            data_arq = extrair_data_arquivo(upload_c.name)
            st.info(f"📅 Data identificada: {data_arq}")
            
            with st.spinner("Analisando a natureza real de cada ativo..."):
                df = pd.read_excel(upload_c)
                contexto = df.dropna(how='all').head(300).to_string()
                
                # PROMPT INDEPENDENTE: Não olha pro regulamento, olha pro mercado.
                prompt_c = f"""
                Você é um Analista de Mercado Financeiro Independente.
                Sua tarefa é ler a carteira e identificar a NATUREZA REAL de cada ativo no mercado brasileiro.
                Exemplos de natureza: 'Fundo de Renda Fixa', 'Debênture Incentivada', 'Debênture Comum', 'LFT', 'CDB', 'FIDC', 'Ação'.
                NÃO use termos genéricos como 'Cota' ou 'Portfólio Inv'. Diga o que o ativo realmente é. Extraia também as despesas (Auditoria, Custódia, etc).
                
                JSON: {{
                  'resumo': {{'pl': 0.0, 'cota': 0.0}}, 
                  'ativos': [{{'ativo': 'NOME', 'valor_mercado': 0.0, 'tipo_ativo': 'NATUREZA_REAL'}}], 
                  'despesas': [{{'item': 'NOME', 'valor': 0.0}}]
                }}
                DADOS DO EXCEL: {contexto}
                """
                res, motor = chamar_ia_hydra(prompt_c)
                data = json.loads(res.text[res.text.find('{'):res.text.rfind('}')+1])
                
                # Garante que despesas fiquem negativas
                for d in data.get('despesas', []): d['valor'] = -abs(float(d['valor']))
                
                st.session_state['temp_c'] = {'data': data, 'data_arq': data_arq, 'fundo': fundo_vinculo}
                
                st.write(f"### Validação Extraída ({motor})")
                col_a, col_b = st.columns(2)
                col_a.metric("PL Lido", format_br(data['resumo']['pl']))
                col_b.metric("Cota", f"R$ {data['resumo']['cota']:.6f}")
                
                st.write("**Ativos (Natureza Real)**")
                st.dataframe(pd.DataFrame(data['ativos']).assign(valor_mercado=lambda x: x['valor_mercado'].apply(format_br)))
                
                if data.get('despesas'):
                    st.write("**Despesas Encontradas**")
                    st.dataframe(pd.DataFrame(data['despesas']))

        if 'temp_c' in st.session_state and st.button("💾 Gravar no Banco de Dados"):
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
            
            st.success(f"Dados salvos! Vá para o Dashboard ver o cruzamento de regras.")
            del st.session_state['temp_c']

# --- 6. 📜 REGULAMENTO (O ARQUITETO) ---
elif menu == "📜 Regulamento":
    st.subheader("📜 Arquiteto de Compliance")
    upload_reg = st.file_uploader("Suba o PDF", type=['pdf'])
    
    if upload_reg and st.button("🚀 Mapear Estrutura"):
        with st.spinner("Fatiando texto em regras matemáticas..."):
            try:
                reader = PdfReader(upload_reg)
                texto = "".join([p.extract_text() for p in reader.pages[:40]])
                
                super_prompt = f"""
                Analista CVM: Transforme o regulamento em JSON rigoroso.
                TIPO: 'minimo_percentual' ou 'maximo_percentual'. LIMITES: Use 0.0 a 1.0.
                MAPA DE ATIVOS: Dicionário para atrelar CNPJs ou Nomes de Ativos Específicos (ex: 'SPARTA') às categorias das regras.
                
                JSON: {{ "fundo": "NOME", "cnpj": "CNPJ", "mandato": "Mandato", "regras": [{{ "id": "ID", "tipo": "minimo_percentual", "limite_min": 0.0, "categorias": ["CAT"] }}], "mapa_ativos": {{ "TERMO_ESPECIFICO": "CAT" }}, "categorias_definidas": {{ "CAT": "DESC" }} }}
                TEXTO: {texto[:25000]}
                """
                res, motor = chamar_ia_hydra(super_prompt)
                data = json.loads(res.text[res.text.find('{'):res.text.rfind('}')+1])
                st.session_state['schema_reg'] = data
                st.json(data)
            except Exception as e: st.error(f"Erro: {e}")

    if 'schema_reg' in st.session_state and st.button("💾 Salvar Cérebro"):
        d = st.session_state['schema_reg']
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
            st.success("Regulamento ativado!")
            del st.session_state['schema_reg']
            st.rerun()
        except Exception as e:
            st.error(f"Erro SQL: {e}")
