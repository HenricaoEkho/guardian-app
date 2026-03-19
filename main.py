import streamlit as st
import pandas as pd
from st_supabase_connection import SupabaseConnection
import google.generativeai as genai
import json
import re
from datetime import datetime
from pypdf import PdfReader

# --- 1. CONFIGURAÇÃO E ESTILO ---
st.set_page_config(page_title="Guardian Ultra v28", layout="wide", page_icon="🛡️")

# CSS customizado para melhorar a interface da Mesa de Operações
st.markdown("""
    <style>
    .boleta-container {
        border: 1px solid #333;
        border-radius: 8px;
        padding: 20px;
        background-color: #1e1e1e;
    }
    .status-pendente { color: #FFA500; font-weight: bold; }
    .status-confirmada { color: #00FF00; font-weight: bold; }
    .status-cancelada { color: #FF0000; font-weight: bold; }
    </style>
""", unsafe_allow_html=True)

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
    raise Exception("Modelos IA indisponíveis no momento.")

conn = st.connection("supabase", type=SupabaseConnection)

# --- 3. SIDEBAR ---
st.sidebar.title("🛡️ Guardian Terminal")
try:
    res_f = conn.table("regulamentos").select("fundo_nome").execute()
    lista_regulamentos = sorted(list(set([i['fundo_nome'] for i in res_f.data]))) if res_f.data else []
except: lista_regulamentos = []

fundo_ativo = st.sidebar.selectbox("Fundo Ativo:", lista_regulamentos if lista_regulamentos else ["Nenhum"])
menu = st.sidebar.radio("Navegação:", ["📊 Dashboard Compliance", "🤖 Importar Carteira", "📉 Mesa de Operações", "📜 Regulamento"])

# --- 4. 📊 DASHBOARD ---
if menu == "📊 Dashboard Compliance":
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
                df_view = df_view[['ativo', 'valor_mercado', '% PL', 'tipo_ativo', 'gaveta_matematica']]
                st.dataframe(df_view, use_container_width=True)
                
                if not df_d.empty:
                    with st.expander("💸 Visualizar Despesas"):
                        df_d_view = df_d[['item', 'valor']].copy()
                        df_d_view['% PL'] = (df_d_view['valor'] / pl_liquido * 100).apply(lambda x: f"{x:.4f}%")
                        df_d_view['valor'] = df_d_view['valor'].apply(format_br)
                        st.dataframe(df_d_view, use_container_width=True)
        else:
            st.warning("Nenhuma carteira importada para este fundo.")

# --- 5. 🤖 IMPORTAR CARTEIRA ---
elif menu == "🤖 Importar Carteira":
    st.subheader("📥 Carga Inicial e Classificação")
    if not lista_regulamentos:
        st.error("⚠️ Cadastre o Regulamento do fundo primeiro.")
    else:
        fundo_vinculo = st.selectbox("🔗 Vincular à carteira do fundo:", lista_regulamentos)
        upload_c = st.file_uploader("Arquivo Excel", type=['xlsx'])
        
        if upload_c and st.button("🚀 Processar Arquivo"):
            data_arq = extrair_data_arquivo(upload_c.name)
            with st.spinner("Motor de IA lendo mercado e regulamento..."):
                r_vinculo = conn.table("regulamentos").select("categorias_definidas").eq("fundo_nome", fundo_vinculo).execute()
                chaves_permitidas = list(r_vinculo.data[0].get('categorias_definidas', {}).keys()) if (r_vinculo.data and r_vinculo.data[0].get('categorias_definidas')) else []

                df = pd.read_excel(upload_c)
                
                # NOVO PROMPT ANTI-ALUCINAÇÃO
                prompt_c = f"""
                Você é um Analista de Dados da ANBIMA e Risco de Compliance.
                Acesse a carteira de investimentos enviada.
                
                PASSO 1: Identifique a natureza REAL de cada ativo com base no seu conhecimento de mercado financeiro. (Ex: SPX HORNET é 'Fundo Multimercado', JGP DEB é 'Fundo de Debêntures', BOVA11 é 'ETF', Tesouro Selic é 'LFT'). Responda em 'tipo_ativo'.
                PASSO 2: O regulamento deste fundo SÓ ACEITA as seguintes chaves de gaveta: {chaves_permitidas}.
                SE o ativo não se enquadrar PERFEITAMENTE na definição técnica da chave, o campo 'gaveta_matematica' OBRIGATORIAMENTE deve ser 'Desenquadrado'. Não force o ativo em uma gaveta incorreta!
                
                JSON DE SAÍDA: {{'resumo': {{'pl': 0.0, 'cota': 0.0}}, 'ativos': [{{'ativo': 'NOME', 'valor_mercado': 0.0, 'tipo_ativo': 'NATUREZA_REAL_ANBIMA', 'gaveta_matematica': 'CHAVE_OU_DESENQUADRADO'}}], 'despesas': [{{'item': 'NOME', 'valor': 0.0}}]}}
                DADOS: {df.dropna(how='all').head(300).to_string()}
                """
                res, motor = chamar_ia_hydra(prompt_c)
                data = json.loads(res.text[res.text.find('{'):res.text.rfind('}')+1])
                for d in data.get('despesas', []): d['valor'] = -abs(float(d['valor']))
                st.session_state['temp_c'] = {'data': data, 'data_arq': data_arq, 'fundo': fundo_vinculo}
                st.success("Análise de Risco Concluída!")
                st.dataframe(pd.DataFrame(data['ativos']))

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

