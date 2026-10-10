import streamlit as st
import pandas as pd
import plotly.express as px
import numpy as np
import io

# Configuração da página
st.set_page_config(
    page_title="Data Clean & Analytics App",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.title("📊 Aplicação Web de Tratamento e Análise de Dados")
st.markdown("Faça upload do seu arquivo **CSV ou Excel**, aplique regras de limpeza, crie filtros avançados e gere gráficos interativos em tempo real.")

# ---------------------------------------------------------
# FUNÇÃO DE CARREGAMENTO DE DADOS DE EXEMPLO
# ---------------------------------------------------------
@st.cache_data
def load_sample_data():
    np.random.seed(42)
    datas = pd.date_range(start="2025-01-01", periods=100, freq="D")
    categorias = np.random.choice(["Eletrônicos", "Roupas", "Alimentos", "Livros"], size=100)
    regioes = np.random.choice(["Norte", "Sul", "Leste", "Oeste", "Centro"], size=100)
    vendas = np.random.uniform(50.0, 1500.0, size=100).round(2)
    quantidades = np.random.randint(1, 20, size=100)
    
    # Inserir alguns valores nulos de propósito para demonstrar limpeza
    vendas[np.random.choice(100, 5, replace=False)] = np.nan
    categorias[np.random.choice(100, 3, replace=False)] = None

    df = pd.DataFrame({
        "Data": datas,
        "Categoria": categorias,
        "Região": regioes,
        "Vendas (R$)": vendas,
        "Quantidade": quantidades
    })
    return df

# ---------------------------------------------------------
# SIDEBAR - UPLOAD E CONFIGURAÇÕES
# ---------------------------------------------------------
st.sidebar.header("📁 Carga de Dados")
uploaded_file = st.sidebar.file_uploader("Selecione um arquivo CSV ou Excel", type=["csv", "xlsx", "xls"])

if uploaded_file is not None:
    try:
        if uploaded_file.name.endswith(".csv"):
            # Permite escolher separador para CSVs
            sep = st.sidebar.text_input("Separador do CSV", value=",")
            df_raw = pd.read_csv(uploaded_file, sep=sep)
        else:
            df_raw = pd.read_excel(uploaded_file)
        st.sidebar.success(f"Arquivo '{uploaded_file.name}' carregado com sucesso!")
    except Exception as e:
        st.sidebar.error(f"Erro ao ler arquivo: {e}")
        df_raw = load_sample_data()
else:
    st.sidebar.info("Utilizando **Conjunto de Dados de Exemplo**.")
    df_raw = load_sample_data()

# Trabalhar em uma cópia do DataFrame
df = df_raw.copy()

# ---------------------------------------------------------
# PAINEL 1: LIMPEZA E NORMALIZAÇÃO DE DADOS
# ---------------------------------------------------------
st.sidebar.markdown("---")
st.sidebar.header("🧹 Limpeza e Normalização")

# 1. Remover Linhas/Colunas totalmente nulas
if st.sidebar.checkbox("Remover linhas 100% vazias", value=True):
    df = df.dropna(how="all")

if st.sidebar.checkbox("Remover colunas 100% vazias", value=True):
    df = df.dropna(how="all", axis=1)

# 2. Tratamento de Valores Nulos (NaN)
null_count = df.isnull().sum().sum()
if null_count > 0:
    st.sidebar.warning(f"Total de campos nulos encontrados: {null_count}")
    clean_action = st.sidebar.selectbox(
        "Ação para valores nulos:",
        ["Manter", "Remover linhas com nulos", "Preencher numéricos com a Média", "Preencher numéricos com Zero", "Preencher com 'N/A'"]
    )
    
    if clean_action == "Remover linhas com nulos":
        df = df.dropna()
    elif clean_action == "Preencher numéricos com a Média":
        num_cols = df.select_dtypes(include=[np.number]).columns
        df[num_cols] = df[num_cols].fillna(df[num_cols].mean())
        df = df.fillna("N/A")
    elif clean_action == "Preencher numéricos com Zero":
        num_cols = df.select_dtypes(include=[np.number]).columns
        df[num_cols] = df[num_cols].fillna(0)
        df = df.fillna("N/A")
    elif clean_action == "Preencher com 'N/A'":
        df = df.fillna("N/A")

# 3. Tratamento de Texto
text_cols = df.select_dtypes(include=["object"]).columns.tolist()
if text_cols:
    trim_spaces = st.sidebar.checkbox("Remover espaços extras no texto (Trim)", value=True)
    if trim_spaces:
        for c in text_cols:
            df[c] = df[c].astype(str).str.strip()

    text_transform = st.sidebar.selectbox("Padronizar formato de texto:", ["Nenhum", "MAIÚSCULAS", "minúsculas", "Primeira Letra Maiúscula"])
    if text_transform == "MAIÚSCULAS":
        for c in text_cols:
            df[c] = df[c].astype(str).str.upper()
    elif text_transform == "minúsculas":
        for c in text_cols:
            df[c] = df[c].astype(str).str.lower()
    elif text_transform == "Primeira Letra Maiúscula":
        for c in text_cols:
            df[c] = df[c].astype(str).str.title()

# ---------------------------------------------------------
# PAINEL 2: FILTROS DINÂMICOS E COMPLEXOS
# ---------------------------------------------------------
st.markdown("---")
st.subheader("🔍 Filtros Personalizados")

expander_filtros = st.expander("Clique para expandir/ocultar os filtros avançados", expanded=True)

with expander_filtros:
    col1, col2 = st.columns(2)
    cols_disponiveis = df.columns.tolist()
    
    # Filtro Categorias/Texto
    with col1:
        st.markdown("**Filtro Multisseleção (Texto / Categorias)**")
        col_cat = st.selectbox("Selecione a coluna para filtrar:", ["Nenhuma"] + cols_disponiveis, key="filter_cat_col")
        if col_cat != "Nenhuma":
            valores_unicos = df[col_cat].dropna().unique().tolist()
            valores_selecionados = st.multiselect(f"Valores permitidos em '{col_cat}':", valores_unicos, default=valores_unicos)
            if valores_selecionados:
                df = df[df[col_cat].isin(valores_selecionados)]

    # Filtro Numérico por Intervalo
    with col2:
        st.markdown("**Filtro Numérico (Mínimo e Máximo)**")
        num_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        if num_cols:
            col_num = st.selectbox("Selecione uma coluna numérica:", ["Nenhuma"] + num_cols, key="filter_num_col")
            if col_num != "Nenhuma":
                min_val = float(df[col_num].min())
                max_val = float(df[col_num].max())
                intervalo = st.slider(
                    f"Intervalo de '{col_num}':",
                    min_value=min_val,
                    max_value=max_val,
                    value=(min_val, max_val)
                )
                df = df[(df[col_num] >= intervalo[0]) & (df[col_num] <= intervalo[1])]

# ---------------------------------------------------------
# PAINEL 3: MÉTRICAS CHAVE & VISUALIZAÇÃO DE DADOS
# ---------------------------------------------------------
st.markdown("---")
st.subheader("📋 Resumo do Dataframe Filtrado")

# Métricas rápidas
m1, m2, m3, m4 = st.columns(4)
m1.metric("Linhas Originais", len(df_raw))
m2.metric("Linhas Atuais", len(df))
m3.metric("Total de Colunas", len(df.columns))

num_cols_atual = df.select_dtypes(include=[np.number]).columns
if len(num_cols_atual) > 0:
    m4.metric("Soma da 1ª Col. Numérica", f"{df[num_cols_atual[0]].sum():,.2f}")
else:
    m4.metric("Colunas Numéricas", 0)

# Pré-visualização da Tabela de Dados
st.dataframe(df, use_container_width=True)

# ---------------------------------------------------------
# PAINEL 4: VISUALIZAÇÃO ESTATÍSTICA E GRÁFICOS
# ---------------------------------------------------------
st.markdown("---")
st.subheader("📈 Análise Estatística e Gráficos Interativos")

if len(df) > 0:
    tab1, tab2 = st.tabs(["📊 Gráficos Interativos", "🔢 Estatística Descritiva"])

    with tab1:
        g1, g2, g3, g4 = st.columns([2, 2, 2, 2])
        with g1:
            tipo_grafico = st.selectbox("Tipo de Gráfico", ["Barras", "Linhas", "Dispersão (Scatter)", "Pizza (Pie)"])
        with g2:
            eixo_x = st.selectbox("Eixo X (Categoria/Data)", df.columns, index=0)
        with g3:
            eixo_y = st.selectbox("Eixo Y (Valor Numérico)", num_cols_atual if len(num_cols_atual) > 0 else df.columns, index=0)
        with g4:
            agregacao = st.selectbox("Função de Agregação", ["Soma", "Média", "Contagem", "Mínimo", "Máximo"])

        # Mapeamento da agregação
        agg_dict = {
            "Soma": "sum",
            "Média": "mean",
            "Contagem": "count",
            "Mínimo": "min",
            "Máximo": "max"
        }

        # Preparar dados agregados para o gráfico
        if tipo_grafico != "Dispersão (Scatter)":
            df_chart = df.groupby(eixo_x, as_index=False)[eixo_y].agg(agg_dict[agregacao])
        else:
            df_chart = df

        # Plotar gráfico
        if tipo_grafico == "Barras":
            fig = px.bar(df_chart, x=eixo_x, y=eixo_y, title=f"{agregacao} de {eixo_y} por {eixo_x}", text_auto='.2s')
        elif tipo_grafico == "Linhas":
            fig = px.line(df_chart, x=eixo_x, y=eixo_y, title=f"{agregacao} de {eixo_y} por {eixo_x}", markers=True)
        elif tipo_grafico == "Dispersão (Scatter)":
            fig = px.scatter(df_chart, x=eixo_x, y=eixo_y, title=f"Dispersão de {eixo_y} x {eixo_x}")
        elif tipo_grafico == "Pizza (Pie)":
            fig = px.pie(df_chart, names=eixo_x, values=eixo_y, title=f"Proporção de {eixo_y} por {eixo_x}")

        fig.update_layout(template="plotly_white", margin=dict(l=20, r=20, t=50, b=20))
        st.plotly_chart(fig, use_container_width=True)

    with tab2:
        st.markdown("**Resumo Estatístico das Variáveis Numéricas:**")
        if len(num_cols_atual) > 0:
            st.dataframe(df.describe().T.style.highlight_max(axis=0, color="#d1e7dd"), use_container_width=True)
        else:
            st.info("Nenhuma coluna numérica disponível para gerar estatísticas.")

else:
    st.warning("Nenhum dado para exibir com os filtros selecionados.")

# ---------------------------------------------------------
# PAINEL 5: EXPORTAÇÃO DOS DADOS LIMPOS
# ---------------------------------------------------------
st.markdown("---")
st.subheader("💾 Exportar Dados Trata dos")

def convert_df_to_csv(data_frame):
    return data_frame.to_csv(index=False).encode('utf-8')

csv_data = convert_df_to_csv(df)

col_exp1, col_exp2 = st.columns([2, 8])
with col_exp1:
    st.download_button(
        label="📥 Baixar em CSV",
        data=csv_data,
        file_name="dados_tratados.csv",
        mime="text/csv"
    )