import streamlit as st
import pandas as pd
import yfinance as yf
from decimal import Decimal

# Configuração da página
st.set_page_config(
    page_title="Rebalanceamento de Carteira",
    page_icon="💰",
    layout="wide"
)

# Título do app
st.title("💰 Assistente de Rebalanceamento de Carteira")
st.markdown("---")

# ============================================================================
# DADOS FIXADOS - ESTRUTURA DO PORTFÓLIO
# ============================================================================
# Aqui estão os ativos e objetivos fixados. Sua namorada só vai editar
# as quantidades, o CDI e quanto quer aportar.

PORTFOLIO_CONFIG = {
    "SPXR11.SA": {"objetivo": 0.10, "nome": "Fundo Imobiliário S&P 500"},
    "NASD11.SA": {"objetivo": 0.15, "nome": "Fundo Imobiliário NASDAQ"},
    "DIVO11.SA": {"objetivo": 0.15, "nome": "Fundo Imobiliário Dividendos"},
    "B5P211.SA": {"objetivo": 0.20, "nome": "Fundo Imobiliário Brasil"},
    "JURO11.SA": {"objetivo": 0.15, "nome": "Fundo Imobiliário Juros"},
    "RENDA_FIXA_CDI": {"objetivo": 0.25, "nome": "Renda Fixa CDI"}
}

# ============================================================================
# FUNÇÕES
# ============================================================================

def buscar_cotacoes(ativos):
    """Busca as cotações mais recentes para uma lista de ativos."""
    ativos_renda_fixa = ['RENDA_FIXA_CDI']
    tickers_yf = [ativo for ativo in ativos if ativo not in ativos_renda_fixa]
    cotacoes_finais = pd.Series(dtype=float)

    for ativo_rf in ativos_renda_fixa:
        if ativo_rf in ativos:
            cotacoes_finais[ativo_rf] = 1.00

    if tickers_yf:
        try:
            tickers_str = " ".join(tickers_yf)
            dados = yf.download(tickers_str, period='2d', progress=False)

            if not dados.empty:
                cotacoes_yf = dados['Close'].iloc[-1]
                cotacoes_finais = pd.concat([cotacoes_finais, cotacoes_yf.dropna()])

        except Exception as e:
            st.error(f"Erro ao buscar cotações: {e}")

    return cotacoes_finais


def alocar_sobra_iterativamente(sobra_inicial, portfolio_df, recomendacoes_df):
    """Aloca a sobra do aporte de forma iterativa."""
    sobra_atual = sobra_inicial
    estado_loop = pd.merge(portfolio_df, recomendacoes_df, on='ativo', how='left')
    estado_loop['qtd_comprada'] = estado_loop['qtd_comprada'].fillna(0)

    while True:
        estado_loop['nova_quantidade_loop'] = estado_loop['quantidade'] + estado_loop['qtd_comprada']
        estado_loop['novo_valor_loop'] = estado_loop['nova_quantidade_loop'] * estado_loop['cotacao']
        estado_loop['diferenca_valor_loop'] = estado_loop['valor_ideal'] - estado_loop['novo_valor_loop']

        candidatos = estado_loop[
            (estado_loop['diferenca_valor_loop'] > 0) &
            (estado_loop['ativo'] != 'RENDA_FIXA_CDI') &
            (estado_loop['cotacao'] <= sobra_atual)
        ].copy()

        if candidatos.empty:
            break

        ativo_prioritario = candidatos.loc[candidatos['diferenca_valor_loop'].idxmax()]
        ticker_alvo = ativo_prioritario['ativo']
        cotacao_alvo = ativo_prioritario['cotacao']

        sobra_atual -= cotacao_alvo

        idx_rec = recomendacoes_df.index[recomendacoes_df['ativo'] == ticker_alvo].tolist()
        if idx_rec:
            recomendacoes_df.loc[idx_rec, 'qtd_comprada'] += 1
        else:
            nova_rec = pd.DataFrame([{'ativo': ticker_alvo, 'qtd_comprada': 1}])
            recomendacoes_df = pd.concat([recomendacoes_df, nova_rec], ignore_index=True)

        idx_loop = estado_loop.index[estado_loop['ativo'] == ticker_alvo].tolist()
        estado_loop.loc[idx_loop, 'qtd_comprada'] += 1

    return sobra_atual, recomendacoes_df


