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
# pip install -e git+https://github.com/CassDs/exnovaapi.git#egg=exnovaapi
from Exnovaapi.stable_api import Exnova

# Configuração do Flask para manter o Web Service do Render ativo
app = Flask('')

@app.route('/')
def home():
    return "Hércules Neural operando com sucesso em segundo plano!"

def rodar_servidor_web():
    porta = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=porta)

# ================================================================
# CONFIGURAÇÃO DEFINITIVA - SEU WEBHOOK E CANAL
# ================================================================
URL_DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1537847047917408296/3XyBLhgZnprJdwfVeDoAv6G49CwOzLW5CGj4jqw-vZyBgC9JFPdAqGp2IXJKi7p5IO1X"

# ================================================================
# CREDENCIAIS DA EXNOVA
# Defina como variáveis de ambiente no Render (não deixe no código!)
# ================================================================
EXNOVA_EMAIL = os.environ.get("EXNOVA_EMAIL")
EXNOVA_SENHA = os.environ.get("EXNOVA_SENHA")

# IMPORTANTE: confirme os nomes exatos dos ativos na sua conta com
# api.update_ACTIVES_OPCODE(); api.get_all_ACTIVES_OPCODE() antes de rodar.
# Os nomes abaixo são os mais comuns, mas podem variar (ex: com "-OTC").
ATIVOS_MONITORADOS = {"BTCUSD": "BITCOIN", "EURUSD": "EUR/USD", "XAUUSD": "OURO"}
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
    api.change_balance("PRACTICE")  # troque para "REAL" quando estiver pronto
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

def candles_para_dataframe(candles):
    """Converte a lista de candles da Exnova em um DataFrame no mesmo
    formato que o resto do script espera (Open, High, Low, Close, Volume)."""
    if not candles:
        return None
    df = pd.DataFrame(candles)
    # A Exnova retorna: open, close, min, max, volume, from (timestamp)
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
        # interval em segundos: 86400 = 1 dia
        candles = api.get_candles(ticker, 86400, 90, int(time.time()))
        df_1d = candles_para_dataframe(candles)
        if df_1d is not None and not df_1d.empty:
            ma9_1d = df_1d['Close'].rolling(window=9).mean().iloc[-1]
            ma21_1d = df_1d['Close'].rolling(window=21).mean().iloc[-1]
            return "ALTA" if ma9_1d > ma21_1d else "BAIXA"
    except Exception as e:
        print(f"[Erro Macro {ticker}]: {e}")
    return "NEUTRO"

def calcular_twap_ancorado(df):
    """TWAP (Time-Weighted Average Price) ancorado no início de cada dia.
    Preferido ao VWAP aqui porque o 'volume' retornado por corretoras de
    opções binárias/CFD costuma ser apenas contagem de ticks, não volume
    financeiro real — o que torna o VWAP pouco confiável nesse contexto.
    O TWAP não depende de volume: pondera o preço só pelo tempo, e
    reinicia (ancora) a cada virada de dia."""
    preco_tipico = (df['High'] + df['Low'] + df['Close']) / 3
    dia = df.index.date

    return preco_tipico.groupby(dia).expanding().mean().droplevel(0)

def obter_dados_preparados(ticker):
    try:
        # interval em segundos: 120 = 2 minutos (equivalente ao "2m" do yfinance)
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
    except Exception as e:
        print(f"[Erro Preparacao {ticker}]: {e}")
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

        # Filtro extra: só compra com preço acima do TWAP, só vende com preço abaixo
        acima_twap = preco_atual > twap_atual
        abaixo_twap = preco_atual < twap_atual

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
            mem_ativo["total_profits"] += 1; mem_ativo["consecutivos_stops"] = 0; mem_ativo["ordem_ativa"] = None; salvar_memoria()
            enviar_alerta_discord(f"REDE NEURAL ACERTOU! ({nome_amigavel}) - Lucro no preco: {preco_atual:,.4f}")
        elif perdeu:
            mem_ativo["total_stops"] += 1; mem_ativo["consecutivos_stops"] += 1; mem_ativo["ordem_ativa"] = None
            mem_ativo["horario_bloqueio_ate"] = (datetime.now() + timedelta(minutes=15)).isoformat(); salvar_memoria()
            enviar_alerta_discord(f"STOP LOSS ACIONADO ({nome_amigavel}) - Recalibrando os neuronios: {preco_atual:,.4f}")
        return

    if mem_ativo.get("horario_bloqueio_ate"):
        if datetime.now() < datetime.fromisoformat(mem_ativo["horario_bloqueio_ate"]): return
        else: mem_ativo["horario_bloqueio_ate"] = None; salvar_memoria()

    decisao_neural = treinar_e_prever_rede_neural(df, ticker)
    stops = mem_ativo["consecutivos_stops"]
    stop_calc = mem_ativo["ajuste_stop_base"] + (0.0005 * stops) if stops > 0 else mem_ativo["ajuste_stop_base"]
    profit_calc = mem_ativo["ajuste_profit_base"] - (0.0003 * stops) if stops > 0 else mem_ativo["ajuste_profit_base"]

    if decisao_neural in ["COMPRA", "VENDA"]:
        tp_preco = preco_atual * (1 + profit_calc) if decisao_neural == "COMPRA" else preco_atual * (1 - profit_calc)
        sl_preco = preco_atual * (1 - stop_calc) if decisao_neural == "COMPRA" else preco_atual * (1 + stop_calc)

        mem_ativo["ordem_ativa"] = {
            "tipo": decisao_neural, "entrada": preco_atual, "tp": tp_preco, "sl": sl_preco, "data": datetime.now().isoformat()
        }
        salvar_memoria()
        enviar_alerta_discord(f"🔥 NOVA ORDEM ({nome_amigavel}) - {decisao_neural}\nEntrada: {preco_atual:,.4f} | TP: {tp_preco:,.4f} | SL: {sl_preco:,.4f}")

def loop_principal_ia():
    enviar_alerta_discord("🚀 [SISTEMA] Hércules Neural iniciado com sucesso no Render (dados via Exnova)!")
    while True:
        try:
            for ticker, nome_amigavel in ATIVOS_MONITORADOS.items():
                processar_ciclo_ia_por_ativo(ticker, nome_amigavel)
                time.sleep(5)
            print("[LOG] Ciclo concluído. Aguardando 120 segundos...")
            time.sleep(120)
        except Exception as e:
            print(f"[ERRO CRÍTICO NO LOOP]: {e}")
            time.sleep(30)

# ================================================================
# EXECUÇÃO PARALELA (WEB SERVER + INTELIGÊNCIA ARTIFICIAL)
# ================================================================
if __name__ == "__main__":
    t = Thread(target=loop_principal_ia)
    t.daemon = True
    t.start()

    rodar_servidor_web()
