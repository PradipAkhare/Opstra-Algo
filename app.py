import streamlit as st, pandas as pd, math, time, requests, pyotp
import plotly.graph_objects as go
from SmartApi import SmartConnect

# ==========================================
# 1. PAGE SETUP & LOGIN (WIDE MODE + CSS)
# ==========================================
st.set_page_config(page_title="Opstra Clone", layout="wide")

# 👇 CSS TO EXPAND TABLE WIDTH & REMOVE CONSTRAINTS 👇
st.markdown("""
    <style>
    .block-container { max-width: 98% !important; padding-top: 1rem; padding-bottom: 1rem; }
    dataframe { width: 100% !important; }
    </style>
""", unsafe_allow_html=True)

st.title("🚀 Opstra Clone: Universal Pro Dashboard")

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
st.sidebar.header("⚙️ Algo Settings")
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
tgt_exp = st.sidebar.selectbox("Expiry Date", options=exps, index=0, key=exp_key)
lot_size = st.sidebar.number_input("Lot Size", value=c_lot)
dte = st.sidebar.number_input("Days to Expiry", value=3)

st.sidebar.markdown("---")
st.sidebar.subheader("🛡️ Risk Management")
m_loss = st.sidebar.number_input("Overall Max Loss (₹)", value=-500)
tsl_act = st.sidebar.number_input("Trailing SL Activate (₹)", value=500)
tsl_trl = st.sidebar.number_input("Trail SL by (₹)", value=200)

st.sidebar.markdown("---")
st.sidebar.subheader("🎯 Leg-Wise Settings")
sl_p = st.sidebar.number_input("Leg SL (%)", 10, 200, 50, step=10)
tgt_p = st.sidebar.number_input("Leg Target (%)", 10, 100, 90, step=10)
start = st.sidebar.button("▶️ START LIVE ALGO")

# ==========================================
# 4. LEGS CONFIGURATION
# ==========================================
est_mgn, legs = 0, []

if "Option Chain" in strat: pass
elif "Custom" in strat:
    st.sidebar.markdown("### 🛠️ Build Your Own Strategy")
    nl = st.sidebar.number_input("Kitne Legs chahiye?", 1, 6, 2)
    hsf, hb = False, False
    for i in range(nl):
        c1, c2, c3 = st.sidebar.columns([1.2, 1.2, 1.5])
        t = c1.selectbox("Type", ["CE","PE","FUT"], key=f"t{i}_{sym_name}_{strat}")
        sd = c2.selectbox("Side", ["BUY","SELL"], key=f"s{i}_{sym_name}_{strat}")
        sk = c3.number_input("Strike", value=tgt_stk, step=stk_step, key=f"k{i}_{sym_name}_{strat}")
        legs.append((t, sd, sk-tgt_stk))
        if t=="FUT" or sd=="SELL": est_mgn+=120000; hsf=True
        else: est_mgn+=10000; hb=True
    if nl>1 and hsf and hb: est_mgn*=0.35
    elif nl>1: est_mgn*=0.85
elif "Butterfly" in strat:
    hd = st.sidebar.number_input("Hedge OTM Distance", value=10*stk_step, step=int(stk_step), key=f"hd_{sym_name}_{strat}")
    legs = [("CE","SELL",0),("PE","SELL",0),("CE","BUY",hd),("PE","BUY",-hd)]; est_mgn=55000
elif "Straddle" in strat: legs = [("CE","SELL",0),("PE","SELL",0)]; est_mgn=130000
elif "Bullish" in strat: legs = [("FUT","BUY",0),("PE","BUY",0)]; est_mgn=45000
else: legs = [("FUT","SELL",0),("CE","BUY",0)]; est_mgn=45000

est_mgn = (lot_size/25)*est_mgn

