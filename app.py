import yfinance as yf
import pandas as pd
import numpy as np
import json
import time
import os
import requests
from datetime import datetime, timedelta

# ==============================================================================
# CONFIGURAÇÕES DE CONEXÃO (TELEGRAM E ATIVO)
# ==============================================================================
# IMPORTANTE: Coloque suas credenciais reais aqui ou configure nas variáveis de ambiente do Render
TOKEN_TELEGRAM = os.environ.get("TOKEN_TELEGRAM", "SEU_TOKEN_AQUI")
CHAT_ID_TELEGRAM = os.environ.get("CHAT_ID_TELEGRAM", "SEU_CHAT_ID_AQUI")

TICKER_OURO = "GC=F" # Padrão Spot XAU/USD internacional
ARQUIVO_MEMORIA = "memoria_ia_evolutiva.json"

# ==============================================================================
# FUNÇÃO DE DISPARO DE NOTIFICAÇÃO PARA O SEU CELULAR
# ==============================================================================
def enviar_alerta_telegram(mensagem):
    if TOKEN_TELEGRAM == "SEU_TOKEN_AQUI" or CHAT_ID_TELEGRAM == "SEU_CHAT_ID_AQUI":
        print(f"[Aviso Sem Telegram]: {mensagem}")
        return
    url = f"https://telegram.org{TOKEN_TELEGRAM}/sendMessage"
    payload = {"chat_id": CHAT_ID_TELEGRAM, "text": mensagem, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Erro ao disparar Telegram: {e}")

# ==============================================================================
# CARREGAMENTO DA MEMÓRIA ADAPTATIVA DA IA
# ==============================================================================
if os.path.exists(ARQUIVO_MEMORIA):
    with open(ARQUIVO_MEMORIA, 'r') as f:
        memoria_ia = json.load(f)
    print(f"-> Memória carregada! Erros acumulados: {memoria_ia['consecutivos_stops']}")
else:
    memoria_ia = {
        "consecutivos_stops": 0,
        "total_profits": 0,
        "total_stops": 0,
        "ajuste_stop_base": 0.0025,   # -0.25% padrão
        "ajuste_profit_base": 0.0050, # +0.50% padrão
        "ordem_ativa": None           # Guarda se há uma operação aberta em andamento
    }

def salvar_memoria():
    with open(ARQUIVO_MEMORIA, 'w') as f:
        json.dump(memoria_ia, f, indent=4)

# ==============================================================================
# MOTOR CENTRAL DE RASTREAMENTO E APRENDIZADO CONTÍNUO
# ==============================================================================
def processar_ciclo_ia():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] IA varrendo o mercado...")
    
    # Baixa dados de 2 minutos das últimas 48 horas
    df = yf.download(TICKER_OURO, period="2d", interval="2m", progress=False)
    if df.empty:
        return

    # Limpeza de colunas MultiIndex do Yahoo Finance
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = df.columns.str.strip()
    df.ffill(inplace=True)

    preco_atual = float(df['Close'].iloc[-1])
    high_atual = float(df['High'].iloc[-1])
    low_atual = float(df['Low'].iloc[-1])

    # 1. SE HOUVER UMA ORDEM ABERTA, A IA FICA MONITORANDO SE FOI STOPADA OU DEU PROFIT
    if memoria_ia["ordem_ativa"] is not None:
        ordem = memoria_ia["ordem_ativa"]
        print(f"-> Monitorando Ordem Ativa... Entrada: ${ordem['entrada']:.2f} | Preço Atual: ${preco_atual:.2f}")
        
        # Testando barreira de Ganho (Take Profit)
        if high_atual >= ordem["tp"]:
            memoria_ia["total_profits"] += 1
            memoria_ia["consecutivos_stops"] = 0 # Reinicia histórico de falhas
            memoria_ia["ordem_ativa"] = None
            salvar_memoria()
            
            msg = f"🏆 *ALVO ALCANÇADO NA EXNOVA!*\n\n" \
                  f"💰 Operação finalizada com Sucesso.\n" \
                  f"📈 Profit batido em: US$ {ordem['tp']:,.2f}\n" \
                  f"🔄 Cérebro da IA estabilizado em parâmetros ideais."
            enviar_alerta_telegram(msg)
            return

        # Testando barreira de Perda (Stop Loss)
        elif low_atual <= ordem["sl"]:
            memoria_ia["total_stops"] += 1
            memoria_ia["consecutivos_stops"] += 1 # IA memoriza o erro para evoluir
            memoria_ia["ordem_ativa"] = None
            salvar_memoria()
            
            # Ativa o bloqueio temporário de segurança de 2 horas guardando o momento do stop
            memoria_ia["horario_bloqueio_ate"] = (datetime.now() + timedelta(hours=2)).isoformat()
            salvar_memoria()

            msg = f"🚨 *STOP LOSS ACIONADO (IA EM EVOLUÇÃO)*\n\n" \
                  f"🛡️ Proteção ativada em: US$ {ordem['sl']:,.2f}\n" \
                  f"🧠 Módulo adaptativo ativado para corrigir a próxima entrada infantil.\n" \
                  f"⏳ Robô bloqueado por 2 horas para proteção contra fúria do mercado."
            enviar_alerta_telegram(msg)
            return
        
        return # Se há ordem ativa e não bateu em nada, apenas espera a próxima vela

    # 2. VERIFICA SE O ROBÔ ESTÁ DENTRO DO BLOQUEIO DE SEGURANÇA PÓS-STOP
    if "horario_bloqueio_ate" in memoria_ia and memoria_ia["horario_bloqueio_ate"]:
        bloqueio_ate = datetime.fromisoformat(memoria_ia["horario_bloqueio_ate"])
        if datetime.now() < bloqueio_ate:
            print(f"-> Sistema em modo de segurança pós-stop até {bloqueio_ate.strftime('%H:%M:%S')}. Ignorando entradas.")
            return
        else:
            memoria_ia["horario_bloqueio_ate"] = None
            salvar_memoria()

    # 3. CÁLCULO DE GATILHOS (MÉDIAS MÓVEIS)
    df['MA9'] = df['Close'].rolling(window=9).mean()
    df['MA21'] = df['Close'].rolling(window=21).mean()
    
    linha_sinal = df.iloc[-2]
    linha_anterior = df.iloc[-3]
    cruzou_comprado = (linha_anterior['MA9'] <= linha_anterior['MA21']) and (linha_sinal['MA9'] > linha_sinal['MA21'])

    # 4. GERAÇÃO DE SINAL COM AJUSTE EVOLUTIVO CONTRA SEQUÊNCIA DE ERROS
    if cruzou_comprado:
        stops_recentes = memoria_ia["consecutivos_stops"]
        
        # Se a IA errou no passado, ela se corrige alargando o stop e encurtando o profit automaticamente
        if stops_recentes > 0:
            fator_correcao = 0.0005 * stops_recentes
            stop_calc = memoria_ia["ajuste_stop_base"] + fator_correcao
            profit_calc = memoria_ia["ajuste_profit_base"] - fator_correcao
            status_motor = f"⚠️ PROTEÇÃO ADAPTATIVA (Corrigindo {stops_recentes} erros)"
        else:
            stop_calc = memoria_ia["ajuste_stop_base"]
            profit_calc = memoria_ia["ajuste_profit_base"]
            status_motor = "🟢 MOTOR ESTÁVEL (Alta Precisão)"

        entrada = preco_atual
        tp = entrada * (1 + profit_calc)
        sl = entrada * (1 - stop_calc)

        # Registra a ordem aberta na memória para monitoramento contínuo
        memoria_ia["ordem_ativa"] = {"entrada": entrada, "tp": tp, "sl": sl, "tempo": datetime.now().isoformat()}
        salvar_memoria()

        # Calcula estatística básica de assertividade para exibir no alerta
        total = memoria_ia["total_profits"] + memoria_ia["total_stops"]
        taxa = (memoria_ia["total_profits"] / total * 100) if total > 0 else 100.0

        msg_gatilho = f"🔥 *NOVO GATILHO DE COMPRA ENCONTRADO!* 🔥\n\n" \
                      f"🤖 *Status da IA:* {status_motor}\n" \
                      f"📊 *Taxa de Acerto Atual:* {taxa:.1f}% ({memoria_ia['total_profits']}G / {memoria_ia['total_stops']}S)\n" \
                      f"🎯 *Ativo:* Ouro Spot (XAU/USD)\n\n" \
                      f"📥 *ONDE COMPRAR:* Mercado em *US$ {entrada:,.2f}*\n" \
                      f"🟢 *TAKE PROFIT (ALVO):* US$ {tp:,.2f}\n" \
                      f"🔴 *STOP LOSS (DEFESA):* US$ {sl:,.2f}\n\n" \
                      f"📱 _Copie os valores exatos para a sua boleta na Exnova!_"
        
        enviar_alerta_telegram(msg_gatilho)

# ==============================================================================
# EXECUÇÃO DO LOOP DA NUVEM (SEGUNDO PLANO INFINITO)
# ==============================================================================
if __name__ == "__main__":
    enviar_alerta_telegram("✅ *IA Operacional Iniciada com Sucesso em Segundo Plano!* Monitorando o Ouro 24/7...")
    while True:
        try:
            processar_ciclo_ia()
        except Exception as e:
            print(f"Erro no ciclo: {e}")
        
        # Como as velas são de 2 minutos, o app dorme por 60 segundos antes de verificar novamente
        time.sleep(60)
