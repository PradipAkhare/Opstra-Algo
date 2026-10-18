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
    "Short Straddle (Naked Sell ⚠️)", 
    "Iron Butterfly (Hedged Straddle 🛡️)", 
    "Bullish Hedge (Long FUT + Buy PE)", 
    "Bearish Hedge (Short FUT + Buy CE)",
    "Custom Strategy Builder 🛠️" # 👇 Naya Custom Builder
])

target_strike = st.sidebar.number_input("Center Strike (For Graph)", value=25000, step=50)

# ==========================================
# 5. DYNAMIC LEGS CONFIGURATION
# ==========================================
hedge_dist = 0
est_margin = 0

if "Custom" in strategy:
    st.sidebar.markdown("### 🛠️ Build Your Own Strategy")
    num_legs = st.sidebar.number_input("Kitne Legs chahiye?", min_value=1, max_value=6, value=2)
    legs_config = []
    
    for i in range(num_legs):
        st.sidebar.markdown(f"**Leg {i+1}**")
        c1, c2, c3 = st.sidebar.columns([1.2, 1.2, 1.5])
        l_type = c1.selectbox("Type", ["CE", "PE", "FUT"], key=f"t_{i}")
        l_side = c2.selectbox("Side", ["BUY", "SELL"], key=f"s_{i}")
        l_strike = c3.number_input("Strike", value=target_strike, step=50, key=f"stk_{i}")
        
        # Calculate offset from center strike for the engine
        l_off = l_strike - target_strike
        legs_config.append((l_type, l_side, l_off))
        
        # Rough margin estimate for custom legs
        if l_side == "SELL" and l_type != "FUT": est_margin += (25/25) * 110000
        elif l_side == "SELL" and l_type == "FUT": est_margin += (25/25) * 120000
        else: est_margin += (25/25) * 10000 # Buy legs margin
    est_margin = est_margin * 0.7 # Hedge benefit assumption

elif "Butterfly" in strategy:
    hedge_dist = st.sidebar.number_input("Hedge OTM Distance (Buy Options)", value=500, step=50)
    legs_config = [("CE", "SELL", 0), ("PE", "SELL", 0), ("CE", "BUY", hedge_dist), ("PE", "BUY", -hedge_dist)]
    est_margin = 55000 
elif "Straddle" in strategy:
    legs_config = [("CE", "SELL", 0), ("PE", "SELL", 0)]
    est_margin = 130000
elif "Bullish" in strategy:
    legs_config = [("FUT", "BUY", 0), ("PE", "BUY", 0)]
    est_margin = 45000
else:
    legs_config = [("FUT", "SELL", 0), ("CE", "BUY", 0)]
    est_margin = 45000

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

# Multiply base margin estimate by lots
est_margin = (lot_size/25) * est_margin

# ==========================================
# 6. MAIN DASHBOARD LOGIC 
# ==========================================
leg_data = []
all_tokens_found = True

for l_type, l_side, l_off in legs_config:
    l_strike = target_strike + l_off
    tok, sym = get_token_info("NIFTY", l_strike, l_type, target_expiry)
    if tok:
        leg_data.append({"type": l_type, "side": l_side, "strike": l_strike, "token": tok, "symbol": sym, "active": True})
    else:
        all_tokens_found = False