# ==========================================
# 5. PAYOFF GRAPH (TOP)
# ==========================================
ld, aok = [], True
if "Option Chain" not in strat and legs:
    for t, sd, off in legs:
        tk, sm, ex = get_token(sym_name, tgt_stk+off, t, tgt_exp)
        if tk: ld.append({"t":t, "s":sd, "k":tgt_stk+off, "tk":tk, "sm":sm, "a":True, "ex":ex})
        else: aok = False

    if aok and ld:
        for l in ld: l['e'] = safe_ltp(l['ex'], l['sm'], l['tk'])
        pxs = list(range(int(tgt_stk*0.85), int(tgt_stk*1.15), max(1, int(tgt_stk*0.3/200))))
        pe, pt0 = [], []
        for p in pxs:
            ev, tv = 0, 0
            for l in ld:
                ev += calc_pnl(p, l['k'], l['e'], l['t'], l['s'], 0, False)
                tv += calc_pnl(p, l['k'], l['e'], l['t'], l['s'], dte, True)
            pe.append(ev*lot_size); pt0.append(tv*lot_size)
            
        with st.expander("📊 Pre-Trade Analysis & Payoff Graph", expanded=True):
            pop = get_pop(pxs, pt0, tgt_stk, dte) if ld else 0.0
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Est. Margin", f"₹ {est_mgn:,.0f}")
            m2.metric("Max Profit", "Unlimited 🚀" if (pe[-1]-pe[-2]>1 or pe[0]-pe[1]>1) else f"₹ {max(pe):.2f}")
            m3.metric("Max Loss", "Unlimited ⚠️" if (pe[-1]-pe[-2]<-1 or pe[0]-pe[1]<-1) else f"₹ {min(pe):.2f}")
            m4.metric("POP", f"{pop} %")
            
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=pxs, y=[x if x>=0 else 0 for x in pe], fill='tozeroy', fillcolor='rgba(0,128,0,0.3)', showlegend=False))
            fig.add_trace(go.Scatter(x=pxs, y=[x if x<0 else 0 for x in pe], fill='tozeroy', fillcolor='rgba(255,0,0,0.3)', showlegend=False))
            fig.add_trace(go.Scatter(x=pxs, y=pe, mode='lines', name='Expiry', line=dict(color='blue', dash='dash')))
            fig.add_trace(go.Scatter(x=pxs, y=pt0, mode='lines', name='T+0', line=dict(color='darkorange', width=3)))
            fig.add_vline(x=tgt_stk, line_dash="dot", line_color="red")
            fig.add_hline(y=0, line_color="black")
            st.plotly_chart(fig, use_container_width=True)

