import pandas as pd
import numpy as np
import talib as tb
import pandas_ta as ta
from backtester import BackTester


def process_data(data):
    """Process input data and add technical indicators."""
    data['ATR'] = ta.atr(data['high'], data['low'], data['close'], length=14)
    data['SMA_20'] = ta.sma(data['close'], length=20)
    data['SMA_50'] = ta.sma(data['close'], length=50)
    data['SMA_200'] = ta.sma(data['close'], length=200)
    data['RSI'] = ta.rsi(data['close'], length=14)
    data['MACD'], data['MACD_signal'], data['MACD_hist'] = ta.macd(data['close'])
    data['BB_upper'], data['BB_middle'], data['BB_lower'] = ta.bbands(data['close'], length=20)
    data['Volume_SMA'] = ta.sma(data['volume'], length=20)
    
    # Price momentum and volatility
    data['Price_Change'] = data['close'].pct_change()
    data['Volatility'] = data['Price_Change'].rolling(window=14).std()
    
    return data


def strat(data):
    """Enhanced trading strategy with multiple confirmation signals."""
    data['trade_type'] = "HOLD"
    data['signals'] = 0
    
    position = 0
    trailing_stop_multiplier = 2.0
    rsi_overbought = 70
    rsi_oversold = 30
    trailing_stop = 0
    entry_price = 0
    
    start_index = 200
    
    for i in range(start_index, len(data)):
        current_close = data.loc[i, 'close']
        current_atr = data.loc[i, 'ATR']
        current_sma_20 = data.loc[i, 'SMA_20']
        current_sma_50 = data.loc[i, 'SMA_50']
        current_sma_200 = data.loc[i, 'SMA_200']
        current_rsi = data.loc[i, 'RSI']
        current_macd = data.loc[i, 'MACD']
        current_macd_signal = data.loc[i, 'MACD_signal']
        current_volume = data.loc[i, 'volume']
        volume_sma = data.loc[i, 'Volume_SMA']
        bb_upper = data.loc[i, 'BB_upper']
        bb_lower = data.loc[i, 'BB_lower']
        
        # Skip if indicators are NaN
        required_indicators = [current_close, current_atr, current_sma_20, 
                             current_sma_50, current_sma_200, current_rsi, 
                             current_macd, current_macd_signal]
        if any(pd.isna(val) for val in required_indicators):
            data.loc[i, 'signals'] = 0
            continue
        
        # Enhanced signal conditions
        trend_bullish = (current_sma_20 > current_sma_50 > current_sma_200)
        trend_bearish = (current_sma_20 < current_sma_50 < current_sma_200)
        
        sma_cross_up = (current_sma_50 > current_sma_200 and 
                       data.loc[i-1, 'SMA_50'] <= data.loc[i-1, 'SMA_200'])
        sma_cross_down = (current_sma_50 < current_sma_200 and 
                         data.loc[i-1, 'SMA_50'] >= data.loc[i-1, 'SMA_200'])
        
        macd_bullish = current_macd > current_macd_signal
        macd_bearish = current_macd < current_macd_signal
        
        volume_confirmation = current_volume > volume_sma * 1.2
        price_above_bb_middle = current_close > data.loc[i, 'BB_middle']
        price_below_bb_middle = current_close < data.loc[i, 'BB_middle']
        
        # Entry logic with multiple confirmations
        if position == 0:
            # Enhanced LONG entry
            long_conditions = [
                sma_cross_up or (trend_bullish and current_close > current_sma_20),
                current_rsi < rsi_overbought and current_rsi > 40,
                macd_bullish,
                price_above_bb_middle or current_close > bb_lower * 1.01,
                volume_confirmation or current_volume > volume_sma * 0.8
            ]
            
            if sum(long_conditions) >= 3:
                data.loc[i, 'signals'] = 1
                position = 1
                data.loc[i, 'trade_type'] = "LONG"
                entry_price = current_close
                trailing_stop = current_close - (current_atr * trailing_stop_multiplier)
            
            # Enhanced SHORT entry
            short_conditions = [
                sma_cross_down or (trend_bearish and current_close < current_sma_20),
                current_rsi > rsi_oversold and current_rsi < 60,
                macd_bearish,
                price_below_bb_middle or current_close < bb_upper * 0.99,
                volume_confirmation or current_volume > volume_sma * 0.8
            ]
            
            if sum(short_conditions) >= 3:
                data.loc[i, 'signals'] = -1
                position = -1
                data.loc[i, 'trade_type'] = "SHORT"
                entry_price = current_close
                trailing_stop = current_close + (current_atr * trailing_stop_multiplier)
        
        # Exit logic with improved conditions
        elif position == 1:
            # Profit target
            profit_pct = (current_close - entry_price) / entry_price
            
            # Enhanced exit conditions for LONG
            exit_conditions = [
                current_close < trailing_stop,  # Trailing stop
                current_rsi > 75,  # Extreme overbought
                macd_bearish and current_rsi > 65,  # MACD divergence
                profit_pct > 0.15,  # Take profit at 15%
                trend_bearish and current_close < current_sma_20  # Trend reversal
            ]
            
            # Reversal to SHORT
            if (sma_cross_down and macd_bearish and current_rsi < 65) or trend_bearish:
                data.loc[i, 'signals'] = -2
                position = -1
                data.loc[i, 'trade_type'] = "REVERSE_LONG_TO_SHORT"
                entry_price = current_close
                trailing_stop = current_close + (current_atr * trailing_stop_multiplier)
            elif any(exit_conditions):
                data.loc[i, 'signals'] = -1
                position = 0
                data.loc[i, 'trade_type'] = 'CLOSE_LONG'
                trailing_stop = 0
            else:
                # Dynamic trailing stop adjustment
                new_trailing_stop = current_close - (current_atr * trailing_stop_multiplier)
                trailing_stop = max(trailing_stop, new_trailing_stop)
                data.loc[i, 'signals'] = 0
        
        elif position == -1:
            # Profit target
            profit_pct = (entry_price - current_close) / entry_price
            
            # Enhanced exit conditions for SHORT
            exit_conditions = [
                current_close > trailing_stop,  # Trailing stop
                current_rsi < 25,  # Extreme oversold
                macd_bullish and current_rsi < 35,  # MACD divergence
                profit_pct > 0.15,  # Take profit at 15%
                trend_bullish and current_close > current_sma_20  # Trend reversal
            ]
            
            # Reversal to LONG
            if (sma_cross_up and macd_bullish and current_rsi > 35) or trend_bullish:
                data.loc[i, 'signals'] = 2
                position = 1
                data.loc[i, 'trade_type'] = "REVERSE_SHORT_TO_LONG"
                entry_price = current_close
                trailing_stop = current_close - (current_atr * trailing_stop_multiplier)
            elif any(exit_conditions):
                data.loc[i, 'signals'] = 1
                position = 0
                data.loc[i, 'trade_type'] = 'CLOSE_SHORT'
                trailing_stop = 0
            else:
                # Dynamic trailing stop adjustment
                new_trailing_stop = current_close + (current_atr * trailing_stop_multiplier)
                trailing_stop = min(trailing_stop, new_trailing_stop)
                data.loc[i, 'signals'] = 0
    
    return data


