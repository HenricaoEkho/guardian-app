import streamlit as st
import pandas as pd
from st_supabase_connection import SupabaseConnection
import google.generativeai as genai
import json
import re
from datetime import datetime
from pypdf import PdfReader

# --- 1. CONFIGURAÇÃO ---
st.set_page_config(page_title="Guardian Ultra v26", layout="wide", page_icon="🛡️")

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
st.sidebar.title("🛡️ Guardian Ultra v26")
try:
    res_f = conn.table("regulamentos").select("fundo_nome").execute()
    lista_regulamentos = sorted(list(set([i['fundo_nome'] for i in res_f.data]))) if res_f.data else []
except: lista_regulamentos = []

fundo_ativo = st.sidebar.selectbox("Fundo Ativo:", lista_regulamentos if lista_regulamentos else ["Nenhum"])
menu = st.sidebar.radio("Ir para:", ["📊 Dashboard", "🤖 Importar Carteira", "📉 Mesa de Operações", "📜 Regulamento"])

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

                st.write("### 📄 Carteira: Posição Consolidada")
                df_view = df_c[['ativo', 'valor_mercado', 'tipo_ativo', 'gaveta_matematica']].copy()
                df_view['% PL'] = (df_view['valor_mercado'] / pl_liquido * 100).apply(lambda x: f"{x:.2f}%")
                df_view['valor_mercado'] = df_view['valor_mercado'].apply(format_br)
                df_view = df_view[['ativo', 'valor_mercado', '% PL', 'tipo_ativo', 'gaveta_matematica']]
                st.dataframe(df_view, use_container_width=True)
                
                if not df_d.empty:
                    with st.expander("💸 Ver Despesas"):
                        df_d_view = df_d[['item', 'valor']].copy()
                        df_d_view['% PL'] = (df_d_view['valor'] / pl_liquido * 100).apply(lambda x: f"{x:.4f}%")
                        df_d_view['valor'] = df_d_view['valor'].apply(format_br)
                        st.dataframe(df_d_view, use_container_width=True)
        else:
            st.warning("Importe a carteira para este fundo na data selecionada.")

# --- 5. 🤖 IMPORTAR CARTEIRA ---
elif menu == "🤖 Importar Carteira":
    st.subheader("📥 Carga de Dados Inicial")
    if not lista_regulamentos:
        st.error("⚠️ Cadastre um Regulamento primeiro.")
    else:
        fundo_vinculo = st.selectbox("🔗 A qual fundo pertence?", lista_regulamentos)
        upload_c = st.file_uploader("Excel da Carteira", type=['xlsx'])
        
        if upload_c and st.button("🚀 Processar Ativos e Despesas"):
            data_arq = extrair_data_arquivo(upload_c.name)
            with st.spinner("Classificando via IA..."):
                r_vinculo = conn.table("regulamentos").select("categorias_definidas").eq("fundo_nome", fundo_vinculo).execute()
                chaves_permitidas = list(r_vinculo.data[0].get('categorias_definidas', {}).keys()) if (r_vinculo.data and r_vinculo.data[0].get('categorias_definidas')) else ["Renda Fixa", "FIDC", "Ações"]

                df = pd.read_excel(upload_c)
                prompt_c = f"""
                Analista de Mercado. 
                TAREFA 1: Diga a NATUREZA REAL do ativo (Ex: 'Fundo de Debêntures', 'LFT').
                TAREFA 2: Escolha UMA destas chaves: {chaves_permitidas}. Se não couber, use 'Outros'.
                JSON: {{'resumo': {{'pl': 0.0, 'cota': 0.0}}, 'ativos': [{{'ativo': 'NOME', 'valor_mercado': 0.0, 'tipo_ativo': 'NATUREZA', 'gaveta_matematica': 'CHAVE_EXATA'}}], 'despesas': [{{'item': 'NOME', 'valor': 0.0}}]}}
                DADOS: {df.dropna(how='all').head(300).to_string()}
                """
                res, motor = chamar_ia_hydra(prompt_c)
                data = json.loads(res.text[res.text.find('{'):res.text.rfind('}')+1])
                for d in data.get('despesas', []): d['valor'] = -abs(float(d['valor']))
                st.session_state['temp_c'] = {'data': data, 'data_arq': data_arq, 'fundo': fundo_vinculo}
                st.success("Análise concluída!")
                st.dataframe(pd.DataFrame(data['ativos']))

        if 'temp_c' in st.session_state and st.button("💾 Gravar no Banco"):
            tc = st.session_state['temp_c']
            fn, dt, d = tc['fundo'], tc['data_arq'], tc['data']
            for a in d.get('ativos', []): a['fundo_nome'] = fn; a['data'] = dt
            for ds in d.get('despesas', []): ds['fundo_nome'] = fn; ds['data'] = dt
            if d.get('ativos'): conn.table("carteira_diaria").insert(d['ativos']).execute()
            if d.get('despesas'): conn.table("despesas_diarias").insert(d['despesas']).execute()
            st.success("Salvo com sucesso!")
            del st.session_state['temp_c']
            st.rerun()

