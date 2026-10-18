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

# ==========================================
# 1. PAGE SETUP
# ==========================================
st.set_page_config(page_title="Opstra Clone", layout="wide")
st.title("🚀 Opstra Clone: Live Algo Dashboard")

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

def get_token_info(symbol, strike_price, option_type, expiry):
    filtered_df = df[(df['exch_seg'] == 'NFO') & 
                     (df['name'] == symbol) & 
                     (df['strike'] == str(strike_price * 100) + '.000000') & 
                     (df['symbol'].str.endswith(option_type)) & 
                     (df['expiry'] == expiry)]
    if not filtered_df.empty:
        return filtered_df.iloc[0]['token'], filtered_df.iloc[0]['symbol']
    return None, None

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

# 👇 OPTION GREEKS CALCULATION 👇
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

# 👇 T+0 PAYOFF KE LIYE OPTION PRICE CALCULATOR 👇
def bs_price(S, K, T_days, opt_type="CE", r=0.10, v=0.15):
    if T_days <= 0:
        return max(0, S - K) if opt_type == "CE" else max(0, K - S)
    T = T_days / 365.0
    d1 = (math.log(S / K) + (r + 0.5 * v**2) * T) / (v * math.sqrt(T))
    d2 = d1 - v * math.sqrt(T)
    def cdf(x): return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0
    if opt_type == "CE": return S * cdf(d1) - K * math.exp(-r * T) * cdf(d2)
    else: return K * math.exp(-r * T) * cdf(-d2) - S * cdf(-d1)

# ==========================================
# 3. SIDEBAR SETTINGS (User Input UI)
# ==========================================
st.sidebar.header("⚙️ Algo Settings")
target_strike = st.sidebar.number_input("Strike Price", value=25000, step=50)
target_expiry = st.sidebar.text_input("Expiry Date", value="29DEC2026")
lot_size = st.sidebar.number_input("Lot Size", value=25)
days_to_expiry = st.sidebar.number_input("Days to Expiry", value=3)

st.sidebar.markdown("---")
st.sidebar.subheader("🛡️ Risk Management")
max_loss = st.sidebar.number_input("Overall Max Loss (₹)", value=-500)
tsl_activation = st.sidebar.number_input("Activate Trailing SL after Profit (₹)", value=500)
tsl_trail_by = st.sidebar.number_input("Trail SL by (₹)", value=200)

st.sidebar.markdown("---")
st.sidebar.subheader("🎯 Leg-Wise Settings")
leg_sl_percent = st.sidebar.number_input("Individual Leg SL (%)", 10, 200, 50, step=10)
leg_target_percent = st.sidebar.number_input("Individual Leg Target (%)", 10, 100, 90, step=10)

start_algo = st.sidebar.button("▶️ START LIVE ALGO")

