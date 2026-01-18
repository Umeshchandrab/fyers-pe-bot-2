import pandas as pd
import numpy as np
import requests
import time
import schedule
from datetime import datetime
from fyers_apiv2 import fyersModel

# ==========================
# 🔐 FYERS CONFIG
# ==========================
CLIENT_ID = "YOUR_CLIENT_ID"
ACCESS_TOKEN = "YOUR_ACCESS_TOKEN"

fy = fyersModel.FyersModel(
    client_id=CLIENT_ID,
    token=ACCESS_TOKEN,
    log_path=""
)

# ==========================
# 📩 TELEGRAM CONFIG
# ==========================
BOT_TOKEN = "YOUR_BOT_TOKEN"
CHAT_ID = "YOUR_CHAT_ID"

def telegram(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": CHAT_ID, "text": msg})

# ==========================
# 📊 INDICATORS
# ==========================
def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def bollinger(df):
    df["MB"] = df["close"].rolling(20).mean()
    df["STD"] = df["close"].rolling(20).std()
    df["UB"] = df["MB"] + 2 * df["STD"]
    return df

# ==========================
# 📈 DATA FETCH
# ==========================
def get_candles(symbol, tf, days=5):
    data = {
        "symbol": symbol,
        "resolution": tf,
        "date_format": "1",
        "range_from": (datetime.now() - pd.Timedelta(days=days)).strftime("%Y-%m-%d"),
        "range_to": datetime.now().strftime("%Y-%m-%d"),
        "cont_flag": "1"
    }
    res = fy.history(data)
    df = pd.DataFrame(res["candles"],
        columns=["ts","open","high","low","close","vol"])
    return df

# ==========================
# 🎯 ATM PE SELECTION
# ==========================
def get_atm_pe(index_price, index):
    step = 50 if index == "NIFTY" else 100
    strike = round(index_price / step) * step
    expiry = "24JUL"   # 🔴 make dynamic later
    return f"NSE:{index}{expiry}{strike}PE"

# ==========================
# 🧠 HTF EMA CHECK
# ==========================
def htf_check(symbol):
    for tf in ["1D", "240"]:
        df = get_candles(symbol, tf, 60)
        df["EMA5"] = ema(df["close"], 5)
        df["EMA9"] = ema(df["close"], 9)
        df["EMA20"] = ema(df["close"], 20)
        df["EMA50"] = ema(df["close"], 50)

        price = df["close"].iloc[-1]
        for e in ["EMA5","EMA9","EMA20","EMA50"]:
            if abs(price - df[e].iloc[-1]) / df[e].iloc[-1] <= 0.0015:
                return True
    return False

# ==========================
# 🔍 LOWER TF CONFIRMATION
# ==========================
def ltf_confirm(symbol):
    for tf in ["30","15","10"]:
        df = get_candles(symbol, tf, 5)
        df = bollinger(df)
        last = df.iloc[-1]
        if last["close"] < last["open"] and last["close"] > last["UB"]:
            return True
    return False

# ==========================
# 📥 BUY ORDER
# ==========================
def buy_option(symbol, qty):
    fy.place_order({
        "symbol": symbol,
        "qty": qty,
        "type": 2,
        "side": 1,          # BUY
        "productType": "INTRADAY",
        "limitPrice": 0,
        "stopPrice": 0,
        "validity": "DAY"
    })

def sell_option(symbol, qty):
    fy.place_order({
        "symbol": symbol,
        "qty": qty,
        "type": 2,
        "side": -1,
        "productType": "INTRADAY",
        "limitPrice": 0,
        "stopPrice": 0,
        "validity": "DAY"
    })

# ==========================
# 🎯 EXIT MANAGEMENT
# ==========================
def manage_exit(option_symbol, qty):
    half = qty // 2
    exited_ema = False

    while True:
        df = get_candles(option_symbol, "5", 1)
        df["EMA20"] = ema(df["close"], 20)
        df = bollinger(df)

        price = df["close"].iloc[-1]

        # 50% exit at EMA20
        if not exited_ema and price >= df["EMA20"].iloc[-1]:
            sell_option(option_symbol, half)
            telegram(f"✅ 50% EXIT @ EMA20 → {option_symbol}")
            exited_ema = True

        # Final exit at Upper BB
        if price >= df["UB"].iloc[-1]:
            sell_option(option_symbol, qty - half)
            telegram(f"🎯 FINAL EXIT @ UPPER BB → {option_symbol}")
            break

        time.sleep(30)

# ==========================
# 🚀 MAIN STRATEGY
# ==========================
def run():
    index = "NIFTY"
    index_symbol = "NSE:NIFTY50-INDEX"

    idx = get_candles(index_symbol, "1", 1)
    price = idx["close"].iloc[-1]

    if not htf_check(index_symbol):
        return

    if not ltf_confirm(index_symbol):
        telegram("⚠️ EMA near — waiting for LTF confirmation")
        return

    option_symbol = get_atm_pe(price, index)
    qty = 50

    telegram(f"🟢 BUY ATM PE → {option_symbol}")
    buy_option(option_symbol, qty)

    manage_exit(option_symbol, qty)

# ==========================
# ⏱ SCHEDULER
# ==========================
schedule.every(1).minutes.do(run)
telegram("✅ FYERS PE BUY BOT STARTED")

while True:
    schedule.run_pending()
    time.sleep(1)