# --- 6. 📉 MESA DE OPERAÇÕES E DOUBLE CHECK ---
elif menu == "📉 Mesa de Operações":
    st.subheader(f"📉 Mesa de Operações: {fundo_ativo}")
    if fundo_ativo != "Nenhum":
        res_datas = conn.table("carteira_diaria").select("data").eq("fundo_nome", fundo_ativo).execute()
        if res_datas.data:
            datas_disp = sorted(list(set([d['data'] for d in res_datas.data])), reverse=True)
            data_sel = st.selectbox("📅 Data da Posição Alvo:", datas_disp)
            
            c_ativos = conn.table("carteira_diaria").select("*").eq("fundo_nome", fundo_ativo).eq("data", data_sel).execute()
            df_ativos = pd.DataFrame(c_ativos.data) if c_ativos.data else pd.DataFrame()
            
            aba1, aba2 = st.tabs(["🔀 Lançar Boleta (Maker)", "📋 Relatório e Confirmação (Checker)"])
            
            # --- ABA 1: LANÇAR BOLETA ---
            with aba1:
                st.write("Crie uma ordem. Ela ficará **Pendente** até ser confirmada na aba de Relatório.")
                tipo_ativo_boleta = st.radio("O ativo já existe na carteira?", ["Sim (Aumentar/Reduzir Posição)", "Não (Comprar Novo Ativo)"])
                
                with st.form("form_boleta"):
                    col_t, col_a, col_v = st.columns([1, 2, 1])
                    tipo_mov = col_t.selectbox("Operação", ["Compra", "Venda"])
                    valor_mov = col_v.number_input("Valor (R$)", min_value=0.01, step=1000.0)
                    
                    if "Sim" in tipo_ativo_boleta:
                        ativo_mov = col_a.selectbox("Ativo Alvo", df_ativos['ativo'].tolist() if not df_ativos.empty else [])
                        submitted = st.form_submit_button("Lançar Boleta")
                        
                        if submitted:
                            # Busca as tags do ativo existente para replicar na boleta
                            linha_ativo = df_ativos[df_ativos['ativo'] == ativo_mov].iloc[0]
                            payload = {
                                "fundo_nome": fundo_ativo, "data": data_sel, "tipo": tipo_mov, 
                                "ativo": ativo_mov, "valor": valor_mov, 
                                "tipo_ativo_ia": linha_ativo['tipo_ativo'], "gaveta_ia": linha_ativo['gaveta_matematica'],
                                "status": "Pendente"
                            }
                            conn.table("movimentacoes_ativo").insert(payload).execute()
                            st.success("Boleta gerada! Vá na aba de Relatório para confirmar.")
                    else:
                        ativo_mov = col_a.text_input("Nome/Ticker/CNPJ do Novo Ativo")
                        submitted = st.form_submit_button("Lançar Boleta com Pré-Trade IA")
                        
                        if submitted and ativo_mov:
                            with st.spinner("IA classificando o novo ativo nas gavetas do regulamento..."):
                                r_vinculo = conn.table("regulamentos").select("categorias_definidas").eq("fundo_nome", fundo_ativo).execute()
                                chaves = list(r_vinculo.data[0].get('categorias_definidas', {}).keys()) if r_vinculo.data else []
                                
                                prompt_pre = f"""
                                O gestor quer comprar o ativo: '{ativo_mov}'.
                                1. Diga a NATUREZA REAL (Ação, FIDC, Debênture).
                                2. Escolha a CHAVE EXATA para o compliance: {chaves}. Se não couber, use 'Outros'.
                                JSON: {{ "tipo_ativo": "NATUREZA", "gaveta_matematica": "CHAVE" }}
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
                                st.success(f"Boleta gerada! A IA classificou como '{classif['gaveta_matematica']}'. Vá confirmar no Relatório.")

            # --- ABA 2: DOUBLE CHECK (RELATÓRIO E CONFIRMAÇÃO) ---
            with aba2:
                st.write("### 📋 Histórico e Aprovações")
                
                # Exibe todas as movimentações
                hist = conn.table("movimentacoes_ativo").select("*").eq("fundo_nome", fundo_ativo).order("data", desc=True).execute()
                if hist.data:
                    df_hist = pd.DataFrame(hist.data)
                    st.dataframe(df_hist[['data', 'tipo', 'ativo', 'valor', 'status', 'gaveta_ia']], use_container_width=True)
                    
                    # Filtra apenas as Pendentes para ação
                    pendentes = [op for op in hist.data if op['status'] == 'Pendente']
                    
                    if pendentes:
                        st.divider()
                        st.write("#### ⚠️ Operações Aguardando Double Check")
                        op_sel_str = st.selectbox("Selecione a boleta para avaliar:", [f"{op['id']} | {op['tipo']} {op['ativo']} - R$ {op['valor']}" for op in pendentes])
                        op_id = op_sel_str.split(" | ")[0]
                        op_data = next(op for op in pendentes if op['id'] == op_id)
                        
                        col_conf, col_del, col_edit = st.columns(3)
                        
                        if col_conf.button("✅ Confirmar e Atualizar Carteira"):
                            # Lógica de atualização na carteira_diaria
                            ativo_existente = df_ativos[df_ativos['ativo'] == op_data['ativo']]
                            
                            if not ativo_existente.empty:
                                # Atualiza valor do ativo existente
                                id_carteira = ativo_existente.iloc[0]['id']
                                val_atual = float(ativo_existente.iloc[0]['valor_mercado'])
                                novo_val = val_atual + float(op_data['valor']) if op_data['tipo'] == "Compra" else val_atual - float(op_data['valor'])
                                conn.table("carteira_diaria").update({"valor_mercado": novo_val}).eq("id", id_carteira).execute()
                            else:
                                # Insere o NOVO ativo usando a classificação que a IA fez na boleta
                                novo_ativo_payload = {
                                    "data": op_data['data'], "fundo_nome": fundo_ativo,
                                    "ativo": op_data['ativo'], "valor_mercado": float(op_data['valor']),
                                    "tipo_ativo": op_data['tipo_ativo_ia'], "gaveta_matematica": op_data['gaveta_ia']
                                }
                                conn.table("carteira_diaria").insert(novo_ativo_payload).execute()
                            
                            # Muda status para Confirmada
                            conn.table("movimentacoes_ativo").update({"status": "Confirmada"}).eq("id", op_id).execute()
                            st.success("Operação confirmada! O Dashboard foi atualizado.")
                            st.rerun()
                            
                        if col_del.button("❌ Cancelar Boleta"):
                            conn.table("movimentacoes_ativo").update({"status": "Cancelada"}).eq("id", op_id).execute()
                            st.error("Operação cancelada.")
                            st.rerun()
                            
                        with col_edit.expander("✏️ Editar Valor da Ordem"):
                            novo_v = st.number_input("Novo Valor Financeiro", value=float(op_data['valor']))
                            if st.button("Salvar Nova Ordem"):
                                conn.table("movimentacoes_ativo").update({"valor": novo_v}).eq("id", op_id).execute()
                                st.success("Boleta editada!")
                                st.rerun()
                    else:
                        st.success("Tudo limpo! Nenhuma operação pendente.")
                else:
                    st.info("Nenhuma movimentação registrada.")
        else: st.warning("Importe a carteira primeiro.")

# --- 7. 📜 REGULAMENTO ---
elif menu == "📜 Regulamento":
    st.subheader("📜 Arquiteto de Regras")
    upload_reg = st.file_uploader("Suba o PDF do Regulamento", type=['pdf'])
    
    if upload_reg and st.button("🚀 Mapear Fundo"):
        with st.spinner("Gerando Gavetas Matemáticas..."):
            reader = PdfReader(upload_reg)
            texto = "".join([p.extract_text() for p in reader.pages[:40]])
            
            prompt_reg = f"""
            Analista CVM: Transforme o regulamento em JSON rigoroso.
            Crie 'categorias_definidas'.
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
            "fundo_nome": d.get('fundo', 'Sem Nome'), "cnpj": d.get('cnpj', ''), "descricao_mandato": d.get('mandato', ''),
            "regras_json": d.get('regras', []), "categorias_definidas": d.get('categorias_definidas', {})
        }
        conn.table("regulamentos").upsert(payload, on_conflict="fundo_nome").execute()
        st.success("Regulamento ativado!")
        del st.session_state['schema_reg']
        st.rerun()