# ==========================================
# 4. MAIN DASHBOARD LOGIC
# ==========================================
if start_algo:
    ce_token, ce_symbol = get_token_info("NIFTY", target_strike, "CE", target_expiry)
    pe_token, pe_symbol = get_token_info("NIFTY", target_strike, "PE", target_expiry)
    
    if ce_token and pe_token:
        # Initial Prices
        ce_data = smartApi.ltpData("NFO", ce_symbol, ce_token)
        pe_data = smartApi.ltpData("NFO", pe_symbol, pe_token)
        
        entry_ce = ce_data['data']['ltp']
        entry_pe = pe_data['data']['ltp']
        entry_prem = entry_ce + entry_pe
        
        st.success(f"✅ Position Executed! Total Premium Collected: ₹{round(entry_prem, 2)}")
        
        # --- INTERACTIVE GRAPH DRAW KARNA (PLOTLY) ---
        st.subheader("📉 Expiry & T+0 Payoff Graph")
        prices = list(range(int(target_strike) - 2500, int(target_strike) + 2500, 10))
        pnl_expiry = []
        pnl_t0 = []
        
        for p in prices:
            ce_exp = entry_ce - max(0, p - target_strike)
            pe_exp = entry_pe - max(0, target_strike - p)
            pnl_expiry.append((ce_exp + pe_exp) * lot_size)
            
            ce_t0_price = bs_price(p, target_strike, days_to_expiry, "CE")
            pe_t0_price = bs_price(p, target_strike, days_to_expiry, "PE")
            ce_t0_pnl = entry_ce - ce_t0_price
            pe_t0_pnl = entry_pe - pe_t0_price
            pnl_t0.append((ce_t0_pnl + pe_t0_pnl) * lot_size)
            
        fig = go.Figure()
        
        # 1. Profit Area (Green)
        pnl_profit = [p if p >= 0 else 0 for p in pnl_expiry]
        fig.add_trace(go.Scatter(x=prices, y=pnl_profit, mode='none', 
                                 fill='tozeroy', fillcolor='rgba(0, 128, 0, 0.3)', showlegend=False))
                                 
        # 2. Loss Area (Red)
        pnl_loss = [p if p < 0 else 0 for p in pnl_expiry]
        fig.add_trace(go.Scatter(x=prices, y=pnl_loss, mode='none', 
                                 fill='tozeroy', fillcolor='rgba(255, 0, 0, 0.3)', showlegend=False))

        # 3. Expiry Line (Dashed Blue)
        fig.add_trace(go.Scatter(x=prices, y=pnl_expiry, mode='lines', name='Expiry Payoff', 
                                 line=dict(color='blue', dash='dash')))
                                 
        # 4. T+0 Line (Solid Orange)
        fig.add_trace(go.Scatter(x=prices, y=pnl_t0, mode='lines', name='T+0 Payoff (Today)', 
                                 line=dict(color='darkorange', width=3)))
                                 
        fig.update_layout(hovermode="x unified", xaxis_title="Nifty Price", yaxis_title="P&L (₹)",
                          title="Cursor ghumayein aur P&L dekhein (T+0 vs Expiry)")
        fig.add_vline(x=target_strike, line_dash="dot", line_color="red", annotation_text="Strike")
        fig.add_hline(y=0, line_color="black")
        
        st.plotly_chart(fig, use_container_width=True)
        # --- LIVE P&L TRACKER UI ---
        st.markdown("---")
        st.subheader("⚡ Live MTM & Option Greeks")
        
        col1, col2, col3 = st.columns(3)
        ce_metric = col1.empty() 
        pe_metric = col2.empty()
        pnl_metric = col3.empty()
        
        g_col1, g_col2, g_col3 = st.columns(3)
        delta_metric = g_col1.empty()
        theta_metric = g_col2.empty()
        vega_metric = g_col3.empty()
        
        status_msg = st.empty()
        
        # 👇 SL & Target Calculations 👇
        ce_sl_price = entry_ce * (1 + (leg_sl_percent / 100))
        pe_sl_price = entry_pe * (1 + (leg_sl_percent / 100))
        ce_target_price = entry_ce * (1 - (leg_target_percent / 100))
        pe_target_price = entry_pe * (1 - (leg_target_percent / 100))

        ce_active = True
        pe_active = True
        max_pnl_seen = 0 # Trailing SL ke liye variable
        
        # Live Update Loop
        while True:
            live_ce = smartApi.ltpData("NFO", ce_symbol, ce_token)['data']['ltp']
            live_pe = smartApi.ltpData("NFO", pe_symbol, pe_token)['data']['ltp']
            live_prem = live_ce + live_pe
            
            pnl = 0
            if ce_active: pnl += (entry_ce - live_ce) * lot_size
            if pe_active: pnl += (entry_pe - live_pe) * lot_size
            
            ce_delta, ce_theta, ce_vega = black_scholes_greeks(target_strike, target_strike, days_to_expiry, "CE")
            pe_delta, pe_theta, pe_vega = black_scholes_greeks(target_strike, target_strike, days_to_expiry, "PE")
            
            total_delta = ce_delta + pe_delta
            total_theta = ce_theta + pe_theta
            total_vega = ce_vega + pe_vega
            
            ce_metric.metric(label="Call (CE) Live", value=f"₹ {live_ce}")
            pe_metric.metric(label="Put (PE) Live", value=f"₹ {live_pe}")
            pnl_metric.metric(label="Total MTM P&L", value=f"₹ {round(pnl, 2)}", delta=round(pnl, 2))
            
            delta_metric.metric(label="Total Delta", value=round(total_delta, 2))
            theta_metric.metric(label="Total Theta (Time Decay)", value=f"₹ {round(total_theta * lot_size, 2)} / day")
            vega_metric.metric(label="Total Vega (Vol Impact)", value=round(total_vega, 2))
            
            # 👇 SMART TRAILING STOP LOSS (TSL) 👇
            if pnl > max_pnl_seen:
                max_pnl_seen = pnl
                
            if max_pnl_seen >= tsl_activation:
                dynamic_sl = max_pnl_seen - tsl_trail_by
                if pnl <= dynamic_sl:
                    status_msg.error(f"🛡️ TRAILING SL HIT! Protected Profit at ₹{round(pnl, 2)}. Squaring off...")
                    if ce_active: place_exit_order(ce_symbol, ce_token, lot_size)
                    if pe_active: place_exit_order(pe_symbol, pe_token, lot_size)
                    break

            # 👇 SMART AUTO ADJUSTMENT (LEG-WISE SL & TARGET) 👇
            if ce_active:
                if live_ce >= ce_sl_price:
                    st.toast(f"⚠️ CE Stop Loss Hit at ₹{live_ce}!")
                    place_exit_order(ce_symbol, ce_token, lot_size)
                    ce_active = False 
                elif live_ce <= ce_target_price:
                    st.toast(f"🎯 CE Target Hit (90% Profit) at ₹{live_ce}!")
                    place_exit_order(ce_symbol, ce_token, lot_size)
                    ce_active = False 

            if pe_active:
                if live_pe >= pe_sl_price:
                    st.toast(f"⚠️ PE Stop Loss Hit at ₹{live_pe}!")
                    place_exit_order(pe_symbol, pe_token, lot_size)
                    pe_active = False 
                elif live_pe <= pe_target_price:
                    st.toast(f"🎯 PE Target Hit (90% Profit) at ₹{live_pe}!")
                    place_exit_order(pe_symbol, pe_token, lot_size)
                    pe_active = False 
                
            if not ce_active and not pe_active:
                status_msg.error("🛑 Both legs squared off. Algo stopped.")
                break
                
            # Total Max Loss Check
            if pnl <= max_loss:
                status_msg.error(f"⚠️ TOTAL MAX LOSS HIT! (-₹{abs(round(pnl,2))}) Squaring off all...")
                if ce_active: place_exit_order(ce_symbol, ce_token, lot_size)
                if pe_active: place_exit_order(pe_symbol, pe_token, lot_size)
                break
                
            time.sleep(1)
            
    else:
        st.error("❌ Token nahi mila. Kripya Expiry date check karein.")
