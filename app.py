import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

def calculate_call_payoff(spot_prices, strike_price, premium, position='long'):
    # Call option intrinsic value: max(0, Spot - Strike)
    payoff = np.where(spot_prices > strike_price, spot_prices - strike_price, 0)
    if position == 'long':
        return payoff - premium
    else: # short
        return premium - payoff

def calculate_put_payoff(spot_prices, strike_price, premium, position='long'):
    # Put option intrinsic value: max(0, Strike - Spot)
    payoff = np.where(spot_prices < strike_price, strike_price - spot_prices, 0)
    if position == 'long':
        return payoff - premium
    else: # short
        return premium - payoff

# Nifty ka example setup
current_spot = 22000
# Hum x-axis par 21000 se 23000 tak ke spot prices check karenge
spot_prices = np.arange(21000, 23000, 50) 

# Strategy: Long Straddle (Buy 22000 CE & 22000 PE)
ce_payoff = calculate_call_payoff(spot_prices, strike_price=22000, premium=150, position='long')
pe_payoff = calculate_put_payoff(spot_prices, strike_price=22000, premium=140, position='long')

# Total Strategy Payoff
strategy_payoff = ce_payoff + pe_payoff

# Data ko dataframe me daalna (API ke through frontend bhejne ke liye)
df = pd.DataFrame({'Spot_Price': spot_prices, 'Total_PnL': strategy_payoff})
print(df.head())
