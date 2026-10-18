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
st.title("🚀 Opstra Clone: Pro Strategy Dashboard")

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

# ==========================================
# 3. ADVANCED HELPER FUNCTIONS (MULTI-LEG)
# ==========================================
def get_token_info(symbol, strike_price, inst_type, expiry):
    if inst_type == "FUT":
        filtered_df = df[(df['exch_seg'] == 'NFO') & (df['name'] == symbol) & (df['symbol'].str.endswith('FUT')) & (df['expiry'] == expiry)]
    else:
        filtered_df = df[(df['exch_seg'] == 'NFO') & (df['name'] == symbol) & (df['strike'] == str(strike_price * 100) + '.000000') & (df['symbol'].str.endswith(inst_type)) & (df['expiry'] == expiry)]
    
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
    return round(pop * 100, 2)

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
    "Short Straddle (Sell CE + Sell PE)", 
    "Bullish Hedge (Long FUT + Buy PE)", 
    "Bearish Hedge (Short FUT + Buy CE)"
])

target_strike = st.sidebar.number_input("Strike Price (For Options)", value=25000, step=50)
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

# Strategy Configuration
if "Straddle" in strategy:
    leg1_type, leg1_side = "CE", "SELL"
    leg2_type, leg2_side = "PE", "SELL"
elif "Bullish" in strategy:
    leg1_type, leg1_side = "FUT", "BUY"
    leg2_type, leg2_side = "PE", "BUY"
else:
    leg1_type, leg1_side = "FUT", "SELL"
    leg2_type, leg2_side = "CE", "BUY"

# ==========================================
# 5. MAIN DASHBOARD LOGIC (ANALYSIS & ALGO)
# ==========================================
leg1_token, leg1_symbol = get_token_info("NIFTY", target_strike, leg1_type, target_expiry)
leg2_token, leg2_symbol = get_token_info("NIFTY", target_strike, leg2_type, target_expiry)

if leg1_token and leg2_token:
    
