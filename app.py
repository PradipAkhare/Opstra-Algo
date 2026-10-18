import streamlit as st
import pandas as pd
import json
import time
import os
import requests
import matplotlib.pyplot as plt
from SmartApi import SmartConnect
import pyotp
import math

# 1. Page Setup (Website ki chaudaai aur title)
st.set_page_config(page_title="Opstra Clone", layout="wide")
st.title("🚀 Opstra Clone: Live Algo Dashboard")

# ==========================================
# 2. LOGIN DETAILS (Yahan apni details daalein)
# ==========================================
api_key = "A04oCs0I"
client_id = "V551760"
password = "2015" 
totp_secret = "4YILABJ5MTMUTRC45SUPNKANOU"

# Streamlit Caching: Taaki baar-baar login na karna pade
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

@st.cache_data(ttl=86400) # Har 24 ghante mein naya data layega
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

def get_token_info(symbol, strike_price, option_type, expiry):
    filtered_df = df[(df['exch_seg'] == 'NFO') & 
                     (df['name'] == symbol) & 
                     (df['strike'] == str(strike_price * 100) + '.000000') & 
                     (df['symbol'].str.endswith(option_type)) & 
                     (df['expiry'] == expiry)]
    if not filtered_df.empty:
        return filtered_df.iloc[0]['token'], filtered_df.iloc[0]['symbol']
    return None, None
def get_token_info(symbol, strike_price, option_type, expiry):
    filtered_df = df[(df['exch_seg'] == 'NFO') & 
                     (df['name'] == symbol) & 
                     (df['strike'] == str(strike_price * 100) + '.000000') & 
                     (df['symbol'].str.endswith(option_type)) & 
                     (df['expiry'] == expiry)]
    if not filtered_df.empty:
        return filtered_df.iloc[0]['token'], filtered_df.iloc[0]['symbol']
    return None, None

# 👇 NAYA FUNCTION YAHAN PASTE KARNA HAI 👇
def place_exit_order(symbol, token, qty, transaction_type="BUY"):
    try:
        orderparams = {
            "variety": "NORMAL",
            "tradingsymbol": symbol,
            "symboltoken": token,
            "transactiontype": transaction_type, 
            "exchange": "NFO",
            "ordertype": "MARKET",
            "producttype": "CARRYFORWARD", 
            "duration": "DAY",
            "quantity": qty
        }
        orderId = smartApi.placeOrder(orderparams)
        return orderId
    except Exception as e:
        return f"Error: {e}"
# 👇 OPTION GREEKS CALCULATION (BLACK-SCHOLES) 👇
def black_scholes_greeks(S, K, T_days, opt_type="CE", r=0.10, v=0.15):
    # S = Spot Price, K = Strike, T = Time to expiry, r = Interest Rate, v = Volatility
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
# ==========================================
# 3. SIDEBAR SETTINGS (User Input UI)
# ==========================================
st.sidebar.header("⚙️ Algo Settings")
target_strike = st.sidebar.number_input("Strike Price", value=25000, step=50)
target_expiry = st.sidebar.text_input("Expiry Date", value="29DEC2026")
lot_size = st.sidebar.number_input("Lot Size", value=25)
target_profit = st.sidebar.number_input("Target Profit (₹)", value=1000)
max_loss = st.sidebar.number_input("Max Loss (₹)", value=-500)
days_to_expiry = st.sidebar.number_input("Days to Expiry", value=3)
start_algo = st.sidebar.button("▶️ START LIVE ALGO")

