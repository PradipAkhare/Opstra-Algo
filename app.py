import streamlit as st, pandas as pd, math, time, requests, datetime, pyotp
import plotly.graph_objects as go
from SmartApi import SmartConnect

# ==========================================
# 1. PAGE SETUP & LOGIN (WIDE MODE + CSS)
# ==========================================
st.set_page_config(page_title="Opstra Clone", layout="wide")

st.markdown("""
    <style>
    .block-container { max-width: 98% !important; padding-top: 1rem; padding-bottom: 1rem; }
    dataframe { width: 100% !important; }
    </style>
""", unsafe_allow_html=True)

st.title("🚀 Opstra Clone: Universal Pro Dashboard + Frozen Historical Backtest")

api_key, client_id, password, totp_secret = "A04oCs0I", "V551760", "2015", "4YILABJ5MTMUTRC45SUPNKANOU"

@st.cache_resource
def login_angel():
    api = SmartConnect(api_key=api_key)
    try:
        if api.generateSession(client_id, password, pyotp.TOTP(totp_secret).now())['status']: return api
    except: pass
    return None

@st.cache_data(ttl=86400)
def get_df(): return pd.DataFrame(requests.get("https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json").json())

api = login_angel()
if not api: st.error("Login Failed ❌ Kripya API details check karein."); st.stop()
st.sidebar.success("✅ Login Successful!")

df = get_df()
fno_df = df[df['exch_seg'].isin(['NFO', 'MCX', 'BFO'])]
unique_syms = sorted(fno_df['name'].dropna().unique())
def_idx = unique_syms.index("NIFTY") if "NIFTY" in unique_syms else 0

# ==========================================
# 2. HELPER FUNCTIONS
# ==========================================
def parse_exp(d):
    try: return pd.to_datetime(str(d))
    except: return pd.Timestamp.max

def get_token(sym, stk, typ, exp):
    if typ == "FUT": 
        f = fno_df[(fno_df['name']==sym) & (fno_df['symbol'].str.endswith('FUT'))].copy()
        if f.empty: return None, None, None
        f['exp_date'] = f['expiry'].apply(parse_exp)
        v_futs = f[f['exp_date'] >= parse_exp(exp)].sort_values('exp_date')
        f_tgt = v_futs if not v_futs.empty else f.sort_values('exp_date')
        return f_tgt.iloc[0]['token'], f_tgt.iloc[0]['symbol'], f_tgt.iloc[0]['exch_seg']
    else:
        f = fno_df[(fno_df['name']==sym) & (fno_df['expiry']==exp) & (fno_df['symbol'].str.endswith(typ))].copy()
        if f.empty: return None, None, None
        f['num_stk'] = pd.to_numeric(f['strike'], errors='coerce')
        f['diff'] = f['num_stk'].apply(lambda x: min(abs(x-float(stk)), abs((x/100)-float(stk)), abs((x/10000)-float(stk))))
        f = f.sort_values('diff')
        return f.iloc[0]['token'], f.iloc[0]['symbol'], f.iloc[0]['exch_seg']

def safe_ltp(exch, sym, tok):
    try:
        res = api.ltpData(exch, sym, tok)
        if res and 'data' in res and 'ltp' in res['data']:
            return float(res['data']['ltp'])
    except: pass
    return 100.0

def place_order(sym, tok, qty, side, exch="NFO"):
    try: return api.placeOrder({"variety":"NORMAL","tradingsymbol":sym,"symboltoken":tok,"transactiontype":side,"exchange":exch,"ordertype":"MARKET","producttype":"CARRYFORWARD","duration":"DAY","quantity":qty})
    except Exception as e: return str(e)

def bs_greeks(S, K, T, typ="CE", r=0.10, v=0.15):
    if S <= 0 or K <= 0: return 0.0, 0.0, 0.0
    T = max(T/365.0, 0.001)
    d1 = (math.log(S/K)+(r+0.5*v**2)*T)/(v*math.sqrt(T)); d2 = d1-v*math.sqrt(T)
    cdf = lambda x: (1.0+math.erf(x/math.sqrt(2.0)))/2.0
    pdf = lambda x: math.exp(-0.5*x**2)/math.sqrt(2*math.pi)
    if typ=="CE": return cdf(d1), -(S*pdf(d1)*v)/(2*math.sqrt(T))-r*K*math.exp(-r*T)*cdf(d2), (S*pdf(d1)*math.sqrt(T))/100
    return cdf(d1)-1, -(S*pdf(d1)*v)/(2*math.sqrt(T))+r*K*math.exp(-r*T)*cdf(-d2), (S*pdf(d1)*math.sqrt(T))/100