def calcular_rebalanceamento(portfolio_df, aporte):
    """Calcula o rebalanceamento e retorna os resultados."""
    portfolio_df['valor_atual'] = portfolio_df['quantidade'] * portfolio_df['cotacao']
    valor_total_atual = portfolio_df['valor_atual'].sum()
    novo_valor_total = valor_total_atual + aporte
    portfolio_df['valor_ideal'] = novo_valor_total * portfolio_df['objetivo']
    portfolio_df['diferenca_valor'] = portfolio_df['valor_ideal'] - portfolio_df['valor_atual']

    ativos_para_aportar = portfolio_df[portfolio_df['diferenca_valor'] > 0].copy()

    if ativos_para_aportar.empty:
        return None, None, None, "Todos os seus ativos já estão na proporção ideal ou acima dela."

    total_necessario = ativos_para_aportar['diferenca_valor'].sum()
    ativos_para_aportar['valor_do_aporte'] = (ativos_para_aportar['diferenca_valor'] / total_necessario) * aporte

    ativos_para_aportar['qtd_a_comprar'] = ativos_para_aportar.apply(
        lambda row: row['valor_do_aporte'] if row['ativo'] == 'RENDA_FIXA_CDI'
        else int(Decimal(str(row['valor_do_aporte'])) / Decimal(str(row['cotacao']))),
        axis=1
    )

    recomendacoes_list = []
    for index, row in ativos_para_aportar.iterrows():
        if row['ativo'] == 'RENDA_FIXA_CDI':
            if row['qtd_a_comprar'] > 0.01:
                recomendacoes_list.append({'ativo': row['ativo'], 'qtd_comprada': row['qtd_a_comprar']})
        elif row['qtd_a_comprar'] > 0:
            recomendacoes_list.append({'ativo': row['ativo'], 'qtd_comprada': row['qtd_a_comprar']})

    recomendacoes_df = pd.DataFrame(recomendacoes_list)

    if recomendacoes_df.empty:
        return None, None, None, "Nenhum ativo necessita de aporte."

    custo_inicial_df = pd.merge(recomendacoes_df, portfolio_df[['ativo', 'cotacao']], on='ativo')
    custo_inicial_df['custo_compra'] = custo_inicial_df.apply(
        lambda row: row['qtd_comprada'] if row['ativo'] == 'RENDA_FIXA_CDI'
        else row['qtd_comprada'] * row['cotacao'],
        axis=1
    )
    total_gasto_inicial = custo_inicial_df['custo_compra'].sum()
    sobra = aporte - total_gasto_inicial

    if sobra > 0 and not recomendacoes_df.empty:
        sobra_final, recomendacoes_df = alocar_sobra_iterativamente(sobra, portfolio_df, recomendacoes_df)
    else:
        sobra_final = sobra

    df_final_recomendacoes = pd.merge(recomendacoes_df, portfolio_df[['ativo', 'cotacao']], on='ativo')

    df_final = portfolio_df.copy()
    df_final = pd.merge(df_final, recomendacoes_df, on='ativo', how='left')
    df_final['qtd_comprada'] = df_final['qtd_comprada'].fillna(0)
    df_final['nova_quantidade'] = df_final['quantidade'] + df_final['qtd_comprada']
    df_final['novo_valor'] = df_final['nova_quantidade'] * df_final['cotacao']
    novo_valor_total_carteira = df_final['novo_valor'].sum()

    if novo_valor_total_carteira > 0:
        df_final['porcentagem_nova'] = df_final['novo_valor'] / novo_valor_total_carteira
    else:
        df_final['porcentagem_nova'] = 0

    return df_final_recomendacoes, df_final, sobra_final, None


# ============================================================================
# INTERFACE PRINCIPAL
# ============================================================================

