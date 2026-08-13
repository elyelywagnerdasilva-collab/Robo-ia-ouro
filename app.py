print("[LOG] Iniciando carregamento das bibliotecas de IA...")
import yfinance as yf
import pandas as pd
import numpy as np
import json
import time
import os
import requests
from datetime import datetime, timedelta
from sklearn.linear_model import SGDRegressor
from sklearn.preprocessing import StandardScaler

# ================================================================
# CONFIGURAÇÃO DEFINITIVA - SEU WEBHOOK NOVO E VALIDADO
# ================================================================
URL_DISCORD_WEBHOOK = "https://discord.com"

ATIVOS_MONITORADOS = {"GC=F": "OURO", "BTC-USD": "BITCOIN", "EURUSD=X": "EUR/USD"}

# AJUSTE PARA O RENDER: Caminho de escrita permitido em servidores Linux
ARQUIVO_MEMORIA = "/tmp/memoria_ia_evolutiva_multiativos.json"

MODELOS_NEURAIS = {}
ESCALONADORES = {}

LOG_MOTIVOS = {ticker: {"Rede Neural Mandou Aguardar": 0, "Bloqueado por Stop Recente": 0, "Filtro Q-Table Barrou": 0} for ticker in ATIVOS_MONITORADOS}

def enviar_alerta_discord(mensagem):
    print(f"[LOG] Enviando para o Discord: {str(mensagem[:40])}...")
    headers = {"Content-Type": "application/json"}
    payload = json.dumps({"content": str(mensagem)})
    try:
        response = requests.post(URL_DISCORD_WEBHOOK, data=payload, headers=headers, timeout=10)
        print(f"[Resposta Discord]: Status {response.status_code}")
    except Exception as e:
        print(f"[Erro de Conexão Discord]: {e}")

print("[LOG] Configurando banco de memória da IA...")
if os.path.exists(ARQUIVO_MEMORIA):
    try:
        with open(ARQUIVO_MEMORIA, 'r') as f: memoria_ia = json.load(f)
    except:
        memoria_ia = {}
else:
    memoria_ia = {}

for ticker, nome in ATIVOS_MONITORADOS.items():
    if ticker not in memoria_ia:
        memoria_ia[ticker] = {
            "total_profits": 0, "total_stops": 0, "consecutivos_stops": 0,
            "ajuste_stop_base": 0.0020, "ajuste_profit_base": 0.0040,
            "ordem_ativa": None, "horario_bloqueio_ate": None, "q_table": {}
        }
    MODELOS_NEURAIS[ticker] = SGDRegressor(max_iter=2000, tol=1e-4, learning_rate='adaptive', eta0=0.005)
    ESCALONADORES[ticker] = StandardScaler()

def salvar_memoria():
    try:
        with open(ARQUIVO_MEMORIA, 'w') as f: json.dump(memoria_ia, f, indent=4)
    except Exception as e:
        print(f"[Erro Memoria]: {e}")

def analisar_macro_tendencia(ticker):
    try:
        df_1d = yf.download(ticker, period="3mo", interval="1d", progress=False)
        if not df_1d.empty:
            if isinstance(df_1d.columns, pd.MultiIndex): df_1d.columns = df_1d.columns.get_level_values(0)
            ma9_1d = df_1d['Close'].rolling(window=9).mean().iloc[-1]
            ma21_1d = df_1d['Close'].rolling(window=21).mean().iloc[-1]
            return "ALTA" if ma9_1d > ma21_1d else "BAIXA"
    except Exception as e:
        print(f"[Erro Macro {ticker}]: {e}")
    return "NEUTRO"