def bs_price(S, K, T, typ="CE", r=0.10, v=0.15):
    if S <= 0 or K <= 0: return 0.0
    if T<=0: return max(0, S-K) if typ=="CE" else max(0, K-S)
    T = max(T/365.0, 0.001)
    d1 = (math.log(S/K)+(r+0.5*v**2)*T)/(v*math.sqrt(T)); d2 = d1-v*math.sqrt(T)
    cdf = lambda x: (1.0+math.erf(x/math.sqrt(2.0)))/2.0
    return S*cdf(d1)-K*math.exp(-r*T)*cdf(d2) if typ=="CE" else K*math.exp(-r*T)*cdf(-d2)-S*cdf(-d1)

def calc_pnl(S, K, ent, typ, side, T, is_t0=False):
    cv = S if typ=="FUT" else (bs_price(S,K,T,typ) if is_t0 and T>0 else (max(0,S-K) if typ=="CE" else max(0,K-S)))
    return (cv-ent) if side=="BUY" else (ent-cv)

def get_pop(prices, pnls, S, T, v=0.15):
    T = max(T/365.0, 0.001)
    pop, cdf = 0.0, lambda x: (1.0+math.erf(x/math.sqrt(2.0)))/2.0
    for i in range(len(prices)-1):
        if pnls[i]>0:
            z1, z2 = math.log(prices[i]/S)/(v*math.sqrt(T)), math.log(prices[i+1]/S)/(v*math.sqrt(T))
            pop += (cdf(z2)-cdf(z1))
    return min(round(pop*100, 2), 100.0)

# ==========================================
# 3. SIDEBAR SETTINGS (UI)
# ==========================================
st.sidebar.header("⚙️ Algo & Backtest Settings")
mode = st.sidebar.radio("Mode Select", ["Live Trading ⚡", "Backtest / Simulation 🧪"], horizontal=True)

strat = st.sidebar.selectbox("📈 Select Strategy", ["Option Chain Builder ⛓️", "Custom Strategy Builder 🛠️", "Short Straddle (Naked Sell ⚠️)", "Iron Butterfly (Hedged Straddle 🛡️)", "Bullish Hedge (Long FUT + Buy PE)", "Bearish Hedge (Short FUT + Buy CE)"])
sym_name = st.sidebar.selectbox("🔍 Search F&O Symbol", options=unique_syms, index=def_idx).upper()

sym_df = fno_df[fno_df['name']==sym_name]
if not sym_df.empty:
    opt_df = sym_df[sym_df['symbol'].str.endswith('CE') | sym_df['symbol'].str.endswith('PE')]
    if not opt_df.empty:
        exps = sorted(opt_df['expiry'].dropna().unique(), key=parse_exp)
        near_df = opt_df[opt_df['expiry']==exps[0]]
        c_lot = int(near_df.iloc[0]['lotsize'])
        seg = near_df.iloc[0]['exch_seg']
        raw_stks = sorted(near_df['strike'].astype(float).unique())
        stks = sorted(list(set([s/10000 if seg=='BFO' else (s/100 if seg=='NFO' else s) for s in raw_stks])))
        c_step = int(stks[1]-stks[0]) if len(stks)>1 else 50
        c_stk = int(stks[len(stks)//2])
    else:
        exps = sorted(sym_df['expiry'].dropna().unique(), key=parse_exp)
        c_lot, c_step, c_stk = int(sym_df.iloc[0]['lotsize']), 50, 25000
else: exps, c_lot, c_step, c_stk = ["29DEC2026"], 25, 50, 25000

sm_stks = {"NIFTY":24000, "BANKNIFTY":51000, "FINNIFTY":23000, "SENSEX":80000, "BANKEX":60000, "CRUDEOIL":6000, "GOLD":75000, "RELIANCE":3000}
if sym_name in sm_stks: c_stk = sm_stks[sym_name]

st.sidebar.markdown("### 🔍 Asset Settings")
stk_key, exp_key, step_key = f"stk_{sym_name}_{strat}", f"exp_{sym_name}_{strat}", f"step_{sym_name}_{strat}"

tgt_stk = st.sidebar.number_input("Center Strike (ATM)", value=c_stk, step=c_step, key=stk_key)
stk_step = st.sidebar.number_input("Strike Step", value=max(c_step, 10), key=step_key)

if "Backtest" in mode:
    st.sidebar.markdown("### 📅 Select Historical Date")
    selected_backtest_date = st.sidebar.date_input("Backtest Date", value=datetime.date.today() - datetime.timedelta(days=7))
    st.sidebar.info(f"🔒 Data frozen for date: **{selected_backtest_date}**")
    tgt_exp = st.sidebar.text_input("Manual Expiry Date (e.g. 24SEP2026)", value="24SEP2026").upper()
else:
    tgt_exp = st.sidebar.selectbox("Expiry Date", options=exps, index=0, key=exp_key)

lot_size = st.sidebar.number_input("Lot Size", value=c_lot)
dte = st.sidebar.number_input("Days to Expiry", value=3)

if "Backtest" in mode:
    st.sidebar.markdown("---")
    st.sidebar.subheader("🧪 Simulation Controls")
    sim_spot_shift = st.sidebar.slider("Simulated Spot Shift (%)", -1