# ==========================================
# 4. MAIN DASHBOARD LOGIC
# ==========================================
if start_algo:
    ce_token, ce_symbol = get_token_info("NIFTY", target_strike, "CE", target_expiry)
    pe_token, pe_symbol = get_token_info("NIFTY", target_strike, "PE", target_expiry)
    
    if ce_token and pe_token:
        # Shuruati Price
        ce_data = smartApi.ltpData("NFO", ce_symbol, ce_token)
        pe_data = smartApi.ltpData("NFO", pe_symbol, pe_token)
        
        entry_ce = ce_data['data']['ltp']
        entry_pe = pe_data['data']['ltp']
        entry_prem = entry_ce + entry_pe
        
        st.success(f"✅ Position Executed! Total Premium Collected: ₹{round(entry_prem, 2)}")
        
        # --- GRAPH DRAW KARNA ---
        st.subheader("📉 Expiry Payoff Graph")
        prices = range(int(target_strike) - 2500, int(target_strike) + 2500, 10)
        pnl_list = []
        for p in prices:
            ce_pnl = entry_ce - max(0, p - target_strike)
            pe_pnl = entry_pe - max(0, target_strike - p)
            pnl_list.append((ce_pnl + pe_pnl) * lot_size)
            
        fig, ax = plt.subplots(figsize=(10,4))
        ax.plot(prices, pnl_list, color='blue', linewidth=2)
        ax.axhline(0, color='black', linestyle='--')
        ax.axvline(target_strike, color='green', linestyle=':', label="Strike")
        ax.fill_between(prices, pnl_list, 0, where=[p >= 0 for p in pnl_list], color='green', alpha=0.5)
        ax.fill_between(prices, pnl_list, 0, where=[p < 0 for p in pnl_list], color='red', alpha=0.5)
        ax.set_xlabel("Nifty Price")
        ax.set_ylabel("P&L (₹)")
        st.pyplot(fig) # Graph ko website par dikhana
        
        # --- LIVE P&L TRACKER UI ---
        st.markdown("---")
        st.subheader("⚡ Live MTM & Option Greeks")
        
        # Upar ke 3 dabbe (Prices & PnL)
        col1, col2, col3 = st.columns(3)
        ce_metric = col1.empty() 
        pe_metric = col2.empty()
        pnl_metric = col3.empty()
        
        # Neeche ke 3 dabbe (Greeks)
        g_col1, g_col2, g_col3 = st.columns(3)
        delta_metric = g_col1.empty()
        theta_metric = g_col2.empty()
        vega_metric = g_col3.empty()
        
        status_msg = st.empty()
        
        # Loop for live updates
        while True:
            live_ce = smartApi.ltpData("NFO", ce_symbol, ce_token)['data']['ltp']
            live_pe = smartApi.ltpData("NFO", pe_symbol, pe_token)['data']['ltp']
            live_prem = live_ce + live_pe
            pnl = (entry_prem - live_prem) * lot_size
            
            # Greeks Calculate karna (Nifty Strike ko Spot Price maan kar)
            ce_delta, ce_theta, ce_vega = black_scholes_greeks(target_strike, target_strike, days_to_expiry, "CE")
            pe_delta, pe_theta, pe_vega = black_scholes_greeks(target_strike, target_strike, days_to_expiry, "PE")
            
            total_delta = ce_delta + pe_delta
            total_theta = ce_theta + pe_theta
            total_vega = ce_vega + pe_vega
            
            # Website par live dabbe update karna
            ce_metric.metric(label="Call (CE) Live", value=f"₹ {live_ce}")
            pe_metric.metric(label="Put (PE) Live", value=f"₹ {live_pe}")
            pnl_metric.metric(label="Total MTM P&L", value=f"₹ {round(pnl, 2)}", delta=round(pnl, 2))
            
            # Website par Greeks update karna
            delta_metric.metric(label="Total Delta (Neutral is 0)", value=round(total_delta, 2))
            theta_metric.metric(label="Total Theta (Time Decay)", value=f"₹ {round(total_theta * lot_size, 2)} / day")
            vega_metric.metric(label="Total Vega (Vol Impact)", value=round(total_vega, 2))
            
            # 👇 RISK MANAGEMENT (AUTO EXIT WITH REAL ORDERS) 👇
            if pnl >= target_profit:
                status_msg.success(f"🎉 TARGET HIT! (+₹{round(pnl,2)}) Auto-squaring off...")
                place_exit_order(ce_symbol, ce_token, lot_size) 
                place_exit_order(pe_symbol, pe_token, lot_size) 
                st.balloons() 
                break
                
            elif pnl <= max_loss:
                status_msg.error(f"⚠️ STOP LOSS HIT! (-₹{abs(round(pnl,2))}) Auto-squaring off...")
                place_exit_order(ce_symbol, ce_token, lot_size)
                place_exit_order(pe_symbol, pe_token, lot_size)
                break
                
            time.sleep(1)
            
    else:
        st.error("❌ Token nahi mila. Kripya Expiry date check karein.")