def obter_dados_preparados(ticker):
    try:
        df = yf.download(ticker, period="5d", interval="2m", progress=False)
        if df.empty: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        df.columns = df.columns.str.strip()
        df.ffill(inplace=True)
        
        df['MA9'] = df['Close'].rolling(window=9).mean()
        df['MA21'] = df['Close'].rolling(window=21).mean()
        df['MA100'] = df['Close'].rolling(window=100).mean()
        
        delta = df['Close'].diff()
        ganho = delta.where(delta > 0, 0).rolling(window=14).mean()
        perda = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        df['RSI'] = 100 - (100 / (1 + (ganho / (perda + 1e-9))))
        df.dropna(inplace=True)
        return df
    except Exception as e:
        print(f"[Erro Preparacao {ticker}]: {e}")
        return None

def treinar_e_prever_rede_neural(df, ticker):
    try:
        features = df[['Close', 'MA9', 'MA21', 'MA100', 'RSI']].values
        alvo = df['Close'].shift(-1).ffill().values
        
        X_scaled = ESCALONADORES[ticker].fit_transform(features)
        MODELOS_NEURAIS[ticker].partial_fit(X_scaled, alvo)
        
        ultima_linha_features = features[-1].reshape(1, -1)
        ultima_linha_scaled = ESCALONADORES[ticker].transform(ultima_linha_features)
        
        previsao_preco = MODELOS_NEURAIS[ticker].predict(ultima_linha_scaled)
        preco_atual = df['Close'].iloc[-1]
        
        macro = analisar_macro_tendencia(ticker)
        
        # FILTROS MENOS RÍGIDOS (0.0003) - Mais entradas no mercado
        if previsao_preco > (preco_atual * 1.0003) and macro == "ALTA": return "COMPRA"
        elif previsao_preco < (preco_atual * 0.9997) and macro == "BAIXA": return "VENDA"
    except Exception as e:
        print(f"[Erro Rede Neural {ticker}]: {e}")
    return "AGUARDAR"

def obter_estado_mercado(df):
    try:
        rsi = float(df['RSI'].iloc[-1])
        tendencia = "ALTA" if df['MA9'].iloc[-1] > df['MA21'].iloc[-1] else "BAIXA"
        volatilidade = "ALTA" if df['Close'].std() > df['Close'].rolling(20).std().iloc[-1] else "BAIXA"
        situacao_rsi = "SOBRECOMPRADO" if rsi > 70 else ("SOBREVENDIDO" if rsi < 30 else "NEUTRO")
        return f"{tendencia}_{situacao_rsi}_{volatilidade}"
    except:
        return "INDETERMINADO"