# --- 6. 📉 MESA DE OPERAÇÕES (NOVO DESIGN OMS) ---
elif menu == "📉 Mesa de Operações":
    st.subheader(f"📉 OMS (Order Management System): {fundo_ativo}")
    if fundo_ativo != "Nenhum":
        res_datas = conn.table("carteira_diaria").select("data").eq("fundo_nome", fundo_ativo).execute()
        if res_datas.data:
            datas_disp = sorted(list(set([d['data'] for d in res_datas.data])), reverse=True)
            data_sel = st.selectbox("📅 Refletir operações na carteira do dia:", datas_disp)
            
            c_ativos = conn.table("carteira_diaria").select("*").eq("fundo_nome", fundo_ativo).eq("data", data_sel).execute()
            df_ativos = pd.DataFrame(c_ativos.data) if c_ativos.data else pd.DataFrame()
            
            aba1, aba2 = st.tabs(["🔀 Boleta (Maker)", "📋 Double Check & Relatório (Checker)"])
            
            # --- ABA 1: BOLETA ---
            with aba1:
                st.markdown('<div class="boleta-container">', unsafe_allow_html=True)
                st.markdown("#### 📝 Lançamento de Ordem")
                
                tipo_ativo_boleta = st.radio("Selecione o tipo de ordem:", ["Ativo Existente na Carteira", "Novo Ativo (Requer Pré-Trade IA)"], horizontal=True)
                st.divider()
                
                with st.form("form_boleta_oms"):
                    col_t, col_a, col_v = st.columns([1, 2, 1])
                    tipo_mov = col_t.selectbox("Natureza", ["Compra", "Venda"])
                    valor_mov = col_v.number_input("Volume Financeiro (R$)", min_value=0.01, step=10000.0, format="%.2f")
                    
                    if "Existente" in tipo_ativo_boleta:
                        ativo_mov = col_a.selectbox("Ativo Alvo", df_ativos['ativo'].tolist() if not df_ativos.empty else [])
                        enviar_ordem = st.form_submit_button("Gerar Boleta Pendente")
                        
                        if enviar_ordem:
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
                        ativo_mov = col_a.text_input("Ticker / Nome Institucional do Ativo")
                        enviar_ordem = st.form_submit_button("Analisar Pré-Trade e Gerar Boleta")
                        
                        if enviar_ordem and ativo_mov:
                            with st.spinner("Compliance pré-trade verificando ativo..."):
                                r_vinculo = conn.table("regulamentos").select("categorias_definidas").eq("fundo_nome", fundo_ativo).execute()
                                chaves = list(r_vinculo.data[0].get('categorias_definidas', {}).keys()) if r_vinculo.data else []
                                
                                # PROMPT ANTI-ALUCINAÇÃO PARA O PRÉ-TRADE
                                prompt_pre = f"""
                                Você é um Analista de Risco da ANBIMA. O gestor está comprando: '{ativo_mov}'.
                                PASSO 1: Diga a natureza real de mercado desse ativo. (Ex: 'Fundo Multimercado', 'Debênture', 'Ação').
                                PASSO 2: O regulamento SÓ aceita as gavetas: {chaves}. Se o ativo não for a definição perfeita da gaveta, DEVOLVA 'Desenquadrado'. NÃO FORCE ENCAIXE.
                                JSON: {{ "tipo_ativo": "NATUREZA_MERCADO", "gaveta_matematica": "CHAVE_OU_DESENQUADRADO" }}
                                """
                                res, motor = chamar_ia_hydra(prompt_pre)
                                classif = json.loads(res.text[res.text.find('{'):res.text.rfind('}')+1])
                                
                                payload = {
                                    "fundo_nome": fundo_ativo, "data": data_sel, "tipo": "Compra", 
                                    "ativo": ativo_mov, "valor": valor_mov, 
                                    "tipo_ativo_ia": classif['tipo_ativo'], "gaveta_ia": classif['gaveta_matematica'],
                                    "status": "Pendente"
                                }
                                conn.table("movimentacoes_ativo").insert(payload).execute()
                                st.info(f"Análise: Natureza identificada como '{classif['tipo_ativo']}'. Alocação proposta: '{classif['gaveta_ia']}'.")
                                st.success("Ordem enviada para o Checker.")
                st.markdown('</div>', unsafe_allow_html=True)

            # --- ABA 2: CHECKER E RELATÓRIO ---
            with aba2:
                hist = conn.table("movimentacoes_ativo").select("*").eq("fundo_nome", fundo_ativo).order("data", desc=True).execute()
                if hist.data:
                    df_hist = pd.DataFrame(hist.data)
                    pendentes = [op for op in hist.data if op['status'] == 'Pendente']
                    
                    if pendentes:
                        st.markdown("### ⚠️ Fila de Aprovação (Double Check)")
                        for op in pendentes:
                            with st.container(border=True):
                                st.markdown(f"**Ordem #{op['id'].split('-')[0]}** | {op['tipo']} de **{op['ativo']}**")
                                c_info1, c_info2, c_info3 = st.columns(3)
                                c_info1.write(f"**Volume:** {format_br(op['valor'])}")
                                c_info2.write(f"**Natureza:** {op['tipo_ativo_ia']}")
                                c_info3.write(f"**Gaveta Compliance:** {op['gaveta_ia']}")
                                
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
                    
                    st.divider()
                    st.markdown("### 📋 Trade Blotter (Histórico Geral)")
                    # Visualização limpa do histórico
                    df_view_hist = df_hist[['data', 'tipo', 'ativo', 'valor', 'gaveta_ia', 'status']].copy()
                    df_view_hist['valor'] = df_view_hist['valor'].apply(format_br)
                    st.dataframe(df_view_hist, use_container_width=True)
                else: st.info("O Order Book está vazio para este fundo.")
        else: st.warning("Importe a carteira base primeiro.")