if all_tokens_found:
    # --- PART 1: PRE-TRADE ANALYSIS ---
    for leg in leg_data:
        leg["entry"] = smartApi.ltpData("NFO", leg["symbol"], leg["token"])['data']['ltp']
        leg["sl"], leg["tgt"] = get_exit_prices(leg["entry"], leg["side"], leg_sl_percent, leg_target_percent)
        
    current_spot = target_strike 
    prices = list(range(int(target_strike) - 4000, int(target_strike) + 4000, 10))
    pnl_expiry = []
    pnl_t0 = []
    
    for p in prices:
        exp_val = 0
        t0_val = 0
        for leg in leg_data:
            exp_val += calc_leg_pnl(p, leg["strike"], leg["entry"], leg["type"], leg["side"], 0, False)
            t0_val += calc_leg_pnl(p, leg["strike"], leg["entry"], leg["type"], leg["side"], days_to_expiry, True)
        pnl_expiry.append(exp_val * lot_size)
        pnl_t0.append(t0_val * lot_size)
        
    st.subheader(f"📊 Pre-Trade Analysis: {strategy}")
    
    max_p = max(pnl_expiry)
    max_l = min(pnl_expiry)
    
    # 👇 SMART UNLIMITED CHECK (Graph ke ends check karega) 👇
    right_diff = pnl_expiry[-1] - pnl_expiry[-2]
    left_diff = pnl_expiry[0] - pnl_expiry[1]
    
    max_profit_str = "Unlimited 🚀" if (right_diff > 1 or left_diff > 1) else f"₹ {round(max_p, 2)}"
    max_loss_str = "Unlimited ⚠️" if (right_diff < -1 or left_diff < -1) else f"₹ {round(max_l, 2)}"
    
    pop_value = calculate_dynamic_pop(prices, pnl_t0, current_spot, days_to_expiry)
    
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
        
        cols = st.columns(len(leg_data))
        leg_metrics = [cols[i].empty() for i in range(len(leg_data))]
        
        st.markdown("<br>", unsafe_allow_html=True)
        g_col1, g_col2, g_col3, g_col4 = st.columns(4)
        pnl_metric = g_col1.empty()
        delta_metric = g_col2.empty()
        theta_metric = g_col3.empty()
        vega_metric = g_col4.empty()
        status_msg = st.empty()
        
        max_pnl_seen = 0 
        
        while True:
            pnl = 0
            tot_d, tot_t, tot_v = 0, 0, 0
            
            for i, leg in enumerate(leg_data):
                if not leg["active"]:
                    leg_metrics[i].metric(label=f"🔴 {leg['side']} {leg['strike']} {leg['type']}", value="Closed")
                    continue
                    
                leg["live"] = smartApi.ltpData("NFO", leg["symbol"], leg["token"])['data']['ltp']
                pnl += calc_leg_pnl(leg["live"], leg["strike"], leg["entry"], leg["type"], leg["side"], 0) * lot_size
                
                d, t, v = get_greeks(target_strike, leg["strike"], days_to_expiry, leg["type"], leg["side"])
                tot_d += d; tot_t += t; tot_v += v
                
                leg_metrics[i].metric(label=f"🟢 {leg['side']} {leg['strike']} {leg['type']}", value=f"₹ {leg['live']}")
                
            pnl_metric.metric(label="Total MTM P&L", value=f"₹ {round(pnl, 2)}", delta=round(pnl, 2))
            delta_metric.metric(label="Total Delta", value=round(tot_d, 2))
            theta_metric.metric(label="Total Theta", value=f"₹ {round(tot_t * lot_size, 2)} / day")
            vega_metric.metric(label="Total Vega", value=round(tot_v, 2))
            
            if pnl > max_pnl_seen: max_pnl_seen = pnl
            if max_pnl_seen >= tsl_activation:
                dynamic_sl = max_pnl_seen - tsl_trail_by
                if pnl <= dynamic_sl:
                    status_msg.error(f"🛡️ TRAILING SL HIT! Protected Profit at ₹{round(pnl, 2)}. Squaring off all...")
                    for leg in leg_data:
                        if leg["active"]: place_order_api(leg["symbol"], leg["token"], lot_size, "SELL" if leg["side"]=="BUY" else "BUY")
                    break

            if "Naked Sell" in strategy:
                ce_leg = leg_data[0]
                pe_leg = leg_data[1]
                
                if ce_leg["active"]:
                    if ce_leg["live"] >= ce_leg["sl"]:
                        st.toast(f"⚠️ CE Stop Loss Hit! Adjusting...")
                        place_order_api(ce_leg["symbol"], ce_leg["token"], lot_size, "BUY")
                        ce_leg["active"] = False 
                        if pe_leg["active"]:
                            place_order_api(pe_leg["symbol"], pe_leg["token"], lot_size, "BUY")
                            pe_leg["active"] = False
                        
                        new_strike = target_strike + 500
                        new_token, new_symbol = get_token_info("NIFTY", new_strike, "PE", target_expiry)
                        if new_token:
                            place_order_api(new_symbol, new_token, lot_size, "SELL")
                            pe_leg["active"] = True
                            pe_leg["symbol"] = new_symbol
                            pe_leg["token"] = new_token
                            pe_leg["strike"] = new_strike
                            pe_leg["live"] = smartApi.ltpData("NFO", new_symbol, new_token)['data']['ltp']
                            pe_leg["sl"], pe_leg["tgt"] = get_exit_prices(pe_leg["live"], "SELL", leg_sl_percent, leg_target_percent)
                    elif ce_leg["live"] <= ce_leg["tgt"]:
                        place_order_api(ce_leg["symbol"], ce_leg["token"], lot_size, "BUY")
                        ce_leg["active"] = False 

                if pe_leg["active"]:
                    if pe_leg["live"] >= pe_leg["sl"]:
                        st.toast(f"⚠️ PE Stop Loss Hit! Adjusting...")
                        place_order_api(pe_leg["symbol"], pe_leg["token"], lot_size, "BUY")
                        pe_leg["active"] = False 
                        if ce_leg["active"]:
                            place_order_api(ce_leg["symbol"], ce_leg["token"], lot_size, "BUY")
                            ce_leg["active"] = False
                        
                        new_strike = target_strike - 500 
                        new_token, new_symbol = get_token_info("NIFTY", new_strike, "CE", target_expiry)
                        if new_token:
                            place_order_api(new_symbol, new_token, lot_size, "SELL")
                            ce_leg["active"] = True
                            ce_leg["symbol"] = new_symbol
                            ce_leg["token"] = new_token
                            ce_leg["strike"] = new_strike
                            ce_leg["live"] = smartApi.ltpData("NFO", new_symbol, new_token)['data']['ltp']
                            ce_leg["sl"], ce_leg["tgt"] = get_exit_prices(ce_leg["live"], "SELL", leg_sl_percent, leg_target_percent)
                    elif pe_leg["live"] <= pe_leg["tgt"]:
                        place_order_api(pe_leg["symbol"], pe_leg["token"], lot_size, "BUY")
                        pe_leg["active"] = False 
            else:
                all_closed = True
                for leg in leg_data:
                    if leg["active"]:
                        all_closed = False
                        hit_sl, hit_tgt = check_exit(leg["live"], leg["side"], leg["sl"], leg["tgt"])
                        if hit_sl or hit_tgt:
                            st.toast(f"🔔 {leg['strike']} {leg['type']} Hit Target/SL!")
                            place_order_api(leg["symbol"], leg["token"], lot_size, "SELL" if leg["side"]=="BUY" else "BUY")
                            leg["active"] = False
                if all_closed:
                    status_msg.error("🛑 All legs squared off. Algo stopped.")
                    break
                
            if pnl <= max_loss:
                status_msg.error(f"⚠️ TOTAL MAX LOSS HIT! (-₹{abs(round(pnl,2))}) Squaring off all...")
                for leg in leg_data:
                    if leg["active"]: place_order_api(leg["symbol"], leg["token"], lot_size, "SELL" if leg["side"]=="BUY" else "BUY")
                break
                
            time.sleep(1)
            
else:
    st.warning("⚠️ Koi ek Token nahi mila. Kripya Expiry Date check karein (Jaise: 29DEC2026) ya Strike badlein.")