st.markdown("""
### Bem-vinda ao seu assistente de rebalanceamento! 👋

Aqui você pode:
1. **Informar suas posições atuais** (quantidades de cada ativo)
2. **Digitar o valor a aportar**
3. **Receber recomendações** de exatamente o que comprar

Vamos começar? ⬇️
""")

st.markdown("---")

# ============================================================================
# SEÇÃO 1: ENTRADA DE DADOS
# ============================================================================

st.subheader("📝 Suas Posições Atuais")

col1, col2 = st.columns(2)

# Criar um dicionário para armazenar os inputs
posicoes_atuais = {}

# Criar inputs para cada ativo
ativos_lista = list(PORTFOLIO_CONFIG.keys())

# Primeira coluna
with col1:
    st.markdown("**Fundos Imobiliários:**")
    for ativo in ativos_lista[:5]:  # Primeiros 5 ativos (todos exceto CDI)
        if ativo != "RENDA_FIXA_CDI":
            nome = PORTFOLIO_CONFIG[ativo]["nome"]
            posicoes_atuais[ativo] = st.number_input(
                f"Quantas cotas de {ativo}?",
                min_value=0,
                value=0,
                step=1,
                key=f"input_{ativo}"
            )

# Segunda coluna
with col2:
    st.markdown("**Renda Fixa:**")
    posicoes_atuais["RENDA_FIXA_CDI"] = st.number_input(
        "Quanto você tem investido em CDI? (R$)",
        min_value=0.0,
        value=0.0,
        step=100.0,
        format="%.2f",
        key="input_cdi"
    )

st.markdown("---")

# ============================================================================
# SEÇÃO 2: VALOR DO APORTE
# ============================================================================

st.subheader("💵 Valor a Aportar")

aporte = st.number_input(
    "Quanto você quer aportar? (R$)",
    min_value=0.0,
    value=1000.0,
    step=100.0,
    format="%.2f"
)

st.markdown("---")

# ============================================================================
# SEÇÃO 3: CÁLCULO
# ============================================================================