# ==========================================
# 6. OPTION CHAIN BUILDER (ALL COLUMNS VISIBLE)
# ==========================================
if "Option Chain" in strat:
    with st.expander(f"⛓️ {sym_name} Option Chain", expanded=True):
        st.markdown(f"#### 📍 {sym_name} ATM: **{tgt_stk}**")
        ch_data = []
        for s in range(int(tgt_stk - 10*stk_step), int(tgt_stk + 11*stk_step), int(stk_step)):
            if s <= 0: continue
            cd, ct, cv = bs_greeks(tgt_stk, s, dte, "CE")
            pd_d, pt, pv = bs_greeks(tgt_stk, s, dte, "PE")
            cp, pp = round(bs_price(tgt_stk, s, dte, "CE"),2), round(bs_price(tgt_stk, s, dte, "PE"),2)
            oi = int(100000*math.exp(-((s-tgt_stk)**2)/100000))
            ch_data.append({"Buy CE":False, "Sell CE":False, "CE Pr":cp, "CE Trnd":"🔴 Sell" if s>=tgt_stk else "🚀 Buy", "CE OI":oi, "CE Th":ct, "CE Dl":cd, "Spot":"ATM" if s==tgt_stk else "", "STRIKE":s, "PE Dl":pd_d, "PE Th":pt, "PE OI":oi, "PE Trnd":"🟢 Buy" if s>tgt_stk else "🔴 Sell", "PE Pr":pp, "Buy PE":False, "Sell PE":False})
        
        df_ch = pd.DataFrame(ch_data)
        def style_ch(row):
            res = []
            for c in df_ch.columns:
                if row['STRIKE']==tgt_stk: res.append('background-color:rgba(255,215,0,0.2);font-weight:bold;')
                elif row['STRIKE']<tgt_stk and 'CE' in c: res.append('background-color:rgba(135,206,250,0.06);')
                elif row['STRIKE']>tgt_stk and 'PE' in c: res.append('background-color:rgba(135,206,250,0.06);')
                else: res.append('')
            return res

        if not df_ch.empty:
            # 👇 FULL WIDTH WIDE DATA EDITOR TO SHOW ALL COLUMNS 👇
            ed_ch = st.data_editor(df_ch.style.apply(style_ch, axis=1), hide_index=True, use_container_width=True)
            hs, hb = False, False
            for _, r in ed_ch.iterrows():
                off = int(r['STRIKE']) - tgt_stk
                if r['Buy CE']: legs.append(("CE","BUY",off)); hb=True; est_mgn+=10000
                if r['Sell CE']: legs.append(("CE","SELL",off)); hs=True; est_mgn+=110000
                if r['Buy PE']: legs.append(("PE","BUY",off)); hb=True; est_mgn+=10000
                if r['Sell PE']: legs.append(("PE","SELL",off)); hs=True; est_mgn+=110000
            if hs and hb and len(legs)>1: est_mgn*=0.35
            elif len(legs)>1: est_mgn*=0.85
            
            if legs:
                ld = []
                for t, sd, off in legs:
                    tk, sm, ex = get_token(sym_name, tgt_stk+off, t, tgt_exp)
                    if tk: ld.append({"t":t, "s":sd, "k":tgt_stk+off, "tk":tk, "sm":sm, "a":True, "ex":ex})
                if ld:
                    for l in ld: l['e'] = safe_ltp(l['ex'], l['sm'], l['tk'])
                    pxs = list(range(int(tgt_stk*0.85), int(tgt_stk*1.15), max(1, int(tgt_stk*0.3/200))))
                    pe, pt0 = [], []
                    for p in pxs:
                        ev, tv = 0, 0
                        for l in ld:
                            ev += calc_pnl(p, l['k'], l['e'], l['t'], l['s'], 0, False)
                            tv += calc_pnl(p, l['k'], l['e'], l['t'], l['s'], dte, True)
                        pe.append(ev*lot_size); pt0.append(tv*lot_size)
                    
                    st.markdown("---")
                    pop = get_pop(pxs, pt0, tgt_stk, dte)
                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("Est. Margin", f"₹ {est_mgn:,.0f}")
                    m2.metric("Max Profit", "Unlimited 🚀" if (pe[-1]-pe[-2]>1 or pe[0]-pe[1]>1) else f"₹ {max(pe):.2f}")
                    m3.metric("Max Loss", "Unlimited ⚠️" if (pe[-1]-pe[-2]<-1 or pe[0]-pe[1]<-1) else f"₹ {min(pe):.2f}")
                    m4.metric("POP", f"{pop} %")
                    
                    fig = go.Figure()
                    fig.add_trace(go.Scatter(x=pxs, y=[x if x>=0 else 0 for x in pe], fill='tozeroy', fillcolor='rgba(0,128,0,0.3)', showlegend=False))
                    fig.add_trace(go.Scatter(x=pxs, y=[x if x<0 else 0 for x in pe], fill='tozeroy', fillcolor='rgba(255,0,0,0.3)', showlegend=False))
                    fig.add_trace(go.Scatter(x=pxs, y=pe, mode='lines', name='Expiry', line=dict(color='blue', dash='dash')))
                    fig.add_trace(go.Scatter(x=pxs, y=pt0, mode='lines', name='T+0', line=dict(color='darkorange', width=3)))
                    fig.add_vline(x=tgt_stk, line_dash="dot", line_color="red")
                    fig.add_hline(y=0, line_color="black")
                    st.plotly_chart(fig, use_container_width=True)