# --- PART 1: PRE-TRADE ANALYSIS ---
    entry1 = smartApi.ltpData("NFO", leg1_symbol, leg1_token)['data']['ltp']
    entry2 = smartApi.ltpData("NFO", leg2_symbol, leg2_token)['data']['ltp']
    current_spot = target_strike # Approximation for center point
    
    # Graph range thoda bada kar diya (4000 points) taaki unlimited profit clear dikhe
    prices = list(range(int(target_strike) - 4000, int(target_strike) + 4000, 10))
    pnl_expiry = []
    pnl_t0 = []
    
    for p in prices:
        pnl1_exp = calc_leg_pnl(p, target_strike, entry1, leg1_type, leg1_side, 0, False)
        pnl2_exp = calc_leg_pnl(p, target_strike, entry2, leg2_type, leg2_side, 0, False)
        pnl_expiry.append((pnl1_exp + pnl2_exp) * lot_size)
        
        pnl1_t0 = calc_leg_pnl(p, target_strike, entry1, leg1_type, leg1_side, days_to_expiry, True)
        pnl2_t0 = calc_leg_pnl(p, target_strike, entry2, leg2_type, leg2_side, days_to_expiry, True)
        pnl_t0.append((pnl1_t0 + pnl2_t0) * lot_size)
        
    st.subheader(f"📊 Pre-Trade Analysis: {strategy}")
    
    max_p = max(pnl_expiry)
    max_l = min(pnl_expiry)
    
    # 👇 SMART UNLIMITED CHECK (Graph ke ends check karega) 👇
    right_diff = pnl_expiry[-1] - pnl_expiry[-2]
    left_diff = pnl_expiry[0] - pnl_expiry[1]
    
    max_profit_str = "Unlimited 🚀" if (right_diff > 1 or left_diff > 1) else f"₹ {round(max_p, 2)}"
    max_loss_str = "Unlimited ⚠️" if (right_diff < -1 or left_diff < -1) else f"₹ {round(max_l, 2)}"
    
    pop_value = calculate_dynamic_pop(prices, pnl_t0, current_spot, days_to_expiry)
    est_margin = (lot_size/25) * 130000 if "Straddle" in strategy else (lot_size/25) * 45000
    
    m_col1, m_col2, m_col3, m_col4 = st.columns(4)
    m_col1.metric("Est. Margin Required", f"₹ {est_margin:,.0f}")
    m_col2.metric("Max Profit (At Expiry)", max_profit_str)
    m_col3.metric("Max Loss (At Expiry)", max_loss_str)
    m_col4.metric("Probability of Profit (POP)", f"{pop_value} %")
    
    fig = go.Figure()
    pnl_profit = [p if p >= 0 else 0 for p in pnl_expiry]
    pnl_loss = [p if p < 0 else 0 for p in pnl_expiry]
    fig.add_trace(go.Scatter(x=prices, y=pnl_profit, mode='none', fill='tozeroy', fillcolor='rgba(0, 128, 0, 0.3)', showlegend=False))
    fig.add_trace(go.Scatter(x=prices, y=pnl_loss, mode='none', fill='tozeroy', fillcolor='rgba(255, 0, 0, 0.3)', showlegend=False))
    fig.add_trace(go.Scatter(x=prices, y=pnl_expiry, mode='lines', name='Expiry Payoff', line=dict(color='blue', dash='dash')))
    fig.add_trace(go.Scatter(x=prices, y=pnl_t0, mode='lines', name='T+0 Payoff (Today)', line=dict(color='darkorange', width=3)))
    fig.update_layout(hovermode="x unified", xaxis_title="Nifty Price", yaxis_title="P&L (₹)", title="Payoff Graph")
    fig.add_vline(x=target_strike, line_dash="dot", line_color="red", annotation_text="Strike")
    fig.add_hline(y=0, line_color="black")
    st.plotly_chart(fig, use_container_width=True)
    
    # --- PART 2: LIVE ALGO EXECUTION ---
    if start_algo:
        st.success("✅ Algo Started & Orders Placed Successfully!")
        st.markdown("---")
        st.subheader("⚡ Live MTM & Strategy Greeks")
        
        col1, col2, col3 = st.columns(3)
        leg1_metric = col1.empty() 
        leg2_metric = col2.empty()
        pnl_metric = col3.empty()
        
        g_col1, g_col2, g_col3 = st.columns(3)
        delta_metric = g_col1.empty()
        theta_metric = g_col2.empty()
        vega_metric = g_col3.empty()
        
        status_msg = st.empty()
        
        leg1_sl_price, leg1_tgt_price = get_exit_prices(entry1, leg1_side, leg_sl_percent, leg_target_percent)
        leg2_sl_price, leg2_tgt_price = get_exit_prices(entry2, leg2_side, leg_sl_percent, leg_target_percent)

        leg1_active = True
        leg2_active = True
        max_pnl_seen = 0 
        
        while True:
            live1 = smartApi.ltpData("NFO", leg1_symbol, leg1_token)['data']['ltp']
            live2 = smartApi.ltpData("NFO", leg2_symbol, leg2_token)['data']['ltp']
            
            pnl = 0
            if leg1_active: pnl += calc_leg_pnl(live1, target_strike, entry1, leg1_type, leg1_side, 0) * lot_size
            if leg2_active: pnl += calc_leg_pnl(live2, target_strike, entry2, leg2_type, leg2_side, 0) * lot_size
            
            d1, t1, v1 = get_greeks(target_strike, target_strike, days_to_expiry, leg1_type, leg1_side)
            d2, t2, v2 = get_greeks(target_strike, target_strike, days_to_expiry, leg2_type, leg2_side)
            
            leg1_metric.metric(label=f"Leg 1 ({leg1_type}) Live", value=f"₹ {live1}")
            leg2_metric.metric(label=f"Leg 2 ({leg2_type}) Live", value=f"₹ {live2}")
            pnl_metric.metric(label="Total MTM P&L", value=f"₹ {round(pnl, 2)}", delta=round(pnl, 2))
            
            delta_metric.metric(label="Total Delta", value=round(d1 + d2, 2))
            theta_metric.metric(label="Total Theta", value=f"₹ {round((t1 + t2) * lot_size, 2)} / day")
            vega_metric.metric(label="Total Vega", value=round(v1 + v2, 2))
            
            # Trailing SL Check
            if pnl > max_pnl_seen: max_pnl_seen = pnl
            if max_pnl_seen >= tsl_activation:
                dynamic_sl = max_pnl_seen - tsl_trail_by
                if pnl <= dynamic_sl:
                    status_msg.error(f"🛡️ TRAILING SL HIT! Protected Profit at ₹{round(pnl, 2)}. Squaring off...")
                    if leg1_active: place_order_api(leg1_symbol, leg1_token, lot_size, "SELL" if leg1_side=="BUY" else "BUY")
                    if leg2_active: place_order_api(leg2_symbol, leg2_token, lot_size, "SELL" if leg2_side=="BUY" else "BUY")
                    break

            # Smart Exits & Rolling Adjustments
            if "Straddle" in strategy:
                # Rolling only applied to Straddles for now
                if leg1_active:
                    hit_sl, hit_tgt = check_exit(live1, leg1_side, leg1_sl_price, leg1_tgt_price)
                    if hit_sl:
                        st.toast(f"⚠️ {leg1_type} SL Hit! Adjusting...")
                        place_order_api(leg1_symbol, leg1_token, lot_size, "BUY")
                        leg1_active = False 
                        if leg2_active:
                            place_order_api(leg2_symbol, leg2_token, lot_size, "BUY")
                            leg2_active = False
                        
                        new_strike = target_strike + 500
                        new_token, new_symbol = get_token_info("NIFTY", new_strike, "PE", target_expiry)
                        if new_token:
                            place_order_api(new_symbol, new_token, lot_size, "SELL")
                            leg2_active = True
                            leg2_symbol = new_symbol
                            leg2_token = new_token
                            live_new = smartApi.ltpData("NFO", leg2_symbol, leg2_token)['data']['ltp']
                            leg2_sl_price, leg2_tgt_price = get_exit_prices(live_new, "SELL", leg_sl_percent, leg_target_percent)
                    elif hit_tgt:
                        place_order_api(leg1_symbol, leg1_token, lot_size, "BUY")
                        leg1_active = False 

                if leg2_active:
                    hit_sl, hit_tgt = check_exit(live2, leg2_side, leg2_sl_price, leg2_tgt_price)
                    if hit_sl:
                        st.toast(f"⚠️ {leg2_type} SL Hit! Adjusting...")
                        place_order_api(leg2_symbol, leg2_token, lot_size, "BUY")
                        leg2_active = False 
                        if leg1_active:
                            place_order_api(leg1_symbol, leg1_token, lot_size, "BUY")
                            leg1_active = False
                        
                        new_strike = target_strike - 500 
                        new_token, new_symbol = get_token_info("NIFTY", new_strike, "CE", target_expiry)
                        if new_token:
                            place_order_api(new_symbol, new_token, lot_size, "SELL")
                            leg1_active = True
                            leg1_symbol = new_symbol
                            leg1_token = new_token
                            live_new = smartApi.ltpData("NFO", leg1_symbol, leg1_token)['data']['ltp']
                            leg1_sl_price, leg1_tgt_price = get_exit_prices(live_new, "SELL", leg_sl_percent, leg_target_percent)
                    elif hit_tgt:
                        place_order_api(leg2_symbol, leg2_token, lot_size, "BUY")
                        leg2_active = False 

            else:
                # Normal SL/Target Exits for Hedged Futures
                if leg1_active:
                    hit_sl, hit_tgt = check_exit(live1, leg1_side, leg1_sl_price, leg1_tgt_price)
                    if hit_sl or hit_tgt:
                        st.toast(f"🔔 {leg1_type} Hit Target/SL!")
                        place_order_api(leg1_symbol, leg1_token, lot_size, "SELL" if leg1_side=="BUY" else "BUY")
                        leg1_active = False
                
                if leg2_active:
                    hit_sl, hit_tgt = check_exit(live2, leg2_side, leg2_sl_price, leg2_tgt_price)
                    if hit_sl or hit_tgt:
                        st.toast(f"🔔 {leg2_type} Hit Target/SL!")
                        place_order_api(leg2_symbol, leg2_token, lot_size, "SELL" if leg2_side=="BUY" else "BUY")
                        leg2_active = False
            
            if not leg1_active and not leg2_active:
                status_msg.error("🛑 Both legs squared off. Algo stopped.")
                break
                
            # Total Max Loss Check
            if pnl <= max_loss:
                status_msg.error(f"⚠️ TOTAL MAX LOSS HIT! (-₹{abs(round(pnl,2))}) Squaring off all...")
                if leg1_active: place_order_api(leg1_symbol, leg1_token, lot_size, "SELL" if leg1_side=="BUY" else "BUY")
                if leg2_active: place_order_api(leg2_symbol, leg2_token, lot_size, "SELL" if leg2_side=="BUY" else "BUY")
                break
                
            time.sleep(1)
            
else:
    st.warning("⚠️ Token nahi mila. Kripya Expiry Date check karein (Jaise: 29DEC2026).")