def processar_ciclo_ia_por_ativo(ticker, nome_amigavel):
    print(f"[LOG] Hércules Neural analisando: {nome_amigavel}...")
    df = obter_dados_preparados(ticker)
    if df is None or len(df) < 100: return
    
    preco_atual, high_atual, low_atual = float(df['Close'].iloc[-1]), float(df['High'].iloc[-1]), float(df['Low'].iloc[-1])
    estado_atual = obter_estado_mercado(df)
    mem_ativo = memoria_ia[ticker]
    
    if mem_ativo["ordem_ativa"] is not None:
        ordem = mem_ativo["ordem_ativa"]
        tipo = ordem.get("tipo", "COMPRA")
        ganhou, perdeu = False, False
        if tipo == "COMPRA":
            if preco_atual >= (ordem["entrada"] + ((ordem["tp"] - ordem["entrada"]) * 0.5)) and ordem["sl"] < ordem["entrada"]:
                ordem["sl"] = ordem["entrada"]; salvar_memoria()
                enviar_alerta_discord(f"DEFESA NEURAL ({nome_amigavel}) - Stop na Entrada: {ordem['sl']:,.4f}")
            if high_atual >= ordem["tp"]: ganhou = True
            elif low_atual <= ordem["sl"]: perdeu = True
        elif tipo == "VENDA":
            if preco_atual <= (ordem["entrada"] - ((ordem["entrada"] - ordem["tp"]) * 0.5)) and ordem["sl"] > ordem["entrada"]:
                ordem["sl"] = ordem["entrada"]; salvar_memoria()
                enviar_alerta_discord(f"DEFESA NEURAL ({nome_amigavel}) - Stop na Entrada: {ordem['sl']:,.4f}")
            if low_atual <= ordem["tp"]: ganhou = True
            elif high_atual >= ordem["sl"]: perdeu = True
            
        if ganhou:
            mem_ativo["total_profits"] += 1; mem_ativo["consecutivos_stops"] = 0; mem_ativo["ordem_ativa"] = None
            estado_origem = ordem.get("estado_abertura", estado_atual)
            if estado_origem not in mem_ativo["q_table"]: mem_ativo["q_table"][estado_origem] = {"COMPRA": 0.0, "VENDA": 0.0}
            mem_ativo["q_table"][estado_origem][tipo] += 1.0
            salvar_memoria()
            enviar_alerta_discord(f"REDE NEURAL ACERTOU! ({nome_amigavel}) - Lucro no preco: {preco_atual:,.4f}")
        elif perdeu:
            mem_ativo["total_stops"] += 1; mem_ativo["consecutivos_stops"] += 1; mem_ativo["ordem_ativa"] = None
            mem_ativo["horario_bloqueio_ate"] = (datetime.now() + timedelta(hours=1)).isoformat()
            estado_origem = ordem.get("estado_abertura", estado_atual)
            if estado_origem not in mem_ativo["q_table"]: mem_ativo["q_table"][estado_origem] = {"COMPRA": 0.0, "VENDA": 0.0}
            mem_ativo["q_table"][estado_origem][tipo] -= 1.0
            salvar_memoria()
            enviar_alerta_discord(f"STOP LOSS ACIONADO ({nome_amigavel}) - Recalibrando os neuronios: {preco_atual:,.4f}")
        return

    if mem_ativo.get("horario_bloqueio_ate"):
        if datetime.now() < datetime.fromisoformat(mem_ativo["horario_bloqueio_ate"]):
            LOG_MOTIVOS[ticker]["Bloqueado por Stop Recente"] += 1
            return
        else: mem_ativo["horario_bloqueio_ate"] = None; salvar_memoria()
        
    decisao_neural = treinar_e_prever_rede_neural(df, ticker)
    stops = mem_ativo["consecutivos_stops"]
    stop_calc = mem_ativo["ajuste_stop_base"] + (0.0005 * stops) if stops > 0 else mem_ativo["ajuste_stop_base"]
    profit_calc = mem_ativo["ajuste_profit_base"] - (0.0003 * stops) if stops > 0 else mem_ativo["ajuste_profit_base"]
    
    if estado_atual not in mem_ativo["q_table"]:
        mem_ativo["q_table"][estado_atual] = {"COMPRA": 0.0, "VENDA": 0.0}

    if decisao_neural == "COMPRA":
        if mem_ativo["q_table"][estado_atual].get("COMPRA", 0.0) >= -2.0:
            tp = preco_atual * (1 + profit_calc)
            sl = preco_atual * (1 - stop_calc)
            mem_ativo["ordem_ativa"] = {"tipo": "COMPRA", "entrada": preco_atual, "tp": tp, "sl": sl, "estado_abertura": estado_atual}
            salvar_memoria()
            enviar_alerta_discord(f"🚀 ORDEM DE COMPRA EXECUTADA ({nome_amigavel})\nPreço: {preco_atual:,.4f}\nTP: {tp:,.4f}\nSL: {sl:,.4f}")
        else:
            LOG_MOTIVOS[ticker]["Filtro Q-Table Barrou"] += 1
            
    elif decisao_neural == "VENDA":
        if mem_ativo["q_table"][estado_atual].get("VENDA", 0.0) >= -2.0:
            tp = preco_atual * (1 - profit_calc)
            sl = preco_atual * (1 + stop_calc)
            mem_ativo["ordem_ativa"] = {"tipo": "VENDA", "entrada": preco_atual, "tp": tp, "sl": sl, "estado_abertura": estado_atual}
            salvar_memoria()
