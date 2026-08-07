import yfinance as yf
import pandas as pd
import numpy as np
import json
import time
import os
import requests
from datetime import datetime, timedelta

# ================================================================
# CONFIGURAÇÃO DEFINITIVA - LINK DO SEU DISCORD INTEGRADO
# ================================================================
URL_DISCORD_WEBHOOK = "https://discord.com"

TICKER_OURO = "GC=F" 
ARQUIVO_MEMORIA = "memoria_ia_evolutiva.json"

def enviar_alerta_discord(mensagem):
    payload = {"content": mensagem}
    try: 
        response = requests.post(URL_DISCORD_WEBHOOK, json=payload, timeout=10)
        print(f"[Resposta Discord]: Status {response.status_code}")
    except Exception as e: 
        print(f"[Erro de Conexão Discord]: {e}")

# Inicialização da Memória da IA Avançada
if os.path.exists(ARQUIVO_MEMORIA):
    with open(ARQUIVO_MEMORIA, 'r') as f: memoria_ia = json.load(f)
else:
    memoria_ia = {
        "total_profits": 0,
        "total_stops": 0,
        "consecutivos_stops": 0,
        "ajuste_stop_base": 0.0020,   # Stop inicial mais apertado (Proteção)
        "ajuste_profit_base": 0.0040, # Alvo inicial matemático
        "ordem_ativa": None,
        "q_table": {}                 # Tabela de aprendizado real por estados do mercado
    }

def salvar_memoria():
    with open(ARQUIVO_MEMORIA, 'w') as f: json.dump(memoria_ia, f, indent=4)

def obter_estado_mercado(df):
    """ Define o estado do mercado em string para a tabela de aprendizado da IA """
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

def atualizar_aprendizado(estado, acao, ganhou):
    """ Camada rigorosa de Aprendizado por Reforço (Q-Learning) """
    if estado == "INDETERMINADO": return
    if "q_table" not in memoria_ia: memoria_ia["q_table"] = {}
    if estado not in memoria_ia["q_table"]:
        memoria_ia["q_table"][estado] = {"COMPRA": 0.0, "VENDA": 0.0}
        
    recompensa = 1.0 if ganhou else -1.5 # Punição maior para o Stop Loss para forçar rigor absoluto
    lr = 0.2  # Taxa de aprendizado
    
    # Atualiza o peso da decisão na memória de longo prazo
    memoria_ia["q_table"][estado][acao] += lr * (recompensa - memoria_ia["q_table"][estado][acao])
    salvar_memoria()

