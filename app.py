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
from flask import Flask
from threading import Thread

# Configuração do Flask para manter o Web Service do Render ativo
app = Flask('')

@app.route('/')
def home():
    return "Hércules Neural operando com sucesso em segundo plano!"

def rodar_servidor_web():
    porta = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=porta, debug=False, use_reloader=False)

# ================================================================
# CONFIGURAÇÃO DEFINITIVA - SEU WEBHOOK NOVO E CANAL LIMPO
# ================================================================
URL_DISCORD_WEBHOOK = "https://discord.com"

ATIVOS_MONITORADOS = {"GC=F": "OURO", "BTC-USD": "BITCOIN", "EURUSD=X": "EUR/USD"}
ARQUIVO_MEMORIA = "memoria_ia_evolutiva_multiativos.json"

MODELOS_NEURAIS = {}
ESCALONADORES = {}

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
memoria_ia = {}

try:
    if os.path.exists(ARQUIVO_MEMORIA):
        with open(ARQUIVO_MEMORIA, 'r', encoding='utf-8', errors='ignore') as f:
            conteudo = f.read().strip()
            if conteudo:
                memoria_ia = json.loads(conteudo)
except Exception as e:
    print(f"[Aviso] Falha ao ler arquivo de memoria, operando em modo RAM: {e}")
    memoria_ia = {}

for ticker, nome in ATIVOS_MONITORADOS.items():
    if not isinstance(memoria_ia, dict) or ticker not in memoria_ia or not isinstance(memoria_ia[ticker], dict):
        memoria_ia[ticker] = {}
    
    campos_obrigatorios = {
        "total_profits": 0, 
        "total_stops": 0, 
        "consecutivos_stops": 0,
        "ajuste_stop_base": 0.0020, 
        "ajuste_profit_base": 0.0040,
        "ordem_ativa": None, 
        "ordem_pendente": None,
        "horario_bloqueio_ate": None, 
        "q_table": {}
    }
    for chave, valor_padrao in campos_obrigatorios.items():
        if chave not in memoria_ia[ticker]:
            memoria_ia[ticker][chave] = valor_padrao
            
    MODELOS_NEURAIS[ticker] = SGDRegressor(max_iter=2000, tol=1e-4, learning_rate='adaptive', eta0=0.005, warm_start=True)
    ESCALONADORES[ticker] = StandardScaler()

def salvar_memoria():
    try:
        with open(ARQUIVO_MEMORIA, 'w', encoding='utf-8') as f: 
            json.dump(memoria_ia, f, indent=4)
    except Exception as e:
        print(f"[Aviso Memória]: Executando armazenamento em cache RAM temporário: {e}")

def analisar_macro_tendencia(ticker):
    try:
        df_1d = yf.download(ticker, period="3mo", interval="1d", progress=False, threads=False)
        if df_1d is None or df_1d.empty:
            return "NEUTRO"
        if isinstance(df_1d.columns, pd.MultiIndex): 
            df_1d.columns = df_1d.columns.get_level_values(0)
        ma9_1d = df_1d['Close'].rolling(window=9).mean().iloc[-1]
        ma21_1d = df_1d['Close'].rolling(window=21).mean().iloc[-1]
        return "ALTA" if ma9_1d > ma21_1d else "BAIXA"
    except Exception as e:
        print(f"[Erro Macro {ticker}]: {e}")
    return "NEUTRO"

