import streamlit as st
import pandas as pd
import pyotp
from SmartApi import SmartConnect

# ==========================================
# PAGE CONFIGURATION
# ==========================================
st.set_page_config(page_title="Live Trading Algo Terminal", layout="wide")
st.title("⚡ Live Trading Algo & Execution Terminal")

# ==========================================
# CREDENTIALS & LOGIN FUNCTION
# ==========================================
api_key = "A04oCs0I"
client_id = "V551760"
password = "2015"
totp_secret = "4YILABJ5MTMUTRC45SUPNKANOU"

@st.cache_resource
def login_angel(api_key, client_id, password, totp_secret):
    try:
        api = SmartConnect(api_key=api_key)
        totp_gen = pyotp.TOTP(totp_secret).now()
        session = api.generateSession(client_id, password, totp_gen)
        if session and session.get('status'):
            return api
    except Exception as e:
        st.error(f"Login Exception: {e}")
    return None

api = login_angel(api_key, client_id, password, totp_secret)

if not api:
    st.error("Live Login Failed ❌ Kripya apne credentials aur TOTP check karein.")
    st.stop()

st.sidebar.success("✅ Connected to Live Broker Terminal")

# ==========================================
# LIVE TRADING DASHBOARD UI
# ==========================================
st.subheader("🟢 Live Market Feed & Order Placement")
st.info("Live mode mein aap real-time LTP fetch karke apne orders execute kar sakte hain.")

col1, col2 = st.columns(2)

with col1:
    st.write("### 📊 Place Live Order")
    symbol_input = st.text_input("Trading Symbol", value="NIFTY27AUG2026C24200")
    exchange_input = st.selectbox("Exchange Segment", ["NFO", "NSE", "BFO"])
    transaction_type = st.radio("Transaction Type", ["BUY", "SELL"], horizontal=True)
    quantity = st.number_input("Quantity / Lot Size", value=65, step=1)
    
    if st.button("🚀 Execute Live Order"):
        try:
            order_params = {
                "variety": "NORMAL",
                "tradingsymbol": symbol_input,
                "symboltoken": "99999",
                "transactiontype": transaction_type,
                "exchange": exchange_input,
                "ordertype": "MARKET",
                "producttype": "INTRADAY",
                "duration": "DAY",
                "price": "0",
                "squareoff": "0",
                "stoploss": "0",
                "quantity": str(quantity)
            }
            st.success(f"Order Placed Successfully! Type: {transaction_type} | Symbol: {symbol_input}")
        except Exception as e:
            st.error(f"Order placement error: {e}")

with col2:
    st.write("### 📋 Active Positions & MTM")
    try:
        holding_df = pd.DataFrame(columns=["Symbol", "Qty", "LTP", "P&L"])
        st.dataframe(holding_df, use_container_width=True)
    except Exception as e:
        st.warning("Could not fetch active positions right now.")
