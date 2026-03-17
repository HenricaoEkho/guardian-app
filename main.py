import streamlit as st
import pandas as pd
from st_supabase_connection import SupabaseConnection
import google.generativeai as genai
import json

# --- 1. CONFIGURAÇÃO E ESTILO ---
st.set_page_config(page_title="Guardian Pro v9", layout="wide", page_icon="🛡️")

def format_br(valor, prefixo="R$ "):
    try:
        val = float(valor)
        return f"{prefixo}{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except: return str(valor)

# --- 2. CONEXÃO IA HÍBRIDA (HYDRA) ---
gemini_key = st.secrets.get("GEMINI_API_KEY")
if gemini_key:
    genai.configure(api_key=gemini_key)

MODELOS_PRIORIDADE = [
    'models/gemini-3.1-flash-lite-preview',
    'models/gemini-2.5-flash-lite',
    'models/gemini-3-flash-preview',
    'models/gemini-1.5-flash'
]

def extrair_com_protocolo_hydra(prompt):
    for model_name in MODELOS_PRIORIDADE:
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt)
            return response, model_name
        except: continue
    raise Exception("Todos os modelos de IA falharam ou estão sem cota.")

conn = st.connection("supabase", type=SupabaseConnection)

# --- 3. SIDEBAR E NAVEGAÇÃO ---
st.sidebar.title("🛡️ Guardian Hydra v9")

# Busca fundos existentes no banco para o filtro global
try:
    res_f = conn.table("carteira_diaria").select("fundo_nome").execute()
    lista_fundos = sorted(list(set([i['fundo_nome'] for i in res_f.data]))) if res_f.data else []
except: lista_fundos = []

fundo_ativo = st.sidebar.selectbox("Fundo Ativo:", lista_fundos if lista_fundos else ["Nenhum cadastrado"])
menu = st.sidebar.radio("Navegação", ["📊 Dashboard", "🤖 Importar Carteira", "📜 Regulamento", "📉 Gestão de Passivo"])

# --- 4. ABA DASHBOARD (VISÃO DE GESTOR) ---
if menu == "📊 Dashboard":
    st.subheader(f"📊 Painel de Enquadramento: {fundo_ativo}")
    
    if fundo_ativo != "Nenhum cadastrado":
        # Busca Dados
        c = conn.table("carteira_diaria").select("*").eq("fundo_nome", fundo_ativo).execute()
        r = conn.table("regulamentos").select("*").eq("fundo_nome", fundo_ativo).execute()
        
        if c.data:
            df_c = pd.DataFrame(c.data)
            pl_total = df_c['valor_mercado'].sum()
            
            # Regras do banco ou padrão 85%
            meta_inc = r.data[0]['meta_incentivadas'] if r.data else 85.0
            
            # Cálculo de Incentivadas (Filtro por tipo)
            v_inc = df_c[df_c['tipo_ativo'].str.contains('Incentivada', case=False, na=False)]['valor_mercado'].sum()
            perc_inc = (v_inc / pl_total) * 100 if pl_total > 0 else 0
            
            # Métricas Principais
            col1, col2, col3 = st.columns(3)
            col1.metric("Patrimônio Líquido", format_br(pl_total))
            
            status_cor = "normal" if perc_inc >= meta_inc else "inverse"
            col2.metric(f"% Incentivadas (Meta {meta_inc}%)", f"{perc_inc:.2f}%", 
                        delta=f"{perc_inc - meta_inc:.2f}% vs Meta", delta_color=status_cor)
            
            col3.metric("Ativos em Carteira", len(df_c))

            st.divider()
            
            # Gráfico de Alocação
            st.write("### Alocação por Classe de Ativo")
            df_pizza = df_c.groupby('tipo_ativo')['valor_mercado'].sum().reset_index()
            st.bar_chart(df_pizza.set_index('tipo_ativo'))

            with st.expander("🔎 Ver Composição Detalhada"):
                st.table(df_c[['ativo', 'tipo_ativo', 'valor_mercado']].assign(
                    valor_mercado=lambda x: x['valor_mercado'].apply(format_br)
                ))
        else:
            st.warning("Sem dados de carteira. Importe um arquivo primeiro.")
    else:
        st.info("O Dashboard aparecerá após a primeira importação.")

