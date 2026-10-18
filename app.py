import streamlit as st, pandas as pd, math, time, requests, pyotp
import plotly.graph_objects as go
from SmartApi import SmartConnect

# ==========================================
# 1. PAGE SETUP & LOGIN
# ==========================================
st.set_page_config(page_title="Opstra Clone", layout="wide")
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
fno_df = df[df['exch_seg'].isin(['NFO', 'MCX'])]
unique_syms = sorted(fno_df['name'].dropna().unique())
def_idx = unique_syms.index("NIFTY") if "NIFTY" in unique_syms else 0

# ==========================================
# 2. HELPER FUNCTIONS
# ==========================================
def get_token(sym, stk, typ, exp):
    f = fno_df[(fno_df['name']==sym) & (fno_df['expiry']==exp)].copy()
    if typ == "FUT": f = f[f['symbol'].str.endswith('FUT')]
    else:
        f['num_stk'] = pd.to_numeric(f['strike'], errors='coerce')
        f = f[((f['num_stk']==float(stk)) | (f['num_stk']/100==float(stk))) & f['symbol'].str.endswith(typ)]
    return (f.iloc[0]['token'], f.iloc[0]['symbol']) if not f.empty else (None, None)

def place_order(sym, tok, qty, side):
    try: return api.placeOrder({"variety":"NORMAL","tradingsymbol":sym,"symboltoken":tok,"transactiontype":side,"exchange":"NFO","ordertype":"MARKET","producttype":"CARRYFORWARD","duration":"DAY","quantity":qty})
    except Exception as e: return str(e)

def bs_greeks(S, K, T, typ="CE", r=0.10, v=0.15):
    T = max(T/365.0, 0.001)
    d1 = (math.log(S/K)+(r+0.5*v**2)*T)/(v*math.sqrt(T)); d2 = d1-v*math.sqrt(T)
    cdf = lambda x: (1.0+math.erf(x/math.sqrt(2.0)))/2.0
    pdf = lambda x: math.exp(-0.5*x**2)/math.sqrt(2*math.pi)
    if typ=="CE": return cdf(d1), -(S*pdf(d1)*v)/(2*math.sqrt(T))-r*K*math.exp(-r*T)*cdf(d2), (S*pdf(d1)*math.sqrt(T))/100
    return cdf(d1)-1, -(S*pdf(d1)*v)/(2*math.sqrt(T))+r*K*math.exp(-r*T)*cdf(-d2), (S*pdf(d1)*math.sqrt(T))/100

def bs_price(S, K, T, typ="CE", r=0.10, v=0.15):
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
sym_name = st.sidebar.selectbox("🔍 Search F&O Symbol (Type to Search)", options=unique_syms, index=def_idx).upper()