def validate_strategy(data, result_data):
    """Check for lookahead bias in strategy implementation."""
    print("\n--- Checking for lookahead bias ---")
    lookahead_bias = False
    
    signal_indices = result_data[result_data['signals'] != 0].index[:5]  # Check first 5 signals
    
    for i in signal_indices:
        temp_data = data.iloc[:i+1].copy()
        temp_data = process_data(temp_data)
        temp_data = strat(temp_data)
        
        if i < len(temp_data) and temp_data.loc[i, 'signals'] != result_data.loc[i, 'signals']:
            print(f"Lookahead bias detected at index {i}")
            lookahead_bias = True
            break
    
    if not lookahead_bias:
        print("No lookahead bias detected in sample validation.")
    
    return not lookahead_bias


def main():
    # Load and process data
    data = pd.read_csv("BTC_2019_2023_1d.csv")
    processed_data = process_data(data.copy())
    result_data = strat(processed_data.copy())
    
    # Save results
    result_data.to_csv("final_data.csv", index=False)
    
    # Validate strategy
    is_valid = validate_strategy(data, result_data)
    if not is_valid:
        print("Strategy validation failed. Please review implementation.")
        return
    
    # Initialize backtester
    bt = BackTester("BTC", 
                   signal_data_path="final_data.csv", 
                   master_file_path="final_data.csv", 
                   compound_flag=1)
    
    # Execute backtesting
    bt.get_trades(1000)
    
    # Display results
    print("\n--- Individual Trades ---")
    if bt.trades:
        total_trades = len(bt.trades)
        winning_trades = sum(1 for trade in bt.trades if trade.pnl() > 0)
        
        for i, trade in enumerate(bt.trades[:10], 1):  # Show first 10 trades
            print(f"Trade {i}: {trade} | PnL: ${trade.pnl():.2f}")
        
        if total_trades > 10:
            print(f"... and {total_trades - 10} more trades")
        
        print(f"\nTrade Summary: {winning_trades}/{total_trades} winning trades "
              f"({winning_trades/total_trades*100:.1f}% win rate)")
    else:
        print("No trades executed.")
    
    # Performance statistics
    print("\n--- Performance Statistics ---")
    stats = bt.get_statistics()
    if stats:
        key_metrics = ['Total Return', 'Max Drawdown', 'Sharpe Ratio', 'Win Rate', 'Total Trades']
        for key, val in stats.items():
            if any(metric in key for metric in key_metrics):
                if isinstance(val, pd.Timedelta):
                    print(f"{key}: {val}")
                elif isinstance(val, (float, np.float64)):
                    if 'Rate' in key or 'Return' in key:
                        print(f"{key}: {val:.2%}")
                    else:
                        print(f"{key}: {val:.4f}")
                else:
                    print(f"{key}: {val}")
    else:
        print("No statistics available.")
    
    # Generate visualizations
    print("\nGenerating analysis charts...")
    bt.make_trade_graph()
    bt.make_pnl_graph()
    print("Analysis complete. Check generated charts for visual insights.")


if __name__ == "__main__":
    main()