def obter_dados_preparados(ticker):
    try:
        df = yf.download(ticker, period="5d", interval="2m", progress=False, threads=False)
        # CONTROLE DE MERCADO FECHADO: Evita travar caso o DataFrame venha vazio no fim de semana
        if df is None or df.empty or len(df) < 50: 
            return None
            
        if isinstance(df.columns, pd.MultiIndex): 
            df.columns = df.columns.get_level_values(0)
        df.columns = df.columns.str.strip()
        df.ffill(inplace=True)
        
        df['MA9'] = df['Close'].rolling(window=9).mean()
        df['MA21'] = df['Close'].rolling(window=21).mean()
        df['MA100'] = df['Close'].rolling(window=100).mean()
        
        df['VOL_MA20'] = df['Volume'].rolling(window=20).mean()
        
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
        features = df[['Close', 'MA9', 'MA21', 'MA100', 'RSI', 'VOL_MA20']].values
        alvo = df['Close'].shift(-1).ffill().values
        
        X_scaled = ESCALONADORES[ticker].fit_transform(features)
        MODELOS_NEURAIS[ticker].partial_fit(X_scaled, alvo)
        
        ultima_linha_features = features[-1].reshape(1, -1)
        ultima_linha_scaled = ESCALONADORES[ticker].transform(ultima_linha_features)
        
        previsao_preco = MODELOS_NEURAIS[ticker].predict(ultima_linha_scaled)
        preco_atual = float(df['Close'].iloc[-1])
        
        macro = analisar_macro_tendencia(ticker)
        
        # --- SEU RASTREADOR DE EXAUSTÃO ORIGINAL ---
        low_atual = float(df['Low'].iloc[-1])
        high_atual = float(df['High'].iloc[-1])
        rsi_atual = float(df['RSI'].iloc[-1])
        
        caca_stop_3picos_compra = False
        caca_stop_3picos_venda = False
        
        if len(df) >= 30:
            low_anterior = float(df['Low'].iloc[-25:-5].min())
            high_anterior = float(df['High'].iloc[-25:-5].max())
            rsi_no_low_anterior = float(df['RSI'].iloc[-25:-5].min())
            rsi_no_high_anterior = float(df['RSI'].iloc[-25:-5].max())
            
            caca_stop_3picos_compra = (low_atual < low_anterior) and (rsi_atual > rsi_no_low_anterior) and (rsi_atual < 35)
            caca_stop_3picos_venda = (high_atual > high_anterior) and (rsi_atual < rsi_no_high_anterior) and (rsi_atual > 65)
        
        if (previsao_preco > (preco_atual * 1.0003) and macro in ["ALTA", "NEUTRO"]) or caca_stop_3picos_compra: 
            return "COMPRA"
        elif (previsao_preco < (preco_atual * 0.9997) and macro in ["BAIXA", "NEUTRO"]) or caca_stop_3picos_venda: 
            return "VENDA"
            
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
    if df is None or len(df) < 50:
        print(f"[Aviso {nome_amigavel}]: Sem dados recentes da API (Mercado fechado ou sem liquidez).")
        return
    
    preco_atual = float(df['Close'].iloc[-1])
    high_atual = float(df['High'].iloc[-1])
    low_atual = float(df['Low'].iloc[-1])
    estado_atual = obter_estado_mercado(df)
    mem_ativo = memoria_ia[ticker]
    
    # 1. GERENCIAMENTO DE ORDEM ATIVA
    if mem_ativo["ordem_ativa"] is not None:
        ordem = mem_ativo["ordem_ativa"]
        tipo = ordem.get("tipo", "COMPRA")
        ganhou, perdeu = False, False
        
        if tipo == "COMPRA":
            if preco_atual >= (ordem["entrada"] + ((ordem["tp"] - ordem["entrada"]) * 0.5)) and ordem["sl"] < ordem["entrada"]:
                ordem["sl"] = ordem["entrada"]
                salvar_memoria()
                enviar_alerta_discord(f"DEFESA NEURAL ({nome_amigavel}) - Stop na Entrada: {ordem['sl']:,.4f}")
            if high_atual >= ordem["tp"]: ganhou = True
            elif low_atual <= ordem["sl"]: perdeu = True
        elif tipo == "VENDA":
            if preco_atual <= (ordem["entrada"] - ((ordem["entrada"] - ordem["tp"]) * 0.5)) and ordem["sl"] > ordem["entrada"]:
                ordem["sl"] = ordem["entrada"]
                salvar_memoria()
                enviar_alerta_discord(f"DEFESA NEURAL ({nome_amigavel}) - Stop na Entrada: {ordem['sl']:,.4f}")
            if low_atual <= ordem["tp"]: ganhou = True
            elif high_atual >= ordem["sl"]: perdeu = True
            
        if ganhou:
            mem_ativo["total_profits"] += 1
            mem_ativo["consecutivos_stops"] = 0
            mem_ativo["ordem_ativa"] = None
            salvar_memoria()
            enviar_alerta_discord(f"🎯 REDE NEURAL ACERTOU! ({nome_amigavel}) - Lucro no preco: {preco_atual:,.4f}")
        elif perdeu:
            mem_ativo["total_stops"] += 1
            mem_ativo["consecutivos_stops"] += 1
            mem_ativo["ordem_ativa"] = None
            mem_ativo["horario_bloqueio_ate"] = (datetime.now() + timedelta(minutes=15)).isoformat()
            salvar_memoria()
            enviar_alerta_discord(f"❌ STOP LOSS ACIONADO ({nome_amigavel}) - Recalibrando os neuronios: {preco_atual:,.4f}")
        return

    # 2. VERIFICAÇÃO DE BLOQUEIO POR TIMEOUT
    if mem_ativo.get("horario_bloqueio_ate"):