# SMART ASSET SYNC
sym_df = fno_df[fno_df['name']==sym_name]
if not sym_df.empty:
    opt_df = sym_df[sym_df['symbol'].str.endswith('CE') | sym_df['symbol'].str.endswith('PE')]
    if not opt_df.empty:
        exps = sorted(opt_df['expiry'].dropna().unique(), key=lambda x: pd.to_datetime(str(x).upper(), format="%d%b%Y", errors='ignore'))
        near_df = opt_df[opt_df['expiry']==exps[0]]
        c_lot = int(near_df.iloc[0]['lotsize'])
        raw_stks = sorted(near_df['strike'].astype(float).unique())
        stks = sorted(list(set([s/100 if near_df.iloc[0]['exch_seg']=='NFO' else s for s in raw_stks])))
        c_step = int(stks[1]-stks[0]) if len(stks)>1 else 50
        c_stk = int(stks[len(stks)//2])
    else:
        exps = sorted(sym_df['expiry'].dropna().unique(), key=lambda x: pd.to_datetime(str(x).upper(), format="%d%b%Y", errors='ignore'))
        c_lot, c_step, c_stk = int(sym_df.iloc[0]['lotsize']), 50, 25000
else: exps, c_lot, c_step, c_stk = ["29DEC2026"], 25, 50, 25000

sm_stks = {"NIFTY":24000, "BANKNIFTY":51000, "FINNIFTY":23000, "CRUDEOIL":6000, "GOLD":75000, "RELIANCE":3000}
if sym_name in sm_stks: c_stk = sm_stks[sym_name]

st.sidebar.markdown("### 🔍 Asset Settings")
tgt_stk = st.sidebar.number_input("Center Strike (ATM)", value=c_stk, step=c_step)
stk_step = st.sidebar.number_input("Strike Step (Difference)", value=max(c_step, 10))
tgt_exp = st.sidebar.selectbox("Expiry Date", options=exps, key=f"e_{sym_name}")
lot_size = st.sidebar.number_input("Lot Size", value=c_lot)
dte = st.sidebar.number_input("Days to Expiry", value=3)

st.sidebar.markdown("---")
st.sidebar.subheader("🛡️ Risk Management")
m_loss = st.sidebar.number_input("Overall Max Loss (₹)", value=-500)
tsl_act = st.sidebar.number_input("Activate Trailing SL after Profit (₹)", value=500)
tsl_trl = st.sidebar.number_input("Trail SL by (₹)", value=200)

st.sidebar.markdown("---")
st.sidebar.subheader("🎯 Leg-Wise Settings")
sl_p = st.sidebar.number_input("Individual Leg SL (%)", 10, 200, 50, step=10)
tgt_p = st.sidebar.number_input("Individual Leg Target (%)", 10, 100, 90, step=10)
start = st.sidebar.button("▶️ START LIVE ALGO")

# ==========================================
# 4. MAIN DASHBOARD LOGIC
# ==========================================
est_mgn, legs = 0, []

if "Option Chain" in strat:
    with st.expander(f"⛓️ {sym_name} Option Chain (Click to Show/Hide)", expanded=True):
        st.markdown(f"#### 📍 {sym_name} is currently at: **{tgt_stk} (ATM)**")
        st.caption("☑️ Checkboxes par tick karein aur Strategy banayein (Greeks & OI ke sath!)")
        ch_data = []
        for s in range(int(tgt_stk - 10*stk_step), int(tgt_stk + 11*stk_step), int(stk_step)):
            cd, ct, cv = bs_greeks(tgt_stk, s, dte, "CE")
            pd_d, pt, pv = bs_greeks(tgt_stk, s, dte, "PE")
            cp, pp = round(bs_price(tgt_stk, s, dte, "CE"),2), round(bs_price(tgt_stk, s, dte, "PE"),2)
            oi = int(100000*math.exp(-((s-tgt_stk)**2)/100000))
            ch_data.append({"Buy CE":False, "Sell CE":False, "CE Price":cp, "CE Trend":"🔴 Short Buildup" if s>=tgt_stk else "🚀 Short Covering", "CE OI":oi, "CE Theta":ct, "CE Delta":cd, "Spot":"🎯 ATM" if s==tgt_stk else "", "STRIKE":s, "PE Delta":pd_d, "PE Theta":pt, "PE OI":oi, "PE Trend":"🟢 Long Buildup" if s>tgt_stk else "🔴 Short Buildup", "PE Price":pp, "Buy PE":False, "Sell PE":False})
        
        df_ch = pd.DataFrame(ch_data)
        def style_ch(row):
            res = []
            for c in df_ch.columns:
                if row['STRIKE']==tgt_stk: res.append('background-color:rgba(255,215,0,0.2);font-weight:bold;border-top:1px solid #FFD700;border-bottom:1px solid #FFD700;')
                elif row['STRIKE']<tgt_stk and 'CE' in c: res.append('background-color:rgba(135,206,250,0.08);')
                elif row['STRIKE']>tgt_stk and 'PE' in c: res.append('background-color:rgba(135,206,250,0.08);')
                else: res.append('')
            return res

        ed_ch = st.data_editor(df_ch.style.apply(style_ch, axis=1), hide_index=True, use_container_width=True, column_config={"Spot": st.column_config.TextColumn("📍 Spot", width="small"), "STRIKE": st.column_config.NumberColumn("🎯 STRIKE", required=True), "Buy CE": st.column_config.CheckboxColumn("🟢 Buy CE"), "Sell CE": st.column_config.CheckboxColumn("🔴 Sell CE"), "CE Price": st.column_config.NumberColumn("₹ CE Price", format="%.2f"), "CE Trend": st.column_config.TextColumn("📈 CE Trend"), "CE OI": st.column_config.ProgressColumn("📊 CE OI Bar", format="%d", min_value=0, max_value=100000), "PE OI": st.column_config.ProgressColumn("📊 PE OI Bar", format="%d", min_value=0, max_value=100000), "PE Trend": st.column_config.TextColumn("📉 PE Trend"), "PE Price": st.column_config.NumberColumn("₹ PE Price", format="%.2f"), "Buy PE": st.column_config.CheckboxColumn("🟢 Buy PE"), "Sell PE": st.column_config.CheckboxColumn("🔴 Sell PE")})
        
        hs, hb = False, False
        for _, r in ed_ch.iterrows():
            off = int(r['STRIKE']) - tgt_stk
            if r['Buy CE']: legs.append(("CE","BUY",off)); hb=True; est_mgn+=10000
            if r['Sell CE']: legs.append(("CE","SELL",off)); hs=True; est_mgn+=110000
            if r['Buy PE']: legs.append(("PE","BUY",off)); hb=True; est_mgn+=10000
            if r['Sell PE']: legs.append(("PE","SELL",off)); hs=True; est_mgn+=110000
        if hs and hb and len(legs)>1: est_mgn*=0.35
        elif len(legs)>1: est_mgn*=0.85
elif "Custom" in strat:
    st.sidebar.markdown("### 🛠️ Build Your Own Strategy")
    nl = st.sidebar.number_input("Kitne Legs chahiye?", 1, 6, 2)
    hsf, hb = False, False
    for i in range(nl):
        c1, c2, c3 = st.sidebar.columns([1.2, 1.2, 1.5])
        t = c1.selectbox("Type", ["CE","PE","FUT"], key=f"t{i}")
        sd = c2.selectbox("Side", ["BUY","SELL"], key=f"s{i}")
        sk = c3.number_input("Strike", value=tgt_stk, step=stk_step, key=f"k{i}")
        legs.append((t, sd, sk-tgt_stk))
        if t=="FUT" or sd=="SELL": est_mgn+=120000; hsf=True
        else: est_mgn+=10000; hb=True
    if nl>1 and hsf and hb: est_mgn*=0.35
    elif nl>1: est_mgn*=0.85
elif "Butterfly" in strat:
    hd = st.sidebar.number_input("Hedge OTM Distance", value=10*stk_step, step=int(stk_step))
    legs = [("CE","SELL",0),("PE","SELL",0),("CE","BUY",hd),("PE","BUY",-hd)]; est_mgn=55000
elif "Straddle" in strat: legs = [("CE","SELL",0),("PE","SELL",0)]; est_mgn=130000
elif "Bullish" in strat: legs = [("FUT","BUY",0),("PE","BUY",0)]; est_mgn=45000
else: legs = [("FUT","SELL",0),("CE","BUY",0)]; est_mgn=45000

est_mgn = (lot_size/25)*est_mgn

# ==========================================
# 5. LIVE ALGO & PAYOFF GRAPH
# ==========================================
ld, aok = [], True
if legs:
    for t, sd, off in legs:
        tk, sm = get_token(sym_name, tgt_stk+off, t, tgt_exp)
        if tk: ld.append({"t":t, "s":sd, "k":tgt_stk+off, "tk":tk, "sm":sm, "a":True})
        else: aok = False
    
    if aok:
        for l in ld:
            l['e'] = api.ltpData("NFO", l['sm'], l['tk'])['data']['ltp']
            l['sl'] = l['e']*(1-sl_p/100) if l['s']=="BUY" else l['e']*(1+sl_p/100)
            l['tg'] = l['e']*(1+tgt_p/100) if l['s']=="BUY" else l['e']*(1-tgt_p/100)
        
        pxs = list(range(int(tgt_stk*0.85), int(tgt_stk*1.15), max(1, int(tgt_stk*0.3/200))))
        pe, pt0 = [], []
        for p in pxs:
            ev, tv = 0, 0
            for l in ld:
                ev += calc_pnl(p, l['k'], l['e'], l['t'], l['s'], 0, False)
                tv += calc_pnl(p, l['k'], l['e'], l['t'], l['s'], dte, True)
            pe.append(ev*lot_size); pt0.append(tv*lot_size)
            
        st.markdown("---")
        with st.expander("📊 Pre-Trade Analysis & Payoff Graph", expanded=True):
            pop = get_pop(pxs, pt0, tgt_stk, dte) if ld else 0.0
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Est. Margin Required", f"₹ {est_mgn:,.0f}")
            m2.metric("Max Profit (At Expiry)", "Unlimited 🚀" if (pe[-1]-pe[-2]>1 or pe[0]-pe[1]>1) else f"₹ {max(pe):.2f}")
            m3.metric("Max Loss (At Expiry)", "Unlimited ⚠️" if (pe[-1]-pe[-2]<-1 or pe[0]-pe[1]<-1) else f"₹ {min(pe):.2f}")
            m4.metric("Probability of Profit", f"{pop} %")
            
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=pxs, y=[x if x>=0 else 0 for x in pe], fill='tozeroy', fillcolor='rgba(0,128,0,0.3)', showlegend=False))
            fig.add_trace(go.Scatter(x=pxs, y=[x if x<0 else 0 for x in pe], fill='tozeroy', fillcolor='rgba(255,0,0,0.3)', showlegend=False))
            fig.add_trace(go.Scatter(x=pxs, y=pe, mode='lines', name='Expiry Payoff', line=dict(color='blue', dash='dash')))
            fig.add_trace(go.Scatter(x=pxs, y=pt0, mode='lines', name='T+0 Payoff', line=dict(color='darkorange', width=3)))
            fig.add_vline(x=tgt_stk, line_dash="dot", line_color="red", annotation_text="Strike")
            fig.add_hline(y=0, line_color="black")
            st.plotly_chart(fig, use_container_width=True)

        if start:
            st.success("✅ Algo Started & Orders Placed!")
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
                        l['l'] = api.ltpData("NFO", l['sm'], l['tk'])['data']['ltp']
                        pnl += calc_pnl(l['l'], l['k'], l['e'], l['t'], l['s'], 0)*lot_size
                        d, t, v = bs_greeks(tgt_stk, l['k'], dte, "CE" if l['t']=="CE" else "PE")
                        if l['s']=="SELL": d, t, v = -d, -t, -v
                        td+=d; tt+=t; tv+=v
                        lms[i].metric(f"🟢 {l['s']} {l['k']} {l['t']}", f"₹ {l['l']}")
                    
                    pm.metric("Total MTM P&L", f"₹ {pnl:.2f}")
                    dm.metric("Total Delta", f"{td:.2f}")
                    tm.metric("Total Theta", f"₹ {tt*lot_size:.2f}/day")
                    vm.metric("Total Vega", f"{tv:.2f}")
                    
                    if pnl>mpnl: mpnl=pnl
                    if mpnl>=tsl_act and pnl<=(mpnl-tsl_trl):
                        msg.error(f"🛡️ TRAILING SL HIT! Protected Profit at ₹{pnl:.2f}.")
                        for l in ld:
                            if l['a']: place_order(l['sm'], l['tk'], lot_size, "SELL" if l['s']=="BUY" else "BUY")
                        break
                    if pnl<=m_loss:
                        msg.error(f"⚠️ MAX LOSS HIT! (₹{pnl:.2f})")
                        for l in ld:
                            if l['a']: place_order(l['sm'], l['tk'], lot_size, "SELL" if l['s']=="BUY" else "BUY")
                        break
                        
                    if "Naked Sell" in strat and len(ld)>=2:
                        ce, pe_l = ld[0], ld[1]
                        if ce['a'] and ce['l']>=ce['sl']:
                            place_order(ce['sm'], ce['tk'], lot_size, "BUY"); ce['a']=False
                            if pe_l['a']: place_order(pe_l['sm'], pe_l['tk'], lot_size, "BUY"); pe_l['a']=False
                            n_stk = tgt_stk + (10*stk_step)
                            n_tk, n_sm = get_token(sym_name, n_stk, "PE", tgt_exp)
                            if n_tk:
                                place_order(n_sm, n_tk, lot_size, "SELL")
                                pe_l.update({"a":True, "sm":n_sm, "tk":n_tk, "k":n_stk, "l":api.ltpData("NFO",n_sm,n_tk)['data']['ltp']})
                                pe_l['sl'] = pe_l['l']*(1+sl_p/100)
                        if pe_l['a'] and pe_l['l']>=pe_l['sl']:
                            place_order(pe_l['sm'], pe_l['tk'], lot_size, "BUY"); pe_l['a']=False
                            if ce['a']: place_order(ce['sm'], ce['tk'], lot_size, "BUY"); ce['a']=False
                            n_stk = tgt_stk - (10*stk_step)
                            n_tk, n_sm = get_token(sym_name, n_stk, "CE", tgt_exp)
                            if n_tk:
                                place_order(n_sm, n_tk, lot_size, "SELL")
                                ce.update({"a":True, "sm":n_sm, "tk":n_tk, "k":n_stk, "l":api.ltpData("NFO",n_sm,n_tk)['data']['ltp']})
                                ce['sl'] = ce['l']*(1+sl_p/100)
                    time.sleep(1)
    else: st.warning(f"⚠️ {sym_name} ka Token nahi mila. Kripya Expiry Date check karein.")
elif "Option Chain" in strat:
    st.info("👆 Option Chain mein se koi leg select karein (Buy/Sell check box pe tick mark karein) taaki Payoff Graph dikh sake!")
