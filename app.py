print("[LOG] Iniciando carregamento das bibliotecas de IA...")
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

# Biblioteca não-oficial da Exnova (comunidade / engenharia reversa)
from Exnovaapi.stable_api import Exnova

# Configuração do Flask para manter o Web Service do Render ativo
app = Flask('')

@app.route('/')
def home():
    return "Hércules Neural operando com preço Exnova em segundo plano!"

def rodar_servidor_web():
    porta = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=porta)

# ================================================================
# CONFIGURAÇÃO DEFINITIVA - SEU WEBHOOK E CANAL
# ================================================================
URL_DISCORD_WEBHOOK = "https://discord.com"

# ================================================================
# CREDENCIAIS DA EXNOVA (Configuradas no Ambiente do Render)
# ================================================================
EXNOVA_EMAIL = os.environ.get("EXNOVA_EMAIL")
EXNOVA_SENHA = os.environ.get("EXNOVA_SENHA")

# ATENÇÃO: Nomes padronizados para puxar candles e operar digital na Exnova.
# Se operar em finais de semana, adicione "-OTC" na string do ativo (Ex: "EURUSD-OTC")
ATIVOS_MONITORADOS = {
    "BTCUSD": "BITCOIN", 
    "EURUSD": "EUR/USD", 
    "XAUUSD": "OURO"
}

ARQUIVO_MEMORIA = "memoria_ia_evolutiva_multiativos.json"
MODELOS_NEURAIS = {}
ESCALONADORES = {}

# ================================================================
# CONEXÃO COM A EXNOVA
# ================================================================
print("[LOG] Conectando na Exnova...")
api = Exnova(EXNOVA_EMAIL, EXNOVA_SENHA)
status, mensagem = api.connect()

if status:
    print("[LOG] Conectado à Exnova com sucesso!")
    api.change_balance("PRACTICE")  # Troque para "REAL" quando os testes acabarem
    print("[LOG] Atualizando tabela interna de opcodes da Exnova...")
    api.update_ACTIVES_OPCODE()     # Sincroniza os IDs internos da plataforma
else:
    print(f"[ERRO] Falha ao conectar na Exnova: {mensagem}")

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
            "ordem_ativa": None, "horario_bloqueio_ate": None, "q_table": {}
        }
    MODELOS_NEURAIS[ticker] = SGDRegressor(max_iter=2000, tol=1e-4, learning_rate='adaptive', eta0=0.005)
    ESCALONADORES[ticker] = StandardScaler()

def salvar_memoria():
    try:
        with open(ARQUIVO_MEMORIA, 'w') as f: json.dump(memoria_ia, f, indent=4)
    except Exception as e:
        print(f"[Erro Memoria]: {e}")

def candles_para_dataframe(candles):
    if not candles or isinstance(candles, bool):
        return None
    df = pd.DataFrame(candles)
    # Conversão dos campos vindos direto do WebSocket/API Exnova
    df.rename(columns={
        "open": "Open", "close": "Close", "min": "Low",
        "max": "High", "volume": "Volume", "from": "Timestamp"
    }, inplace=True)
    df["Timestamp"] = pd.to_datetime(df["Timestamp"], unit="s")
    df.set_index("Timestamp", inplace=True)
    df.sort_index(inplace=True)
    return df

def analisar_macro_tendencia(ticker):
    try:
        # Puxa 90 candles de 1 dia (86400s) diretamente da Exnova
        candles = api.get_candles(ticker, 86400, 90, int(time.time()))
        df_1d = candles_para_dataframe(candles)
        if df_1d is not None and not df_1d.empty:
            ma9_1d = df_1d['Close'].rolling(window=9).mean().iloc[-1]
            ma21_1d = df_1d['Close'].rolling(window=21).mean().iloc[-1]
            return "ALTA" if ma9_1d > ma21_1d else "BAIXA"
    except Exception as e:
        print(f"[Erro Macro Exnova {ticker}]: {e}")
    return "NEUTRO"

def calcular_twap_ancorado(df):
    preco_tipico = (df['High'] + df['Low'] + df['Close']) / 3
    dia = df.index.date
    return preco_tipico.groupby(dia).expanding().mean().droplevel(0)

