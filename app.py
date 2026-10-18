import streamlit as st
import pandas as pd
import json
import time
import os
import requests
import plotly.graph_objects as go
from SmartApi import SmartConnect
import pyotp
import math
import random

# ==========================================
# 1. PAGE SETUP
# ==========================================
st.set_page_config(page_title="Opstra Clone", layout="wide")
st.title("🚀 Opstra Clone: Universal Pro Dashboard")

# ==========================================
# 2. LOGIN DETAILS
# ==========================================
api_key = "A04oCs0I"
client_id = "V551760"
password = "2015" 
totp_secret = "4YILABJ5MTMUTRC45SUPNKANOU"

@st.cache_resource
def login_angel():
    smartApi = SmartConnect(api_key=api_key)
    try:
        totp = pyotp.TOTP(totp_secret).now()
        data = smartApi.generateSession(client_id, password, totp)
        if data['status']:
            return smartApi
    except Exception as e:
        pass
    return None

@st.cache_data(ttl=86400)
def get_instrument_df():
    url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
    response = requests.get(url)
    return pd.DataFrame(response.json())

smartApi = login_angel()
if smartApi is None:
    st.error("Login Failed ❌ Kripya apni API aur TOTP details check karein.")
    st.stop()

st.sidebar.success("✅ Login Successful!")
df = get_instrument_df()

# 👇 AUTOCOMPLETE SUGGESTION KE LIYE SARE SYMBOLS NIKALNA 👇
fno_mcx_df = df[(df['exch_seg'] == 'NFO') | (df['exch_seg'] == 'MCX')]
unique_symbols = sorted(fno_mcx_df['name'].dropna().unique().tolist())
default_symbol_idx = unique_symbols.index("NIFTY") if "NIFTY" in unique_symbols else 0

# ==========================================
# 3. ADVANCED HELPER FUNCTIONS (MULTI-LEG)
# ==========================================
def get_token_info(symbol, strike_price, inst_type, expiry):
    # 👇 BUG FIXED: Robust numeric matching for API formats 👇
    filtered_df = df[((df['exch_seg'] == 'NFO') | (df['exch_seg'] == 'MCX')) & 
                     (df['name'] == symbol) & 
                     (df['expiry'] == expiry)].copy()
    
    if inst_type == "FUT":
        filtered_df = filtered_df[filtered_df['symbol'].str.endswith('FUT')]
    else:
        filtered_df['numeric_strike'] = pd.to_numeric(filtered_df['strike'], errors='coerce') / 100
        filtered_df = filtered_df[(filtered_df['numeric_strike'] == float(strike_price)) & 
                                  (filtered_df['symbol'].str.endswith(inst_type))]
    
    if not filtered_df.empty:
        return filtered_df.iloc[0]['token'], filtered_df.iloc[0]['symbol']
    return None, None

def place_order_api(symbol, token, qty, transaction_type):
    try:
        orderparams = {
            "variety": "NORMAL", "tradingsymbol": symbol, "symboltoken": token,
            "transactiontype": transaction_type, "exchange": "NFO", "ordertype": "MARKET",
            "producttype": "CARRYFORWARD", "duration": "DAY", "quantity": qty
        }
        orderId = smartApi.placeOrder(orderparams)
        return orderId
    except Exception as e:
        return f"Error: {e}"

def black_scholes_greeks(S, K, T_days, opt_type="CE", r=0.10, v=0.15):
    T = max(T_days / 365.0, 0.001) 
    d1 = (math.log(S / K) + (r + 0.5 * v**2) * T) / (v * math.sqrt(T))
    d2 = d1 - v * math.sqrt(T)
    def cdf(x): return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0
    def pdf(x): return math.exp(-0.5 * x**2) / math.sqrt(2 * math.pi)
    
    if opt_type == "CE":
        delta = cdf(d1)
        theta = -(S * pdf(d1) * v) / (2 * math.sqrt(T)) - r * K * math.exp(-r * T) * cdf(d2)
    else:
        delta = cdf(d1) - 1
        theta = -(S * pdf(d1) * v) / (2 * math.sqrt(T)) + r * K * math.exp(-r * T) * cdf(-d2)
    vega = (S * pdf(d1) * math.sqrt(T)) / 100
    return round(delta, 2), round(theta / 365, 2), round(vega, 2)