if st.button("🎯 Calcular Rebalanceamento", type="primary", use_container_width=True):
    if aporte <= 0:
        st.error("Por favor, digite um valor de aporte maior que zero!")
    else:
        with st.spinner("🔄 Buscando cotações atuais... Isso pode levar alguns segundos."):
            # Buscar cotações
            ativos = list(PORTFOLIO_CONFIG.keys())
            cotacoes = buscar_cotacoes(ativos)

            if cotacoes is None or cotacoes.empty:
                st.error("❌ Não foi possível buscar as cotações. Verifique sua conexão.")
            else:
                # Criar DataFrame do portfólio
                portfolio_data = []
                for ativo, config in PORTFOLIO_CONFIG.items():
                    portfolio_data.append({
                        'ativo': ativo,
                        'quantidade': posicoes_atuais.get(ativo, 0),
                        'objetivo': config['objetivo'],
                        'cotacao': cotacoes.get(ativo, 1.0)
                    })

                portfolio_df = pd.DataFrame(portfolio_data)

                # Calcular valores
                portfolio_df['valor_atual'] = portfolio_df['quantidade'] * portfolio_df['cotacao']
                valor_total_atual = portfolio_df['valor_atual'].sum()

                if valor_total_atual <= 0 and aporte <= 0:
                    st.error("Você precisa ter uma posição atual ou aportar um valor!")
                else:
                    # Calcular rebalanceamento
                    df_recomendacoes, df_final, sobra_final, mensagem = calcular_rebalanceamento(
                        portfolio_df.copy(), aporte
                    )

                    if mensagem:
                        st.info(f"ℹ️ {mensagem}")
                    else:
                        # ============================================
                        # RESULTADO 1: POSIÇÃO ATUAL
                        # ============================================
                        st.markdown("---")
                        st.subheader("📊 Sua Posição Atual")

                        col1, col2, col3 = st.columns(3)
                        with col1:
                            st.metric("Valor Total Investido", f"R$ {valor_total_atual:,.2f}")
                        with col2:
                            st.metric("Aporte", f"R$ {aporte:,.2f}")
                        with col3:
                            st.metric("Novo Total", f"R$ {valor_total_atual + aporte:,.2f}")

                        # Tabela de posição atual
                        posicao_display = portfolio_df[['ativo', 'quantidade', 'valor_atual', 'objetivo']].copy()
                        posicao_display['objetivo'] = posicao_display['objetivo'].apply(lambda x: f"{x:.2%}")
                        posicao_display['valor_atual'] = posicao_display['valor_atual'].apply(
                            lambda x: f"R$ {x:,.2f}" if x > 0 else "R$ 0,00"
                        )
                        posicao_display.columns = ['Ativo', 'Quantidade', 'Valor Atual', '% Objetivo']

                        st.dataframe(posicao_display, use_container_width=True, hide_index=True)

                        # ============================================
                        # RESULTADO 2: RECOMENDAÇÕES DE COMPRA
                        # ============================================
                        st.markdown("---")
                        st.subheader("✅ O Que Comprar")

                        total_gasto = 0
                        st.markdown("**Aqui está exatamente o que você deve comprar:**\n")

                        for index, row in df_recomendacoes.iterrows():
                            if row['ativo'] == 'RENDA_FIXA_CDI':
                                custo_compra = row['qtd_comprada']
                                total_gasto += custo_compra
                                st.markdown(
                                    f"**💰 {row['ativo']}**  \n"
                                    f"Aportar: `R$ {custo_compra:,.2f}`"
                                )
                            else:
                                custo_compra = row['qtd_comprada'] * row['cotacao']
                                total_gasto += custo_compra
                                st.markdown(
                                    f"**📈 {row['ativo']}**  \n"
                                    f"Comprar: `{int(row['qtd_comprada'])} cotas`  \n"
                                    f"Preço por cota: `R$ {row['cotacao']:,.2f}`  \n"
                                    f"Total: `R$ {custo_compra:,.2f}`"
                                )
                            st.markdown("")

                        # Resumo financeiro
                        col1, col2, col3 = st.columns(3)
                        with col1:
                            st.metric("Total a Investir", f"R$ {total_gasto:,.2f}", delta=None)
                        with col2:
                            st.metric("Sobra", f"R$ {sobra_final:,.2f}", delta=None)
                        with col3:
                            st.metric("Aporte Total", f"R$ {aporte:,.2f}", delta=None)

                        # ============================================
                        # RESULTADO 3: CARTEIRA PÓS-APORTE
                        # ============================================
                        st.markdown("---")
                        st.subheader("📈 Como Ficará Sua Carteira")

                        tabela_resumo = df_final[['ativo', 'objetivo', 'porcentagem_nova']].copy()
                        tabela_resumo['% Objetivo'] = tabela_resumo['objetivo'].apply(lambda x: f"{x:.2%}")
                        tabela_resumo['% Pós-Aporte'] = tabela_resumo['porcentagem_nova'].apply(lambda x: f"{x:.2%}")
                        tabela_resumo = tabela_resumo[['ativo', '% Objetivo', '% Pós-Aporte']]
                        tabela_resumo.columns = ['Ativo', 'Objetivo', 'Após Aporte']

                        st.dataframe(tabela_resumo, use_container_width=True, hide_index=True)

                        # Mensagem final
                        st.markdown("---")
                        if abs(sobra_final) < 0.01:
                            st.success(
                                "✨ **Perfeito!** Todo o aporte foi alocado! Sua carteira ficará bem distribuída."
                            )
                        else:
                            st.info(
                                f"💡 **Sobra disponível:** R$ {sobra_final:,.2f}  \n"
                                f"Você pode usar essa sobra para:"
                                f"\n- Aportar mais em CDI"
                                f"\n- Aguardar para comprar um ativo mais caro"
                                f"\n- Deixar em caixa para investir depois"
                            )

st.markdown("---")
st.markdown(
    "<div style='text-align: center; color: gray; font-size: 0.9em;'>"
    "💡 Dica: Os valores são atualizados em tempo real. Recarregue a página para as cotações mais recentes."
    "</div>",
    unsafe_allow_html=True
)