# ================================================================
# FONTE DE DADOS EDITADA: AGORA APENAS DA PLATAFORMA EXNOVA
# ================================================================
def obtener_dados_preparados(ticker):
    try:
        # Coleta 300 candles de 2 minutos (120s) da Exnova para calcular os indicadores
        candles = api.get_candles(ticker, 120, 300, int(time.time()))
        df = candles_para_dataframe(candles)
        if df is None or df.empty: 
            print(f"[AVISO] Nenhum dado de preço retornado pela Exnova para {ticker}.")
            return None
            
        df.ffill(inplace=True)

        # Indicadores baseados no preço oficial Exnova
        df['MA9'] = df['Close'].rolling(window=9).mean()
        df['MA21'] = df['Close'].rolling(window=21).mean()
        df['MA100'] = df['Close'].rolling(window=100).mean()

        delta = df['Close'].diff()
        ganho = delta.where(delta > 0, 0).rolling(window=14).mean()
        perda = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        df['RSI'] = 100 - (100 / (1 + (ganho / (perda + 1e-9))))

        df['TWAP'] = calcular_twap_ancorado(df)

        df.dropna(inplace=True)
        return df
    except Exception as e:
        print(f"[Erro Preparacao Exnova {ticker}]: {e}")
        return None

def treinar_e_prever_rede_neural(df, ticker):
    try:
        features = df[['Close', 'MA9', 'MA21', 'MA100', 'RSI', 'TWAP']].values
        alvo = df['Close'].shift(-1).ffill().values

        X_scaled = ESCALONADORES[ticker].fit_transform(features)
        MODELOS_NEURAIS[ticker].partial_fit(X_scaled, alvo)

        ultima_linha_features = features[-1].reshape(1, -1)
        ultima_linha_scaled = ESCALONADORES[ticker].transform(ultima_linha_features)

        previsao_preco = MODELOS_NEURAIS[ticker].predict(ultima_linha_scaled)
        preco_atual = df['Close'].iloc[-1]
        twap_atual = df['TWAP'].iloc[-1]

        macro = analisar_macro_tendencia(ticker)

        acima_twap = preco_atual > twap_atual
        abaixo_twap = preco_atual < twap_atual

        # Filtro milimétrico usando os preços reais da corretora
        if previsao_preco > (preco_atual * 1.0003) and macro in ["ALTA", "NEUTRO"] and acima_twap:
            return "COMPRA"
        elif previsao_preco < (preco_atual * 0.9997) and macro in ["BAIXA", "NEUTRO"] and abaixo_twap:
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
    mem = memoria_ia[ticker]
    
    if mem["horario_bloqueio_ate"]:
        if datetime.now().isoformat() < mem["horario_bloqueio_ate"]:
            return
        else:
            mem["horario_bloqueio_ate"] = None
            mem["consecutivos_stops"] = 0
            salvar_memoria()

    if mem["ordem_ativa"]:
        id_ordem = mem["ordem_ativa"]
        resultado = api.check_win_digital_v2(id_ordem)
        
        if resultado in ["win", "loose", "equal"] or resultado is not None:
            if resultado == "win":
                mem["total_profits"] += 1
                mem["consecutivos_stops"] = 0
                enviar_alerta_discord(f"💰 **VITÓRIA** no ativo {nome_amigavel}! Preço bateu com o modelo Exnova. ID: {id_ordem}")
            elif resultado == "loose":
                mem["total_stops"] += 1
                mem["consecutivos_stops"] += 1
                enviar_alerta_discord(f"🚨 **DERROTA** no ativo {nome_amigavel}. ID: {id_ordem}")
                
                if mem["consecutivos_stops"] >= 3:
                    bloqueio_fim = (datetime.now() + timedelta(minutes=30)).isoformat()
                    mem["horario_bloqueio_ate"] = bloqueio_fim
                    enviar_alerta_discord(f"⚠️ {nome_amigavel} em pausa de 30m para recalibragem.")
            
            mem["ordem_ativa"] = None
            salvar_memoria()
            return
        else:
            return

    df = obtener_dados_preparados(ticker)
    if df is None:
        return

    decisao = treinar_e_prever_rede_neural(df, ticker)
    estado = obter_estado_mercado(df)
    print(f"[IA EXNOVA] {nome_amigavel} | Preço Atual: {df['Close'].iloc[-1]} | Decisão: {decisao}")

    if decisao in ["COMPRA", "VENDA"]:
        direcao = "call" if decisao == "COMPRA" else "put"
        valor_operacao = 2.0  # Ajuste o valor da sua entrada aqui
        duracao_minutos = 1   
        
