import yfinance as yf
import pandas as pd
import numpy as np
import json
import time
import os
import requests
from datetime import datetime, timedelta

# ================================================================
# CREDENCIAIS CONFIGURADAS DE FORMA DEFINITIVA
# ================================================================
TOKEN_TELEGRAM = "8351646305:AAFCN6_ymS3Qb8kA4PxqyfT7x0Zi-bpTokA"
CHAT_ID_TELEGRAM = "-1003879813604" 
TICKER_OURO = "GC=F" 
ARQUIVO_MEMORIA = "memoria_ia_evolutiva.json"

def enviar_alerta_telegram(mensagem):
    if TOKEN_TELEGRAM == "SEU_TOKEN_AQUI" or CHAT_ID_TELEGRAM == "SEU_CHAT_ID_AQUI":
        print(f"[Aviso Sem Telegram]: {mensagem}")
        return
    
    # CORREÇÃO 1: Endereço oficial e obrigatório da API do Telegram
    url = f"https://telegram.org{TOKEN_TELEGRAM}/sendMessage"
    
    # CORREÇÃO 2: Ajustado de 'message' para 'mensagem' para eliminar o NameError
    payload = {"chat_id": CHAT_ID_TELEGRAM, "text": mensagem, "parse_mode": "Markdown"}
    
    try: 
        response = requests.post(url, json=payload, timeout=10)
        print(f"[Resposta Telegram]: Status {response.status_code}")
    except Exception as e: 
        print(f"[Erro de Conexão]: {e}")

if os.path.exists(ARQUIVO_MEMORIA):
    with open(ARQUIVO_MEMORIA, 'r') as f: memoria_ia = json.load(f)
else:
    memoria_ia = {"consecutivos_stops": 0, "total_profits": 0, "total_stops": 0, "ajuste_stop_base": 0.0025, "ajuste_profit_base": 0.0050, "ordem_ativa": None}

def salvar_memoria():
    # CORREÇÃO 3: Corrigido de ARQUEMA_MEMORIA para ARQUIVO_MEMORIA para evitar travamento ao salvar
    with open(ARQUIVO_MEMORIA, 'w') as f: json.dump(memoria_ia, f, indent=4)

def processar_ciclo_ia():
    df = yf.download(TICKER_OURO, period="2d", interval="2m", progress=False)
    if df.empty: return
    if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
    df.columns = df.columns.str.strip()
    df.ffill(inplace=True)
    
    preco_atual = float(df['Close'].iloc[-1])
    high_atual = float(df['High'].iloc[-1])
    low_atual = float(df['Low'].iloc[-1])

    if memoria_ia["ordem_ativa"] is not None:
        ordem = memoria_ia["ordem_ativa"]
        if high_atual >= ordem["tp"]:
            memoria_ia["total_profits"] += 1
            memoria_ia["consecutivos_stops"] = 0
            memoria_ia["ordem_ativa"] = None
            salvar_memoria()
            enviar_alerta_telegram(f"🏆 *ALVO ALCANÇADO NA EXNOVA!*\n\n📈 Profit batido em: US$ {ordem['tp']:,.2f}")
        elif low_atual <= ordem["sl"]:
            memoria_ia["total_stops"] += 1
            memoria_ia["consecutivos_stops"] += 1
            memoria_ia["ordem_ativa"] = None
            memoria_ia["horario_bloqueio_ate"] = (datetime.now() + timedelta(hours=2)).isoformat()
            salvar_memoria()
            enviar_alerta_telegram(f"🚨 *STOP LOSS ACIONADO (IA EM EVOLUÇÃO)*\n\n🛡️ Proteção ativada em: US$ {ordem['sl']:,.2f}")
        return

    if "horario_bloqueio_ate" in memoria_ia and memoria_ia["horario_bloqueio_ate"]:
        if datetime.now() < datetime.fromisoformat(memoria_ia["horario_bloqueio_ate"]): return
        else: memoria_ia["horario_bloqueio_ate"] = None; salvar_memoria()

    df['MA9'] = df['Close'].rolling(window=9).mean()
    df['MA21'] = df['Close'].rolling(window=21).mean()
    if (df['MA9'].iloc[-3] <= df['MA21'].iloc[-3]) and (df['MA9'].iloc[-2] > df['MA21'].iloc[-2]):
        stops_recentes = memoria_ia["consecutivos_stops"]
        stop_calc = memoria_ia["ajuste_stop_base"] + (0.0005 * stops_recentes) if stops_recentes > 0 else memoria_ia["ajuste_stop_base"]
        profit_calc = memoria_ia["ajuste_profit_base"] - (0.0005 * stops_recentes) if stops_recentes > 0 else memoria_ia["ajuste_profit_base"]
        
        tp = preco_atual * (1 + profit_calc)
        sl = preco_atual * (1 - stop_calc)
        memoria_ia["ordem_ativa"] = {"entrada": preco_atual, "tp": tp, "sl": sl}
        salvar_memoria()
        
        enviar_alerta_telegram(f"🔥 *NOVO GATILHO DE COMPRA ENCONTRADO!* 🔥\n\n📥 *ENTRADA:* US$ {preco_atual:,.2f}\n🟢 *PROFIT:* US$ {tp:,.2f}\n🔴 *STOP:* US$ {sl:,.2f}")

if __name__ == "__main__":
    print("[Iniciando]: Enviando mensagem de teste...")
    enviar_alerta_telegram("✅ *IA Operacional Iniciada!* Monitorando o Ouro 24/7...")
    while True:
        try: processar_ciclo_ia()
        except: pass
        time.sleep(60)
