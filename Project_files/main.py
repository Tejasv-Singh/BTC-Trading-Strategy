import pandas as pd
import numpy as np
import talib as tb # Not directly used in this example, but useful for other indicators
import pandas_ta as ta
from backtester import BackTester


def process_data(data):
    """
    Process the input data and return a dataframe with all the necessary indicators and data for making signals.

    Parameters:
    data (pandas.DataFrame): The input data to be processed.

    Returns:
    pandas.DataFrame: The processed dataframe with all the necessary indicators and data.
    """
    # Generate the necessary indicators here.
    # Ensure no lookahead bias: indicators for row 'i' must only use data up to row 'i'.

    # Example: Calculate Average True Range (ATR)
    # ATR is a volatility indicator. pandas_ta handles lookahead bias correctly for its functions.
    data['ATR'] = ta.atr(data['high'], data['low'], data['close'], length=14)

    # Example: Calculate Simple Moving Averages (SMAs)
    # These can be used for trend following strategies
    data['SMA_50'] = ta.sma(data['close'], length=50)
    data['SMA_200'] = ta.sma(data['close'], length=200)

    # Example: Calculate Relative Strength Index (RSI)
    # RSI is a momentum oscillator.
    data['RSI'] = ta.rsi(data['close'], length=14)

    return data


def strat(data):
    """
    Create a trading strategy based on indicators or other factors.

    Parameters:
    - data: DataFrame
        The input data containing the necessary columns for strategy creation (including indicators).

    Returns:
    - DataFrame
        The modified input data with an additional 'signals' column representing the strategy signals.
    """
    # Initialize 'trade_type' and 'signals' columns
    data['trade_type'] = "HOLD"
    data['signals'] = 0
    
    # Variable to keep track of the current position (0 = no position, 1 = long, -1 = short)
    position = 0 

    # Parameters for the strategy (you can tune these)
    # ATR multiplier for trailing stop-loss
    trailing_stop_multiplier = 2.5 
    # RSI thresholds
    rsi_overbought = 70
    rsi_oversold = 30

    # Initialize trailing stop variable
    trailing_stop = 0  

    # Loop through the data to generate signals
    # Start from an index where all indicators have enough historical data (e.g., max length of indicators)
    # For SMA_200, we need at least 200 data points, so start from 200.
    start_index = max(200, 14) # Ensure ATR and SMAs are calculated

    for i in range(start_index, len(data)):
        # Ensure no lookahead bias: only use data up to index 'i' for decision making.
        current_close = data.loc[i, 'close']
        current_open = data.loc[i, 'open']
        current_volume = data.loc[i, 'volume']
        current_atr = data.loc[i, 'ATR']
        current_sma_50 = data.loc[i, 'SMA_50']
        current_sma_200 = data.loc[i, 'SMA_200']
        current_rsi = data.loc[i, 'RSI']

        # Skip if any required indicator is NaN for the current row
        if pd.isna(current_close) or pd.isna(current_atr) or pd.isna(current_sma_50) or pd.isna(current_sma_200) or pd.isna(current_rsi):
            data.loc[i, 'signals'] = 0
            continue

        # --- Strategy Logic ---

        # Simple Moving Average Crossover Strategy with RSI and ATR-based Trailing Stop
        
        # Entry Conditions
        if position == 0:  # Currently neutral
            # Go LONG if SMA_50 crosses above SMA_200 and RSI is not overbought
            if current_sma_50 > current_sma_200 and data.loc[i-1, 'SMA_50'] <= data.loc[i-1, 'SMA_200'] and current_rsi < rsi_overbought:
                data.loc[i, 'signals'] = 1  # Go LONG
                position = 1
                data.loc[i, 'trade_type'] = "LONG"
                # Set initial trailing stop for LONG position
                trailing_stop = current_close - (current_atr * trailing_stop_multiplier)
            # Go SHORT if SMA_50 crosses below SMA_200 and RSI is not oversold
            elif current_sma_50 < current_sma_200 and data.loc[i-1, 'SMA_50'] >= data.loc[i-1, 'SMA_200'] and current_rsi > rsi_oversold:
                data.loc[i, 'signals'] = -1 # Go SHORT
                position = -1
                data.loc[i, 'trade_type'] = "SHORT"
                # Set initial trailing stop for SHORT position
                trailing_stop = current_close + (current_atr * trailing_stop_multiplier)
            else:
                data.loc[i, 'signals'] = 0 # HOLD
        
        # Exit/Reverse Conditions
        elif position == 1:  # Currently LONG
            # Check for reversal from LONG to SHORT (SMA_50 crosses below SMA_200)
            if current_sma_50 < current_sma_200 and data.loc[i-1, 'SMA_50'] >= data.loc[i-1, 'SMA_200']:
                data.loc[i, 'signals'] = -2 # Reverse from LONG to SHORT
                position = -1
                data.loc[i, 'trade_type'] = "REVERSE_LONG_TO_SHORT"
                # Reset trailing stop for new SHORT position
                trailing_stop = current_close + (current_atr * trailing_stop_multiplier)
            # Check if trailing stop is hit for LONG position
            elif current_close < trailing_stop:
                data.loc[i, 'signals'] = -1 # Exit LONG
                position = 0
                data.loc[i, 'trade_type'] = 'CLOSE_LONG_TRAILING_STOP'
                trailing_stop = 0 # Reset trailing stop
            else:
                # Update trailing stop for LONG position (moves up with price)
                trailing_stop = max(trailing_stop, current_close - (current_atr * trailing_stop_multiplier))
                data.loc[i, 'signals'] = 0 # HOLD
        
        elif position == -1: # Currently SHORT
            # Check for reversal from SHORT to LONG (SMA_50 crosses above SMA_200)
            if current_sma_50 > current_sma_200 and data.loc[i-1, 'SMA_50'] <= data.loc[i-1, 'SMA_200']:
                data.loc[i, 'signals'] = 2 # Reverse from SHORT to LONG
                position = 1
                data.loc[i, 'trade_type'] = "REVERSE_SHORT_TO_LONG"
                # Reset trailing stop for new LONG position
                trailing_stop = current_close - (current_atr * trailing_stop_multiplier)
            # Check if trailing stop is hit for SHORT position
            elif current_close > trailing_stop:
                data.loc[i, 'signals'] = 1 # Exit SHORT
                position = 0
                data.loc[i, 'trade_type'] = 'CLOSE_SHORT_TRAILING_STOP'
                trailing_stop = 0 # Reset trailing stop
            else:
                # Update trailing stop for SHORT position (moves down with price)
                trailing_stop = min(trailing_stop, current_close + (current_atr * trailing_stop_multiplier))
                data.loc[i, 'signals'] = 0 # HOLD
    
    return data

