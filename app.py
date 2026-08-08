print("[LOG] Iniciando loop do script principal...")
import yfinance as yf
import pandas as pd
import numpy as np
import json
import time
import os
import requests
from datetime import datetime, timedelta

# ================================================================
# CONFIGURAÇÃO DEFINITIVA - SEU WEBHOOK NOVO E VALIDADO
# ================================================================
URL_DISCORD_WEBHOOK = "https://discord.com"

# Lista de Moedas/Ativos Monitorados
ATIVOS_MONITORADOS = {
    "GC=F": "OURO",
    "BTC-USD": "BITCOIN",
    "EURUSD=X": "EUR/USD"
}

ARQUIVO_MEMORIA = "memoria_ia_evolutiva_multiativos.json"

def enviar_alerta_discord(mensagem):
    print(f"[LOG] Enviando para o Discord: {mensagem[:40]}...")
    payload = {"content": mensagem}
    try: 
        response = requests.post(URL_DISCORD_WEBHOOK, json=payload, timeout=10)
        print(f"[Resposta Discord]: Status {response.status_code}")
    except Exception as e: 
        print(f"[Erro de Conexão Discord]: {e}")

# Inicialização Segura da Memória
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
            "total_profits": 0,
            "total_stops": 0,
            "consecutivos_stops": 0,
            "ajuste_stop_base": 0.0020,
            "ajuste_profit_base": 0.0040,
            "ordem_ativa": None,
            "horario_bloqueio_ate": None,
            "q_table": {}
        }

def salvar_memoria():
    try:
        with open(ARQUIVO_MEMORIA, 'w') as f: json.dump(memoria_ia, f, indent=4)
    except Exception as e:
        print(f"[LOG] Erro ao salvar memória: {e}")

def obter_estado_mercado(df):
    try:
        rsi = float(df['RSI'].iloc[-1])
        tendencia = "ALTA" if df['MA9'].iloc[-1] > df['MA21'].iloc[-1] else "BAIXA"
        volatilidade = "ALTA" if df['Close'].std() > df['Close'].rolling(20).std().iloc[-1] else "BAIXA"
        
        if rsi > 70: situacao_rsi = "SOBRECOMPRADO"
        elif rsi < 30: situacao_rsi = "SOBREVENDIDO"
        else: situacao_rsi = "NEUTRO"
        
        return f"{tendencia}_{situacao_rsi}_{volatilidade}"
    except:
        return "INDETERMINADO"

def tomar_decisao_analitica(df):
    try:
        rsi_atual = df['RSI'].iloc[-1]
        ma200 = df['Close'].rolling(window=100).mean().iloc[-1]
        preco_atual = df['Close'].iloc[-1]
        
        cruzamento_alta = (df['MA9'].iloc[-3] <= df['MA21'].iloc[-3]) and (df['MA9'].iloc[-2] > df['MA21'].iloc[-2])
        cruzamento_baixa = (df['MA9'].iloc[-3] >= df['MA21'].iloc[-3]) and (df['MA9'].iloc[-2] < df['MA21'].iloc[-2])
        
        if cruzamento_alta and rsi_atual < 65 and preco_atual > ma200:
            return "COMPRA"
        elif cruzamento_baixa and rsi_atual > 35 and preco_atual < ma200:
            return "VENDA"
    except Exception as e:
        print(f"[LOG] Erro na tomada de decisão: {e}")
        
    return "AGUARDAR"

def atualizar_aprendizado(ticker, estado, acao, ganhou):
    if estado == "INDETERMINADO": return
    if estado not in memoria_ia[ticker]["q_table"]:
        memoria_ia[ticker]["q_table"][estado] = {"COMPRA": 0.0, "VENDA": 0.0}
        
    recompensa = 1.0 if ganhou else -1.5
    lr = 0.2
    memoria_ia[ticker]["q_table"][estado][acao] += lr * (recompensa - memoria_ia[ticker]["q_table"][estado][acao])
    salvar_memoria()