def bs_price(S, K, T_days, opt_type="CE", r=0.10, v=0.15):
    if T_days <= 0: return max(0, S - K) if opt_type == "CE" else max(0, K - S)
    T = max(T_days / 365.0, 0.001)
    d1 = (math.log(S / K) + (r + 0.5 * v**2) * T) / (v * math.sqrt(T))
    d2 = d1 - v * math.sqrt(T)
    def cdf(x): return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0
    if opt_type == "CE": return S * cdf(d1) - K * math.exp(-r * T) * cdf(d2)
    else: return K * math.exp(-r * T) * cdf(-d2) - S * cdf(-d1)

def calc_leg_pnl(S, K, entry_price, inst_type, side, T_days, is_t0=False):
    if inst_type == "FUT": current_val = S
    else:
        if is_t0 and T_days > 0: current_val = bs_price(S, K, T_days, inst_type)
        else: current_val = max(0, S - K) if inst_type == "CE" else max(0, K - S)
    return (current_val - entry_price) if side == "BUY" else (entry_price - current_val)

def get_greeks(S, K, T_days, inst_type, side):
    if inst_type == "FUT": return (1.0 if side == "BUY" else -1.0), 0.0, 0.0
    d, t, v = black_scholes_greeks(S, K, T_days, inst_type)
    if side == "SELL": return -d, -t, -v
    return d, t, v

def calculate_dynamic_pop(prices, pnl_array, current_spot, days_to_expiry, v=0.15):
    T = max(days_to_expiry / 365.0, 0.001)
    pop = 0.0
    def cdf(x): return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0
    for i in range(len(prices)-1):
        if pnl_array[i] > 0:
            z1 = math.log(prices[i] / current_spot) / (v * math.sqrt(T))
            z2 = math.log(prices[i+1] / current_spot) / (v * math.sqrt(T))
            pop += (cdf(z2) - cdf(z1))
    return min(round(pop * 100, 2), 100.0)

def get_exit_prices(entry, side, sl_pct, tgt_pct):
    if side == "BUY": return entry * (1 - (sl_pct / 100)), entry * (1 + (tgt_pct / 100))
    else: return entry * (1 + (sl_pct / 100)), entry * (1 - (tgt_pct / 100))

def check_exit(live_price, side, sl_price, tgt_price):
    if side == "BUY": return live_price <= sl_price, live_price >= tgt_price
    else: return live_price >= sl_price, live_price <= tgt_price

# ==========================================
# 4. SIDEBAR SETTINGS (User Input UI)
# ==========================================
st.sidebar.header("⚙️ Algo Settings")
strategy = st.sidebar.selectbox("📈 Select Strategy", [
    "Option Chain Builder ⛓️", 
    "Custom Strategy Builder 🛠️", 
    "Short Straddle (Naked Sell ⚠️)", 
    "Iron Butterfly (Hedged Straddle 🛡️)", 
    "Bullish Hedge (Long FUT + Buy PE)", 
    "Bearish Hedge (Short FUT + Buy CE)"
])

st.sidebar.markdown("### 🔍 Asset Settings")

symbol_name = st.sidebar.selectbox(
    "🔍 Search F&O Symbol (Type to Search)", 
    options=unique_symbols, 
    index=default_symbol_idx
).upper()

# 👇 SMART DYNAMIC DEFAULTS BASED ON SYMBOL 👇
symbol_df_base = fno_mcx_df[fno_mcx_df['name'] == symbol_name]

if not symbol_df_base.empty:
    unique_expiries = symbol_df_base['expiry'].unique().tolist()
    try:
        unique_expiries = sorted(unique_expiries, key=lambda x: pd.to_datetime(x))
    except:
        pass
    
    symbol_df_ce = symbol_df_base[symbol_df_base['symbol'].str.endswith('CE')]
    if not symbol_df_ce.empty:
