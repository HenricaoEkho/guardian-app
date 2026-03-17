import streamlit as st
import pandas as pd
from st_supabase_connection import SupabaseConnection
import google.generativeai as genai
import json
import re
from datetime import datetime
from pypdf import PdfReader

# --- 1. CONFIGURAÇÃO ---
st.set_page_config(page_title="Guardian Ultra v24", layout="wide", page_icon="🛡️")

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
st.sidebar.title("🛡️ Guardian Ultra v24")
try:
    res_f = conn.table("regulamentos").select("fundo_nome").execute()
    lista_regulamentos = sorted(list(set([i['fundo_nome'] for i in res_f.data]))) if res_f.data else []
except: lista_regulamentos = []

fundo_ativo = st.sidebar.selectbox("Fundo Ativo:", lista_regulamentos if lista_regulamentos else ["Nenhum"])
menu = st.sidebar.radio("Navegação:", ["📊 Dashboard", "🤖 Importar Carteira", "📜 Regulamento", "📉 Movimentar Ativos"])

# --- 4. 📊 DASHBOARD ---
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
                
                # PL LÍQUIDO REAL
                total_ativos = df_c['valor_mercado'].sum()
                total_despesas = df_d['valor'].sum() if not df_d.empty else 0
                pl_liquido = total_ativos + total_despesas
                
                col1, col2, col3 = st.columns(3)
                col1.metric("Total Ativos", format_br(total_ativos))
                col2.metric("Total Despesas", format_br(total_despesas))
                col3.metric(f"PL Líquido ({data_selecionada})", format_br(pl_liquido))
                
                st.write("### ✅ Enquadramento do Regulamento")
                for regra in reg.get('regras_json', []):
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

                st.write("### 📄 Carteira: Posição Atual")
                df_view = df_c[['ativo', 'valor_mercado', 'tipo_ativo', 'gaveta_matematica']].copy()
                df_view['% PL'] = (df_view['valor_mercado'] / pl_liquido * 100).apply(lambda x: f"{x:.2f}%")
                df_view['valor_mercado'] = df_view['valor_mercado'].apply(format_br)
                df_view = df_view[['ativo', 'valor_mercado', '% PL', 'tipo_ativo', 'gaveta_matematica']]
                st.dataframe(df_view, use_container_width=True)
                
                if not df_d.empty:
                    st.write("### 💸 Despesas")
                    df_d_view = df_d[['item', 'valor']].copy()
                    df_d_view['% PL'] = (df_d_view['valor'] / pl_liquido * 100).apply(lambda x: f"{x:.4f}%")
                    df_d_view['valor'] = df_d_view['valor'].apply(format_br)
                    st.dataframe(df_d_view, use_container_width=True)
        else:
            st.warning("Importe a carteira para este fundo na data selecionada.")

# --- 5. 🤖 IMPORTAR CARTEIRA ---
elif menu == "🤖 Importar Carteira":
    st.subheader("📥 Carga de Dados e Classificação")
    
    if not lista_regulamentos:
        st.error("⚠️ Cadastre um Regulamento primeiro para poder vincular a carteira.")
    else:
        fundo_vinculo = st.selectbox("🔗 A qual fundo esta carteira pertence?", lista_regulamentos)
        upload_c = st.file_uploader("Excel da Carteira", type=['xlsx'])
        
        if upload_c and st.button("🚀 Extrair e Classificar Ativos"):
            data_arq = extrair_data_arquivo(upload_c.name)
            
            with st.spinner("Analisando ativos e vinculando às gavetas matemáticas..."):
                r_vinculo = conn.table("regulamentos").select("categorias_definidas").eq("fundo_nome", fundo_vinculo).execute()
                chaves_permitidas = []
                if r_vinculo.data and r_vinculo.data[0].get('categorias_definidas'):
                    chaves_permitidas = list(r_vinculo.data[0]['categorias_definidas'].keys())
                else:
                    chaves_permitidas = ["Renda Fixa", "Ações", "FIDC", "Debêntures"]

                df = pd.read_excel(upload_c)
                contexto = df.dropna(how='all').head(300).to_string()
                
                prompt_c = f"""
                Você é um Analista de Mercado. Leia a carteira.
                TAREFA 1 (tipo_ativo): Diga a NATUREZA REAL do ativo (Ex: 'Fundo de Debêntures', 'LFT').
                TAREFA 2 (gaveta_matematica): Escolha ESTRITAMENTE UMA destas chaves: {chaves_permitidas}. Se não couber em nenhuma, use 'Outros'.
                
                JSON: {{
                  'resumo': {{'pl': 0.0, 'cota': 0.0}}, 
                  'ativos': [{{'ativo': 'NOME', 'valor_mercado': 0.0, 'tipo_ativo': 'NATUREZA_REAL', 'gaveta_matematica': 'CHAVE_EXATA'}}], 
                  'despesas': [{{'item': 'NOME', 'valor': 0.0}}]
                }}
                DADOS: {contexto}
                """
                res, motor = chamar_ia_hydra(prompt_c)
                data = json.loads(res.text[res.text.find('{'):res.text.rfind('}')+1])
                
                for d in data.get('despesas', []): d['valor'] = -abs(float(d['valor']))
                st.session_state['temp_c'] = {'data': data, 'data_arq': data_arq, 'fundo': fundo_vinculo}
                
                st.success("Análise Concluída!")
                st.dataframe(pd.DataFrame(data['ativos']))

        if 'temp_c' in st.session_state and st.button("💾 Gravar Posição no Banco"):
            tc = st.session_state['temp_c']
            fn, dt, d = tc['fundo'], tc['data_arq'], tc['data']
            
            for a in d.get('ativos', []): 
                a['fundo_nome'] = fn; a['data'] = dt
            for ds in d.get('despesas', []): 
                ds['fundo_nome'] = fn; ds['data'] = dt
            
            if d.get('ativos'): conn.table("carteira_diaria").insert(d['ativos']).execute()
            if d.get('despesas'): conn.table("despesas_diarias").insert(d['despesas']).execute()
            
            st.success(f"Posição de {fn} gravada com sucesso!")
            del st.session_state['temp_c']
            st.rerun()

