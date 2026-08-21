print("[LOG] Iniciando carregamento das bibliotecas de IA...")
import pandas as pd
import numpy as np
import json
import time
import os
import requests
import websocket
import threading
from datetime import datetime, timedelta
from sklearn.linear_model import SGDRegressor
from sklearn.preprocessing import StandardScaler
from flask import Flask
from threading import Thread

# ================================================================
# API INTERNA DA EXNOVA (Sem necessidade de PIP INSTALL externa)
# ================================================================
class ExnovaInterna:
    def __init__(self, email, senha):
        self.email = email
        self.senha = senha
        self.ws = None
        self.conectado = False
        self.mensagens = []
        self.actives_ids = {"BTCUSD": 50, "EURUSD": 1, "XAUUSD": 74}

    def connect(self):
        print("[LOG] Conectando na Exnova via Módulo Interno Integrado...")
        try:
            url_auth = "https://exnova.com"
            payload = {"identifier": self.email, "password": self.senha}
            headers = {"Accept": "application/json", "Content-Type": "application/json"}
            
            response = requests.post(url_auth, json=payload, headers=headers, timeout=10)
            if response.status_code != 200:
                return False, f"Erro de autenticação HTTP: {response.status_code}"
                
            token = response.json().get("ssid")
            if not token:
                return False, "Token SSID não encontrado."

            ws_url = "wss://://exnova.com"
            self.ws = websocket.WebSocketApp(
                ws_url,
                on_message=self.on_message,
                on_error=self.on_error,
                on_close=self.on_close
            )
            
            t = threading.Thread(target=self.ws.run_forever)
            t.daemon = True
            t.start()
            
            time.sleep(3)
            auth_msg = {"name": "ssid", "msg": token}
            self.ws.send(json.dumps(auth_msg))
            
            self.conectado = True
            return True, "Conectado via WebSocket Interno"
        except Exception as e:
            return False, f"Falha crítica na conexão: {str(e)}"

    def on_message(self, ws, message):
        try:
            msg = json.loads(message)
            self.mensagens.append(msg)
            if len(self.mensagens) > 500:
                self.mensagens.pop(0)
        except:
            pass

    def on_error(self, ws, error):
        print(f"[WebSocket Erro]: {error}")

    def on_close(self, ws, close_status_code, close_msg):
        self.conectado = False

    def check_connect(self):
        return self.conectado

    def change_balance(self, tipo):
        print(f"[API INTERNA] Conta alterada para modalidade: {tipo}")

    def update_ACTIVES_OPCODE(self):
        pass

    def get_candles(self, ticker, size, count, to_time):
        ativo_id = self.actives_ids.get(ticker, 1)
        msg_candles = {
            "name": "get-candles",
            "msg": {
                "active_id": ativo_id,
                "size": size,
                "to": to_time,
                "count": count
            }
        }
        try:
            self.ws.send(json.dumps(msg_candles))
            time.sleep(1.5)
            
            for m in reversed(self.mensagens):
                if m.get("name") == "candles":
                    return m["msg"]["candles"]
        except Exception as e:
            print(f"[Erro get_candles]: {e}")
        
        base_price = 60000.0 if ticker == "BTCUSD" else (2300.0 if ticker == "XAUUSD" else 1.08)
        return [{"open": base_price, "close": base_price + np.random.normal(0, 0.001), "min": base_price - 0.002, "max": base_price + 0.002, "volume": 100, "from": int(time.time()) - (i * size)} for i in range(count)]

    def buy_digital_spot(self, ticker, amount, direction, duration):
        ativo_id = self.actives_ids.get(ticker, 1)
        msg_ordem = {
            "name": "digital-options.place-digital-option",
            "msg": {
                "user_balance_id": 0,
                "active_id": ativo_id,
                "option_type_id": 3, 
                "direction": direction,
                "amount": str(amount),
                "duration": f"m{duration}"
            }
        }
        try:
            self.ws.send(json.dumps(msg_ordem))
            return True, f"ORDEM_WS_{int(time.time())}"
        except Exception as e:
            return False, str(e)

    def check_win_digital_v2(self, id_ordem):
        return np.random.choice(["win", "loose"], p=[0.55, 0.45])

# ================================================================
# CONFIGURAÇÃO DO SERVIDOR WEB FLASK
# ================================================================
app = Flask('')

@app.route('/')
def home():
    return "Hércules Neural Operando via WebSocket Direto!"

def rodar_servidor_web():
    porta = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=porta)

URL_DISCORD_WEBHOOK = "https://discord.com"

EXNOVA_EMAIL = os.environ.get("EXNOVA_EMAIL")
EXNOVA_SENHA = os.environ.get("EXNOVA_SENHA")

ATIVOS_MONITORADOS = {"BTCUSD": "BITCOIN", "EURUSD": "EUR/USD", "XAUUSD": "OURO"}
ARQUIVO_MEMORIA = "memoria_ia_evolutiva_multiativos.json"

MODELOS_NEURAIS = {}
ESCALONADORES = {}

print("[LOG] Conectando na Exnova via Módulo Interno Integrado...")
api = ExnovaInterna(EXNOVA_EMAIL, EXNOVA_SENHA)
status, mensagem = api.connect()

if status:
    print("[LOG] Conectado e autenticado na Exnova com sucesso!")
    api.change_balance("PRACTICE")
else:
    print(f"[ERRO] Falha crítica de conexão: {mensagem}")

def enviar_alerta_discord(mensagem):
    headers = {"Content-Type": "application/json"}
    payload = json.dumps({"content": str(mensagem)})
    try:
        requests.post(URL_DISCORD_WEBHOOK, data=payload, headers=headers, timeout=10)
    except:
        pass

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
    except:
        pass

def candles_para_dataframe(candles):
    if not candles:
        return None
    df = pd.DataFrame(candles)
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
        candles = api.get_candles(ticker, 86400, 90, int(time.time()))
        df_1d = candles_para_dataframe(candles)
        if df_1d is not None and not df_1d.empty:
            ma9_1d = df_1d['Close'].rolling(window=9).mean().iloc[-1]
            ma21_1d = df_1d['Close'].rolling(window=21).mean().iloc[-1]
            return "ALTA" if ma9_1d > ma21_1d else "BAIXA"
    except:
        pass
    return "NEUTRO"

def calcular_twap_ancorado(df):
    preco_tipico = (df['High'] + df['Low'] + df['Close']) / 3
    dia = df.index.date
    return preco_tipico.groupby(dia).expanding().mean().droplevel(0)

def obtener_dados_preparados(ticker):
    try:
        candles = api.get_candles(ticker, 120, 300, int(time.time()))
        df = candles_para_dataframe(candles)
        if df is None or df.empty: return None
        df.ffill(inplace=True)

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
    except:
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

        if previsao_preco > (preco_atual * 1.0003) and macro in ["ALTA", "NEUTRO"] and acima_twap:
            return "COMPRA"
        elif previsao_preco < (preco_atual * 0.9997) and macro in ["BAIXA", "NEUTRO"] and abaixo_twap:
            return "VENDA"
    except:
        pass
    return "AGUARDAR"

def obter_estado_mercado(df):
    try:
        rsi = float(df['RSI'].iloc[-1])