def processar_ciclo_ia():
    df = yf.download(TICKER_OURO, period="3d", interval="2m", progress=False)
    if df.empty: return
    if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
    df.columns = df.columns.str.strip()
    df.ffill(inplace=True)
    
    # --- CAMADA DE INDICADORES TÉCNICOS ---
    df['MA9'] = df['Close'].rolling(window=9).mean()
    df['MA21'] = df['Close'].rolling(window=21).mean()
    
    # Cálculo do RSI para evitar falsos rompimentos
    delta = df['Close'].diff()
    ganho = delta.where(delta > 0, 0).rolling(window=14).mean()
    perda = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = ganho / (perda + 1e-9)
    df['RSI'] = 100 - (100 / (1 + rs))
    
    preco_atual = float(df['Close'].iloc[-1])
    high_atual = float(df['High'].iloc[-1])
    low_atual = float(df['Low'].iloc[-1])
    
    estado_atual = obter_estado_mercado(df)

    # --- CAMADA DE MONITORAMENTO DE ORDEM ATIVA ---
    if memoria_ia["ordem_ativa"] is not None:
        ordem = memoria_ia["ordem_ativa"]
        tipo = ordem.get("tipo", "COMPRA")
        
        ganhou = False
        perdeu = False
        
        if tipo == "COMPRA":
            if high_atual >= ordem["tp"]: ganhou = True
            elif low_atual <= ordem["sl"]: perdeu = True
        elif tipo == "VENDA":
            if low_atual <= ordem["tp"]: ganhou = True
            elif high_atual >= ordem["sl"]: perdeu = True
            
        if ganhou:
            memoria_ia["total_profits"] += 1
            memoria_ia["consecutivos_stops"] = 0
            memoria_ia["ordem_ativa"] = None
            atualizar_aprendizado(ordem["estado"], tipo, ganhou=True)
            enviar_alerta_discord(f"🏆 **ALVO ALCANÇADO NA EXNOVA!**\n\n📈 Direção: *{tipo}*\n🟢 Profit batido em: US$ {ordem['tp']:,.2f}")
        elif perdeu:
            memoria_ia["total_stops"] += 1
            memoria_ia["consecutivos_stops"] += 1
            memoria_ia["ordem_ativa"] = None
            memoria_ia["horario_bloqueio_ate"] = (datetime.now() + timedelta(hours=1)).isoformat()
            atualizar_aprendizado(ordem["estado"], tipo, ganhou=False)
            enviar_alerta_discord(f"🚨 **STOP LOSS ACIONADO (IA EM EVOLUÇÃO)**\n\n🛡️ Proteção ativada em: US$ {ordem['sl']:,.2f}")
        return

    if "horario_bloqueio_ate" in memoria_ia and memoria_ia["horario_bloqueio_ate"]:
        if datetime.now() < datetime.fromisoformat(memoria_ia["horario_bloqueio_ate"]): return
        else: memoria_ia["horario_bloqueio_ate"] = None; salvar_memoria()

    # --- CAMADA DE GATILHOS (COMPRA E VENDA) ---
    gatilho_compra = (df['MA9'].iloc[-3] <= df['MA21'].iloc[-3]) and (df['MA9'].iloc[-2] > df['MA21'].iloc[-2])
    gatilho_venda = (df['MA9'].iloc[-3] >= df['MA21'].iloc[-3]) and (df['MA9'].iloc[-2] < df['MA21'].iloc[-2])
    
    # Filtro de assertividade da memória Inteligente (Se o estado costuma dar stop, bloqueia a operação)
    score_compra = memoria_ia["q_table"].get(estado_atual, {}).get("COMPRA", 0.0)
    score_venda = memoria_ia["q_table"].get(estado_atual, {}).get("VENDA", 0.0)

    # Configuração dinâmica de limites baseada em erros recentes
    stops_recentes = memoria_ia["consecutivos_stops"]
    stop_calc = memoria_ia["ajuste_stop_base"] + (0.0003 * stops_recentes) if stops_recentes > 0 else memoria_ia["ajuste_stop_base"]
    profit_calc = memoria_ia["ajuste_profit_base"] - (0.0002 * stops_recentes) if stops_recentes > 0 else memoria_ia["ajuste_profit_base"]

    # Execução Rigorosa de Compra (Só entra se o RSI permitir e se o aprendizado não estiver negativo para esse estado)
    if gatilho_compra and df['RSI'].iloc[-1] < 68 and score_compra >= -0.5:
        tp = preco_atual * (1 + profit_calc)
        sl = preco_atual * (1 - stop_calc)
        memoria_ia["ordem_ativa"] = {"tipo": "COMPRA", "entrada": preco_atual, "tp": tp, "sl": sl, "estado": estado_atual}
        salvar_memoria()
        enviar_alerta_discord(f"🟢 **NOVO GATILHO DE COMPRA ENCONTRADO!** 🟢\n\n📥 **ENTRADA:** US$ {preco_atual:,.2f}\n🎯 **PROFIT (ALVO):** US$ {tp:,.2f}\n🛑 **STOP LOSS:** US$ {sl:,.2f}\n🧠 *Estado de Análise:* `{estado_atual}`")

    # Execução Rigorosa de Venda (Operação Inversa)
    elif gatilho_venda and df['RSI'].iloc[-1] > 32 and score_venda >= -0.5:
        tp = preco_atual * (1 - profit_calc)
        sl = preco_atual * (1 + stop_calc)
        memoria_ia["ordem_ativa"] = {"tipo": "VENDA", "entrada": preco_atual, "tp": tp, "sl": sl, "estado": estado_atual}
        salvar_memoria()
        enviar_alerta_discord(f"🔴 **NOVO GATILHO DE VENDA ENCONTRADO!** 🔴\n\n📥 **ENTRADA:** US$ {preco_atual:,.2f}\n🎯 **PROFIT (ALVO):** US$ {tp:,.2f}\n🛑 **STOP LOSS:** US$ {sl:,.2f}\n🧠 *Estado de Análise:* `{estado_atual}`")

if __name__ == "__main__":
    print("[Iniciando]: Sistema de IA com Aprendizado por Reforço...")
    enviar_alerta_discord("⚙️ **IA Operacional Reiniciada com Sucesso!**\n📊 *Mapeamento ativado:* Compras, Vendas e Camada Rigorosa de Aprendizado Automático (Q-Learning).")
    while True:
        try: processar_ciclo_ia()
        except Exception as e: print(f"[Erro no processamento]: {e}")
        time.sleep(60)