# --- 7. 📜 REGULAMENTO ---
elif menu == "📜 Regulamento":
    st.subheader("📜 Arquiteto de Risco (CVM 175)")
    upload_reg = st.file_uploader("Suba o PDF do Regulamento", type=['pdf'])
    
    if upload_reg and st.button("🚀 Mapear Cérebro de Compliance"):
        with st.spinner("Análise Profunda ativada (Lendo até 60 páginas)..."):
            try:
                reader = PdfReader(upload_reg)
                texto = ""
                for page in reader.pages[:60]: texto += page.extract_text()
                
                # PROMPT SNIPER - NUNCA MAIS MEXEREMOS AQUI
                prompt_reg = f"""
                Você é um Auditor de Risco e Compliance Sênior da CVM. 
                Seu objetivo é transformar o regulamento em um motor matemático JSON rigoroso.

                DIRETRIZES DE EXTRAÇÃO:
                1. FOQUE nas regras de enquadramento PERMANENTES (Política de Investimento e Anexo I).
                2. IGNORE carências iniciais. LEIA COM ATENÇÃO o limite alvo principal.
                3. TIPO: 'Não pode exceder' = maximo_percentual. 'Deve investir no mínimo' = minimo_percentual.
                4. LIMITES: Retorne apenas FLOAT (ex: 67% = 0.67).
                5. CRIE 'categorias_definidas' com chaves curtas e claras (ex: 'cotas_fic_fidc', 'infra_12431').

                ESTRUTURA DE SAÍDA OBRIGATÓRIA (JSON):
                {{
                  "fundo": "NOME COMPLETO",
                  "cnpj": "CNPJ",
                  "mandato": "Mandato Principal",
                  "regras": [
                    {{ "id": "minimo_estrategia", "tipo": "minimo_percentual", "limite_min": 0.67, "categorias": ["chave_1"] }}
                  ],
                  "categorias_definidas": {{ "chave_1": "Descricao legível da categoria" }}
                }}
                TEXTO: {texto[:35000]}
                """
                res, motor = chamar_ia_hydra(prompt_reg)
                data = json.loads(res.text[res.text.find('{'):res.text.rfind('}')+1])
                st.session_state['schema_reg'] = data
                st.json(data)
            except Exception as e: st.error(f"Erro na extração profunda: {e}")

    if 'schema_reg' in st.session_state and st.button("💾 Ativar Compliance no Banco"):
        d = st.session_state['schema_reg']
        payload = {
            "fundo_nome": d.get('fundo', 'Fundo Sem Nome'),
            "cnpj": d.get('cnpj', ''),
            "descricao_mandato": d.get('mandato', ''),
            "regras_json": d.get('regras', []),
            "categorias_definidas": d.get('categorias_definidas', {})
        }
        conn.table("regulamentos").upsert(payload, on_conflict="fundo_nome").execute()
        st.success("Regulamento ativado! O motor matemático está blindado.")
        del st.session_state['schema_reg']
        st.rerun()