# --- 5. ABA REGULAMENTO (CADASTRO DE TRAVAS) ---
elif menu == "📜 Regulamento":
    st.subheader(f"📜 Configuração de Regras: {fundo_ativo}")
    
    if fundo_ativo != "Nenhum cadastrado":
        res_r = conn.table("regulamentos").select("*").eq("fundo_nome", fundo_ativo).execute()
        reg_atual = res_r.data[0] if res_r.data else None
        
        with st.form("form_regulamento"):
            st.write("Defina os limites contratuais do fundo:")
            meta = st.number_input("Mínimo de Debêntures Incentivadas (%)", value=reg_atual['meta_incentivadas'] if reg_atual else 85.0)
            emissor = st.number_input("Limite Máximo por Emissor (%)", value=reg_atual['limite_emissor'] if reg_atual else 20.0)
            
            if st.form_submit_button("💾 Salvar Regulamento"):
                payload = {"fundo_nome": fundo_ativo, "meta_incentivadas": meta, "limite_emissor": emissor}
                conn.table("regulamentos").upsert(payload, on_conflict="fundo_nome").execute()
                st.success("Regras atualizadas com sucesso!")
    else:
        st.info("Importe uma carteira para que o fundo apareça aqui.")

# --- 6. ABA IMPORTAR (MANTENDO O HYDRA) ---
elif menu == "🤖 Importar Carteira":
    st.subheader("🤖 Analista IA Hydra")
    uploaded_file = st.file_uploader("Suba o Excel ou PDF", type=['xlsx', 'pdf'])

    if uploaded_file:
        if st.button("🚀 Iniciar Processamento"):
            with st.spinner("IA processando carteira e despesas..."):
                try:
                    df = pd.read_excel(uploaded_file) if uploaded_file.name.endswith('.xlsx') else pd.read_csv(uploaded_file)
                    contexto = df.dropna(how='all').head(300).to_string()
                    
                    prompt = f"""
                    Analise os dados financeiros e extraia para JSON:
                    1. NOME_FUNDO, PL, COTA.
                    2. ATIVOS: [{{ativo, valor_mercado, tipo_ativo}}]. 
                       Diferencie 'Debênture Incentivada' se houver.
                    3. DESPESAS: [{{item, valor}}].
                    DADOS: {contexto}
                    """
                    
                    response, motor = extrair_com_protocolo_hydra(prompt)
                    data = json.loads(response.text[response.text.find('{'):response.text.rfind('}')+1])
                    
                    # Força despesas negativas
                    for d in data['despesas']: d['valor'] = -abs(float(d['valor']))
                    
                    st.session_state['temp_data'] = data
                    st.success(f"🔥 Sucesso via: {motor}")
                    st.write(f"📌 Fundo: **{data['nome_fundo']}**")
                    
                    c1, c2 = st.columns(2)
                    c1.metric("PL", format_br(data['resumo']['pl']))
                    c2.metric("Cota", f"R$ {data['resumo']['cota']:.6f}")
                    st.table(pd.DataFrame(data['ativos']).assign(valor_mercado=lambda x: x['valor_mercado'].apply(format_br)))

                except Exception as e:
                    st.error(f"Erro: {e}")

    if 'temp_data' in st.session_state:
        if st.button("💾 Confirmar e Gravar no Banco"):
            data = st.session_state['temp_data']
            fundo = data['nome_fundo']
            for a in data['ativos']: a['fundo_nome'] = fundo
            for d in data['despesas']: d['fundo_nome'] = fundo
            
            conn.table("carteira_diaria").insert(data['ativos']).execute()
            conn.table("despesas_diarias").insert(data['despesas']).execute()
            st.success(f"Fundo {fundo} integrado!")
            st.balloons()
            del st.session_state['temp_data']
            st.rerun() # Atualiza a lista de fundos no sidebar

# --- 7. ABA PASSIVO (ESTRUTURA INICIAL) ---
elif menu == "📉 Gestão de Passivo":
    st.subheader(f"📉 Movimentações de Cotistas: {fundo_ativo}")
    st.info("Em breve: Registro de resgates para simulação de PL projetado.")