def processar_ciclo_ia_por_ativo(ticker, nome_amigavel):
    print(f"[LOG] Baixando dados para: {nome_amigavel}...")
    df = yf.download(ticker, period="5d", interval="2m", progress=False)
    if df.empty: 
        print(f"[LOG] Dados vazios para {nome_amigavel}")
        return
        
    if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
    df.columns = df.columns.str.strip()
    df.ffill(inplace=True)
    
    df['MA9'] = df['Close'].rolling(window=9).mean()
    df['MA21'] = df['Close'].rolling(window=21).mean()
    
    delta = df['Close'].diff()
    ganho = delta.where(delta > 0, 0).rolling(window=14).mean()
    perda = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = ganho / (perda + 1e-9)
    df['RSI'] = 100 - (100 / (1 + rs))
    
    preco_atual = float(df['Close'].iloc[-1])
    high_atual = float(df['High'].iloc[-1])
    low_atual = float(df['Low'].iloc[-1])
    
    estado_atual = obter_estado_mercado(df)
    mem_ativo = memoria_ia[ticker]

    if mem_ativo["ordem_ativa"] is not None:
        ordem = mem_ativo["ordem_ativa"]
        tipo = ordem.get("tipo", "COMPRA")
        ganhou, perdeu = False, False
        
        if tipo == "COMPRA":
            distancia_alvo = ordem["tp"] - ordem["entrada"]
            if preco_atual >= (ordem["entrada"] + (distancia_alvo * 0.5)) and ordem["sl"] < ordem["entrada"]:
                ordem["sl"] = ordem["entrada"]
                salvar_memoria()
                enviar_alerta_discord(f"🛡️ **MECANISMO DE DEFESA ({nome_amigavel})**\nOperação andou 50%! Stop ajustado para o zero a zero (Entrada: {ordem['sl']:,.4f}).")
            
            if high_atual >= ordem["tp"]: ganhou = True
            elif low_atual <= ordem["sl"]: perdeu = True
            
        elif tipo == "VENDA":
            distancia_alvo = ordem["entrada"] - ordem["tp"]
            if preco_atual <= (ordem["entrada"] - (distancia_alvo * 0.5)) and ordem["sl"] > ordem["entrada"]:
                ordem["sl"] = ordem["entrada"]
                salvar_memoria()
                enviar_alerta_discord(f"🛡️ **MECANISMO DE DEFESA ({nome_amigavel})**\nOperação andou 50%! Stop ajustado para o zero a zero (Entrada: {ordem['sl']:,.4f}).")
                
            if low_atual <= ordem["tp"]: ganhou = True
            elif high_atual >= ordem["sl"]: perdeu = True
            
        if ganhou:
            mem_ativo["total_profits"] += 1
            mem_ativo["consecutivos_stops"] = 0
            mem_ativo["ordem_ativa"] = None
            atualizar_aprendizado(ticker, ordem["estado"], tipo, ganhou=True)
            enviar_alerta_discord(f"🏆 **OPERAÇÃO VITORIOSA! ({nome_amigavel})**\n📈 Direção: *{tipo}*\n🟢 Lucro no preço: {preco_atual:,.4f}")
        elif perdeu:
            mem_ativo["total_stops"] += 1
            mem_ativo["consecutivos_stops"] += 1
            mem_ativo["ordem_ativa"] = None
            mem_ativo["horario_bloqueio_ate"] = (datetime.now() + timedelta(hours=1)).isoformat()
            atualizar_aprendizado(ticker, ordem["estado"], tipo, ganhou=False)
            enviar_alerta_discord(f"🚨 **STOP LOSS ACIONADO ({nome_amigavel})**\n🛡️ Proteção ativada no preço: {preco_atual:,.4f}")
        return

    if mem_ativo.get("horario_bloqueio_ate"):
        if datetime.now() < datetime.fromisoformat(mem_ativo["horario_bloqueio_ate"]): return
        else: mem_ativo["horario_bloqueio_ate"] = None; salvar_memoria()

    decisao_ia = tomar_decisao_analitica(df)
    score_compra = mem_ativo["q_table"].get(estado_atual, {}).get("COMPRA", 0.0)
    score_venda = mem_ativo["q_table"].get(estado_atual, {}).get("VENDA", 0.0)

    stops_recentes = mem_ativo["consecutivos_stops"]
    stop_calc = mem_ativo["ajuste_stop_base"] + (0.0003 * stops_recentes) if stops_recentes > 0 else mem_ativo["ajuste_stop_base"]
    profit_calc = mem_ativo["ajuste_profit_base"] - (0.0002 * stops_recentes) if stops_recentes > 0 else mem_ativo["ajuste_profit_base"]

    if decisao_ia == "COMPRA" and score_compra >= -0.5:
        tp = preco_atual * (1 + profit_calc)
        sl = preco_atual * (1 - stop_calc)
        mem_ativo["ordem_ativa"] = {"tipo": "COMPRA", "entrada": preco_atual, "tp": tp, "sl": sl, "estado": estado_atual}
        salvar_memoria()
        enviar_alerta_discord(f"🟢 **IA DECIDIU: MOMENTO DE COMPRA EM {nome_amigavel}** 🟢\n📥 **ENTRADA:** {preco_atual:,.4f}\n🎯 **ALVO (TP):** {tp:,.4f}\n🛑 **STOP INICIAL:** {sl:,.4f}")

    elif decisao_ia == "VENDA" and score_venda >= -0.5:
        tp = preco_atual * (1 - profit_calc)
        sl = preco_atual * (1 + stop_calc)
        mem_ativo["ordem_ativa"] = {"tipo": "VENDA", "entrada": preco_atual, "tp": tp, "sl": sl, "estado": estado_atual}
        salvar_memoria()
        enviar_alerta_discord(f"🔴 **IA DECIDIU: MOMENTO DE VENDA EM {nome_amigavel}** 🔴\n📥 **ENTRADA:** {preco_atual:,.4f}\n🎯 **ALVO (TP):** {tp:,.4f}\n🛑 **STOP INICIAL:** {sl:,.4f}")

if __name__ == "__main__":
    print("[LOG] Iniciando loop do script principal...")
    enviar_alerta_discord("⚙️ **Cérebro de Decisão da IA Ativado!**\n📊 *Ativos:* OURO, BITCOIN e EUR/USD.\n🧠 *Processo:* Monitoramento inteligente e proteção de capital ativos!")
    
    while True:
        try:
            for ticker, nome_amigavel in ATIVOS_MONITORADOS.items():
                processar_ciclo_ia_por_ativo(ticker, nome_amigavel)
                time.sleep(3)
        except Exception as e: 
            print(f"[Erro geral]: {e}")
        time.sleep(60)