# --- 6. 📉 MOVIMENTAR ATIVOS (A MESA DE OPERAÇÕES) ---
elif menu == "📉 Movimentar Ativos":
    st.subheader(f"📉 Mesa de Operações: {fundo_ativo}")
    if fundo_ativo != "Nenhum":
        res_datas = conn.table("carteira_diaria").select("data").eq("fundo_nome", fundo_ativo).execute()
        if res_datas.data:
            datas_disp = sorted(list(set([d['data'] for d in res_datas.data])), reverse=True)
            data_sel = st.selectbox("📅 Selecione a Data da Posição para Operar:", datas_disp)
            
            # Puxa os ativos exatos daquela data (Trazemos o 'id' para poder dar UPDATE no banco)
            c_ativos = conn.table("carteira_diaria").select("id, ativo, valor_mercado, tipo_ativo").eq("fundo_nome", fundo_ativo).eq("data", data_sel).execute()
            
            if c_ativos.data:
                df_ativos = pd.DataFrame(c_ativos.data)
                
                st.write("### Posição Atual")
                st.dataframe(df_ativos[['ativo', 'valor_mercado', 'tipo_ativo']].assign(valor_mercado=lambda x: x['valor_mercado'].apply(format_br)), use_container_width=True)

                st.divider()
                st.write("### 🔀 Lançar Nova Boleta")
                
                with st.form("form_boleta"):
                    col_t, col_a, col_v = st.columns([1, 2, 1])
                    
                    tipo_mov = col_t.selectbox("Operação", ["Compra", "Venda"])
                    # O operador seleciona o ativo que já existe na carteira
                    ativo_mov = col_a.selectbox("Ativo Alvo", df_ativos['ativo'].tolist())
                    valor_mov = col_v.number_input("Valor Financeiro (R$)", min_value=0.01, step=1000.0)
                    
                    submitted = st.form_submit_button("💾 Executar Operação e Atualizar Carteira")
                    
                    if submitted:
                        # 1. Salva o Histórico da Boleta
                        payload_mov = {
                            "fundo_nome": fundo_ativo,
                            "data": data_sel,
                            "tipo": tipo_mov,
                            "ativo": ativo_mov,
                            "valor": valor_mov
                        }
                        conn.table("movimentacoes_ativo").insert(payload_mov).execute()
                        
                        # 2. Atualiza o saldo do ativo na Carteira Diária
                        linha_ativo = df_ativos[df_ativos['ativo'] == ativo_mov].iloc[0]
                        id_carteira = linha_ativo['id']
                        valor_atual = float(linha_ativo['valor_mercado'])
                        
                        novo_valor = valor_atual + valor_mov if tipo_mov == "Compra" else valor_atual - valor_mov
                        
                        # Roda o Update usando o ID exclusivo daquela linha
                        conn.table("carteira_diaria").update({"valor_mercado": novo_valor}).eq("id", id_carteira).execute()
                        
                        st.success(f"BOLETA EXECUTADA: {tipo_mov} de {format_br(valor_mov)} em '{ativo_mov}'.")
                        st.info(f"O saldo do ativo foi atualizado para {format_br(novo_valor)}. Vá ao Dashboard para conferir o novo Enquadramento.")
                        st.rerun()
            else:
                st.warning("Carteira vazia nesta data.")
        else:
            st.warning("Importe a carteira primeiro.")
    else:
        st.info("Selecione um fundo na barra lateral.")

# --- 7. 📜 REGULAMENTO ---
elif menu == "📜 Regulamento":
    st.subheader("📜 Arquiteto de Regras")
    upload_reg = st.file_uploader("Suba o PDF do Regulamento", type=['pdf'])
    
    if upload_reg and st.button("🚀 Mapear Fundo"):
        with st.spinner("Fatiando texto em regras matemáticas..."):
            reader = PdfReader(upload_reg)
            texto = "".join([p.extract_text() for p in reader.pages[:40]])
            
            prompt_reg = f"""
            Analista de Risco: Transforme o regulamento em JSON rigoroso.
            Crie gavetas curtas em 'categorias_definidas'.
            JSON: {{ "fundo": "NOME", "cnpj": "CNPJ", "mandato": "Mandato", "regras": [{{ "id": "regra_x", "tipo": "minimo_percentual", "limite_min": 0.85, "categorias": ["chave_1"] }}], "categorias_definidas": {{ "chave_1": "Desc" }} }}
            TEXTO: {texto[:25000]}
            """
            res, motor = chamar_ia_hydra(prompt_reg)
            data = json.loads(res.text[res.text.find('{'):res.text.rfind('}')+1])
            st.session_state['schema_reg'] = data
            st.json(data)

    if 'schema_reg' in st.session_state and st.button("💾 Salvar Cérebro"):
        d = st.session_state['schema_reg']
        payload = {
            "fundo_nome": d.get('fundo', 'Sem Nome'),
            "cnpj": d.get('cnpj', ''),
            "descricao_mandato": d.get('mandato', ''),
            "regras_json": d.get('regras', []),
            "categorias_definidas": d.get('categorias_definidas', {})
        }
        conn.table("regulamentos").upsert(payload, on_conflict="fundo_nome").execute()
        st.success("Regulamento ativado!")
        del st.session_state['schema_reg']
        st.rerun()