# ==========================================
# 7. LIVE ALGO EXECUTION
# ==========================================
if start:
    st.success("✅ Algo Started & Orders Placed!")
    ld = []
    for t, sd, off in legs:
        tk, sm, ex = get_token(sym_name, tgt_stk+off, t, tgt_exp)
        if tk: ld.append({"t":t, "s":sd, "k":tgt_stk+off, "tk":tk, "sm":sm, "a":True, "ex":ex})
    for l in ld:
        l['e'] = safe_ltp(l['ex'], l['sm'], l['tk'])
        l['sl'] = l['e']*(1-sl_p/100) if l['s']=="BUY" else l['e']*(1+sl_p/100)
        l['tg'] = l['e']*(1+tgt_p/100) if l['s']=="BUY" else l['e']*(1-tgt_p/100)
        
    with st.expander("⚡ Live MTM & Tracker", expanded=True):
        cs = st.columns(len(ld))
        lms = [cs[i].empty() for i in range(len(ld))]
        g1, g2, g3, g4 = st.columns(4)
        pm, dm, tm, vm, msg = g1.empty(), g2.empty(), g3.empty(), g4.empty(), st.empty()
        mpnl = 0
        while True:
            pnl, td, tt, tv = 0, 0, 0, 0
            for i, l in enumerate(ld):
                if not l['a']: lms[i].metric(f"🔴 {l['s']} {l['k']} {l['t']}", "Closed"); continue
                l['l'] = safe_ltp(l['ex'], l['sm'], l['tk'])
                pnl += calc_pnl(l['l'], l['k'], l['e'], l['t'], l['s'], 0)*lot_size
                d, t, v = bs_greeks(tgt_stk, l['k'], dte, "CE" if l['t']=="CE" else "PE")
                if l['s']=="SELL": d, t, v = -d, -t, -v
                td+=d; tt+=t; tv+=v
                lms[i].metric(f"🟢 {l['s']} {l['k']} {l['t']}", f"₹ {l['l']}")
                lms[i].caption(f"Traded: {l['sm']}")
            
            pm.metric("Total MTM P&L", f"₹ {pnl:.2f}")
            dm.metric("Total Delta", f"{td:.2f}")
            tm.metric("Total Theta", f"₹ {tt*lot_size:.2f}/day")
            vm.metric("Total Vega", f"{tv:.2f}")
            
            if pnl>mpnl: mpnl=pnl
            if mpnl>=tsl_act and pnl<=(mpnl-tsl_trl):
                msg.error(f"🛡️ TRAILING SL HIT! Protected Profit at ₹{pnl:.2f}.")
                for l in ld:
                    if l['a']: place_order(l['sm'], l['tk'], lot_size, "SELL" if l['s']=="BUY" else "BUY", l['ex'])
                break
            if pnl<=m_loss:
                msg.error(f"⚠️ MAX LOSS HIT! (₹{pnl:.2f})")
                for l in ld:
                    if l['a']: place_order(l['sm'], l['tk'], lot_size, "SELL" if l['s']=="BUY" else "BUY", l['ex'])
                break
                
            if "Naked Sell" in strat and len(ld)>=2:
                ce, pe_l = ld[0], ld[1]
                if ce['a'] and ce['l']>=ce['sl']:
                    place_order(ce['sm'], ce['tk'], lot_size, "BUY", ce['ex']); ce['a']=False
                    if pe_l['a']: place_order(pe_l['sm'], pe_l['tk'], lot_size, "BUY", pe_l['ex']); pe_l['a']=False
                    n_stk = tgt_stk + (10*stk_step)
                    n_tk, n_sm, n_ex = get_token(sym_name, n_stk, "PE", tgt_exp)
                    if n_tk:
                        place_order(n_sm, n_tk, lot_size, "SELL", n_ex)
                        pe_l.update({"a":True, "sm":n_sm, "tk":n_tk, "k":n_stk, "ex":n_ex, "l":safe_ltp(n_ex,n_sm,n_tk)})
                        pe_l['sl'] = pe_l['l']*(1+sl_p/100)
                if pe_l['a'] and pe_l['l']>=pe_l['sl']:
                    place_order(pe_l['sm'], pe_l['tk'], lot_size, "BUY", pe_l['ex']); pe_l['a']=False
                    if ce['a']: place_order(ce['sm'], ce['tk'], lot_size, "BUY", ce['ex']); ce['a']=False
                    n_stk = tgt_stk - (10*stk_step)
                    n_tk, n_sm, n_ex = get_token(sym_name, n_stk, "CE", tgt_exp)
                    if n_tk:
                        place_order(n_sm, n_tk, lot_size, "SELL", n_ex)
                        ce.update({"a":True, "sm":n_sm, "tk":n_tk, "k":n_stk, "ex":n_ex, "l":safe_ltp(n_ex,n_sm,n_tk)})
                        ce['sl'] = ce['l']*(1+sl_p/100)
            time.sleep(1)