def main():
    data = pd.read_csv("BTC_2019_2023_1d.csv")
    
    # Process the data to add indicators
    processed_data = process_data(data.copy()) # Use .copy() to avoid SettingWithCopyWarning
    
    # Apply the trading strategy to generate signals
    result_data = strat(processed_data.copy()) # Use .copy()

    # Save the results to a CSV file
    csv_file_path = "final_data.csv" 
    result_data.to_csv(csv_file_path, index=False)

    # Initialize the BackTester
    # compound_flag=1 means profits/losses will compound into the trade amount
    bt = BackTester("BTC", signal_data_path="final_data.csv", master_file_path="final_data.csv", compound_flag=1)
    
    # Get trades based on the initial capital ($1000)
    bt.get_trades(1000)

    # Print individual trades and their PnL
    print("\n--- Individual Trades ---")
    if bt.trades:
        for trade in bt.trades: 
            print(f"{trade} PnL: {trade.pnl():.2f}")
    else:
        print("No trades executed.")

    # Print overall statistics
    print("\n--- Performance Statistics ---")
    stats = bt.get_statistics()
    if stats:
        for key, val in stats.items():
            # Format timedelta objects for better readability
            if isinstance(val, pd.Timedelta):
                print(f"{key} : {val}")
            else:
                print(f"{key} : {val:.4f}" if isinstance(val, (float, np.float64)) else f"{key} : {val}")
    else:
        print("No statistics to display (likely no trades were made).")

    # Check for lookahead bias
    print("\n--- Checking for lookahead bias ---")
    lookahead_bias = False
    for i in range(len(result_data)):
        if result_data.loc[i, 'signals'] != 0:  # If there's a signal
            # Take data only up to that point (i+1 because iloc is exclusive of the end index)
            temp_data = data.iloc[:i+1].copy() 
            temp_data = process_data(temp_data) # Re-process the data
            temp_data = strat(temp_data) # Re-run strategy
            
            # Compare the signal generated with limited data to the full data signal
            if i < len(temp_data) and temp_data.loc[i, 'signals'] != result_data.loc[i, 'signals']:
                print(f"Lookahead bias detected at index {i}: Signal mismatch.")
                lookahead_bias = True
                break # Exit loop on first detection

    if not lookahead_bias:
        print("No lookahead bias detected.")
    else:
        print("Lookahead bias detected. Please review your process_data and strat functions.")

    # Generate and display the trade graph and PnL graph
    print("\nGenerating Trade Graph...")
    bt.make_trade_graph()
    print("Generating PnL Graph...")
    bt.make_pnl_graph()
    
if __name__ == "__main__":
    main()
