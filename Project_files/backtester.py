import numpy as np
import pandas as pd
from enum import Enum
import sys
from datetime import timedelta
import matplotlib.pyplot as plt
import math
import plotly.graph_objects as go
from plotly.subplots import make_subplots

transaction_fee = 0.0015

sign = lambda x: int(x > 0) - int(x < 0)

class TradeType(Enum):
    LONG = 1
    SHORT = -1

    def __str__(self):
        return "LONG" if self == TradeType.LONG else "SHORT"

class TradePair:
    def __init__(self, symbol, qty, init_price, final_price, init_timestamp, final_timestamp):
        self.symbol = symbol
        self.qty = qty  # In USD (can be +ve or -ve)
        self.init_price = init_price
        self.final_price = final_price
        self.init_timestamp = init_timestamp
        self.final_timestamp = final_timestamp

    def __str__(self):
        return f"TRADED {self.symbol} {self.trade_type()} ${self.qty} @{self.init_price} to {self.final_price} in {self.init_timestamp} - {self.final_timestamp}"
    
    def trade_type(self):
        return TradeType.LONG if self.qty > 0 else TradeType.SHORT

    def pnl(self):
        """Calculate percentage profit and loss for the trade."""
        return self.qty * (self.final_price - self.init_price) / self.init_price - transaction_fee * abs(self.qty)
        # return ""

    def is_win(self):
        """Check if the trade is a winning trade."""
        return self.pnl() > 0

    def holding_time(self):
        """Calculate the holding time for the trade."""
        return self.final_timestamp - self.init_timestamp

    def drawdown(self):
        """Calculate the drawdown for the trade."""
        peak_price = max(self.init_price, self.final_price)
        lowest_price = min(self.init_price, self.final_price)
        return (peak_price - lowest_price) / peak_price * 100
    
class Position:
    def __init__(self, symbol, qty, price, timestamp):
        self.symbol = symbol
        self.qty = qty
        self.price = price
        self.timestamp = timestamp

    def is_valid(self, signal):
        if self.qty == 0:
            return abs(signal) <= 1
        else:
            return sign(self.qty) * sign(signal) <= 0

    def open(self, price, qty, timestamp):
        self.qty = qty
        self.price = price
        self.timestamp = timestamp
    
    def close(self, price, timestamp):
        trade = TradePair(self.symbol, self.qty, self.price, price, self.timestamp, timestamp)

        self.qty = 0
        self.price = None
        self.timestamp = None

        return trade
    

class BackTester:
    def __init__(self, symbol, signal_data_path, master_file_path = None, compound_flag = 0):

        self.compound_flag = compound_flag
        self.symbol = symbol

        self.data = self.preprocess_csv(signal_data_path)

        if "TP" not in self.data.columns:
            self.data["TP"] = 0
        if "SL" not in self.data.columns:
            self.data["SL"] = 0

        master_file_path = master_file_path if master_file_path else signal_data_path
        self.master_data = self.preprocess_csv(master_file_path)

        self.trades = []
        self.position = Position(symbol, 0, None, None)

        self.tp = 0
        self.sl = 0

    def preprocess_csv(self, file_path):
        data = pd.read_csv(file_path, header=0)
        data['datetime'] = pd.to_datetime(data['datetime'])
        data["nextdatetime"] = data["datetime"] + pd.Timedelta(minutes=1)
        data.set_index("datetime", inplace=True)
        return data

    def check_tp_sl(self, timestamp, next_timestamp):

        if self.position.qty == 0:
            return None
        
        if self.tp == 0 and self.sl == 0:
            return None

        trade = None

        for index, row in self.master_data.loc[timestamp : next_timestamp].iterrows():
            if self.position.qty > 0:
                if row["high"] >= self.tp and self.tp != 0:
                    trade = self.position.close(self.tp, row["nextdatetime"])
                    print("Triggered TP for long", file = sys.stderr)
                    break
                elif row["low"] <= self.sl and self.sl != 0:
                    trade = self.position.close(self.sl, row["nextdatetime"])
                    print("Triggered SL for long", file = sys.stderr)
                    break
            elif self.position.qty < 0:
                if row["low"] <= self.tp and self.tp != 0:
                    trade = self.position.close(self.tp, row["nextdatetime"])
                    print("Triggered TP for short", file = sys.stderr)
                    break
                elif row["high"] >= self.sl and self.sl != 0:
                    trade = self.position.close(self.sl, row["nextdatetime"])
                    print("Triggered SL for short", file = sys.stderr)
                    break

        return trade

    def get_trades(self, trade_amt):

        for index, row in self.data.iterrows():
            signal = row["signals"]
            closing_time = row["nextdatetime"]

            if not self.position.is_valid(signal):
                raise ValueError(f"Invalid signal {signal} for current position {sign(self.position.qty)} at {index}")

            trade = self.check_tp_sl(index, closing_time)

            if trade:
                self.trades.append(trade)
                trade_amt = (trade_amt + trade.pnl()) if self.compound_flag else trade_amt
                continue

            self.tp = row["TP"] if row["TP"] != 0 else self.tp
            self.sl = row["SL"] if row["SL"] != 0 else self.sl

            if row["TP"] == 0 and row["SL"] == 0:
                self.tp = self.sl = 0

            if signal == 0:
                continue
            elif signal == 1 or signal == -1:
                if self.position.qty == 0:
                    self.position.open(row["close"], sign(signal)*trade_amt, closing_time)
                else:
                    trade = self.position.close(row["close"], closing_time)
                    self.trades.append(trade)
                    trade_amt = (trade_amt + trade.pnl()) if self.compound_flag else trade_amt
            elif signal == 2 or signal == -2:
                trade = self.position.close(row["close"], closing_time)
                self.trades.append(trade)
                trade_amt = (trade_amt + trade.pnl()) if self.compound_flag else trade_amt
                self.position.open(row["close"], sign(signal)*trade_amt, closing_time)
            else:
                raise ValueError(f"Invalid signal {signal} at {index}")

    def get_statistics(self):
        total_trades = len(self.trades)
        if total_trades==0:
            return None
        winning_trades = [t for t in self.trades if t.is_win()]
        losing_trades = [t for t in self.trades if not t.is_win()]
        long_trades = [t for t in self.trades if t.trade_type() == TradeType.LONG]
        short_trades = [t for t in self.trades if t.trade_type() == TradeType.SHORT]

        gross_profit = sum(t.pnl() for t in winning_trades)
        gross_loss = sum(t.pnl() for t in losing_trades)
        net_profit = gross_profit + gross_loss
        transaction_costs = sum(transaction_fee * abs(t.qty) for t in self.trades)

        max_holding_time = max(t.holding_time() for t in self.trades)
        avg_holding_time = sum((t.holding_time() for t in self.trades), timedelta()) / total_trades

        largest_win = max(t.pnl() for t in winning_trades) if winning_trades else 0
        largest_loss = min(t.pnl() for t in losing_trades) if losing_trades else 0
        average_win = gross_profit / len(winning_trades) if winning_trades else 0
        average_loss = gross_loss / len(losing_trades) if losing_trades else 0

        winning_streak, losing_streak = self.get_streaks()

        max_drawdown, avg_drawdown = self.get_drawdown(np.array([t.pnl() for t in self.trades]))

        sharpe_ratio = self.get_sharpe_ratio()
        # sortino_ratio = self.get_sortino_ratio()

        # adverse_excursions = [self.adverse_excursion(t) for t in self.trades]
        # max_adverse_excursion = max(adverse_excursions)
        # avg_adverse_excursion = np.mean(adverse_excursions)

        stats = {
            "static" : {
                'Total Trades': total_trades,
                'Leverage Applied': 1,  # Assuming no leverage for now
                'Winning Trades': len(winning_trades),
                'Losing Trades': len(losing_trades),
                'No. of Long Trades': len(long_trades),
                'No. of Short Trades': len(short_trades),
                'Benchmark Return(%)': self.get_benchmark_return() * 100,
                'Benchmark Return(on $1000)': self.get_benchmark_return() * 1000,
                'Win Rate': len(winning_trades) / total_trades * 100 if total_trades > 0 else 0,
                'Winning Streak': winning_streak,
                'Losing Streak': losing_streak,
                'Gross Profit': net_profit + transaction_costs,
                'Net Profit': net_profit,
                'Average Profit': net_profit / total_trades if total_trades > 0 else 0,
                'Maximum Drawdown(%)': max_drawdown,
                'Average Drawdown(%)': avg_drawdown,
                'Largest Win': largest_win,
                'Average Win': average_win,
                'Largest Loss': largest_loss,
                'Average Loss': average_loss,
                'Maximum Holding Time': max_holding_time,
                'Average Holding Time': avg_holding_time,
                'Maximum Adverse Excursion': None,
                'Average Adverse Excursion': None,
                'Sharpe Ratio': sharpe_ratio,
                'Sortino Ratio': None,
                # 'Granular Sharpe Ratio': self.get_granular_sharpe_ratio("1D"),
                # 'Granular Sharpe Ratio (Window)': self.get_granular_sharpe_ratio_window("6ME", "1D")
            },
            "compound" : {
                'Trades Executed': total_trades,
                'Total Profit': net_profit
            }
        }

        return stats["static"]
    
    def get_benchmark_return(self):
        """Calculate benchmark return from the stock data."""
        initial_price = self.data.iloc[0]["close"]
        final_price = self.data.iloc[-1]["close"]
        return (final_price - initial_price) / initial_price

    def get_streaks(self):
        """Calculate winning and losing streaks."""
        max_win_streak = max_loss_streak = 0
        current_win_streak = current_loss_streak = 0

        for t in self.trades:
            if t.is_win():
                current_win_streak += 1
                max_win_streak = max(max_win_streak, current_win_streak)
                current_loss_streak = 0
            else:
                current_loss_streak += 1
                max_loss_streak = max(max_loss_streak, current_loss_streak)
                current_win_streak = 0

        return max_win_streak, max_loss_streak
    
    def get_drawdown(self, pnl_array):
        """Calculate the maximum and avg drawdown for the portfolio.
        Pass pnl_array as np.array of trade PnLs."""

        cum_pnl_series = 1000 + pnl_array.cumsum()
        cumulative_max = pd.Series(cum_pnl_series).cummax()
        
        max_drawdown = np.min((cum_pnl_series - cumulative_max) / cumulative_max)
        avg_drawdown = np.mean((cum_pnl_series - cumulative_max) / cumulative_max)

        return abs(max_drawdown)*100, abs(avg_drawdown)*100
    
    def plot_drawdown(self):
        pnl_array = np.array([t.pnl() for t in self.trades])
        cum_pnl_series = 1000 + pnl_array.cumsum()
        cumulative_max = pd.Series(cum_pnl_series).cummax()

        drawdowns = (cum_pnl_series - cumulative_max) / cumulative_max
        drawdowns = drawdowns * 100

        times = [t.final_timestamp for t in self.trades]

        plt.figure(figsize=(12, 6))
        plt.plot(np.array(times), np.array(drawdowns), label="Drawdown", color="red")
        plt.title("Drawdown Over Time")
        plt.xlabel("Time")
        plt.ylabel("Drawdown (%)")
        plt.legend(loc="best")
        plt.show()

    def get_sharpe_ratio(self, risk_free_rate=0.0):
        """Calculate the Sharpe Ratio for the portfolio."""
        returns = [t.pnl()/t.init_price for t in self.trades]
        mean_return = np.mean(returns)
        return_std = np.std(returns)

        return (mean_return - risk_free_rate)*math.sqrt(365) / return_std if return_std > 0 else 0

    def get_sortino_ratio(self, risk_free_rate=0.0):
        """Calculate the Sortino Ratio."""
        returns = [t.pnl() for t in self.trades]
        mean_return = np.mean(returns)
        downside_risk = np.std([r for r in returns if r < 0])

        return (mean_return - risk_free_rate) / downside_risk if downside_risk > 0 else 0
        
    def calc_pnl(self):
        if "pnl" in self.data.columns:
            return

        pnls = []

        curr_trade_idx = 0
        is_trade_open = False

        prev_row = None

        for index, row in self.data.iterrows():        
            if curr_trade_idx < len(self.trades):
                curr_trade = self.trades[curr_trade_idx]
                if curr_trade.final_timestamp <= index and is_trade_open:
                    is_trade_open = False
                    pnl = -transaction_fee * abs(curr_trade.qty)
                    curr_trade_idx += 1
                elif curr_trade.init_timestamp <= index:
                    is_trade_open = True
                    pnl = curr_trade.qty * (row["close"] - prev_row["close"]) / curr_trade.init_price
                else:
                    pnl = 0
            else:
                pnl = 0

            pnls.append(pnl)
            prev_row = row
        
        self.data["pnl"] = pnls

    def calc_capital(self):
        if "capital" not in self.data.columns:
            self.calc_pnl()
            self.data["capital"] = 1000 + self.data["pnl"].cumsum()

    def get_granular_sharpe_ratio(self, period="1D"):
        """
        Calculate the Sharpe Ratio for the portfolio by dividing into periods.
        period: str, a pandas frequency string (e.g., '1D', '6H', '30T', etc.)
        """

        self.calc_capital()

        # Convert period to pandas Timedelta
        offset = pd.to_timedelta(period)

        # Extract data
        capitals = self.data["capital"]
        time_index = self.data.index

        # Initialize variables
        pnls = []
        last_time = time_index[0]  # Start from the first timestamp
        last_capital = capitals.iloc[0]

        # Loop through the index to find periods based on the offset
        for i in range(1, len(time_index)):
            current_time = time_index[i]

            if current_time - last_time >= offset:
                # Calculate PnL for the static capital
                pnls.append(capitals.iloc[i] - last_capital)

                # Update last checkpoint
                last_time = current_time
                last_capital = capitals.iloc[i]

        # Convert to numpy arrays for Sharpe calculation
        pnls = np.array(pnls)

        # Calculate Sharpe ratios
        granular_sharpe = np.mean(pnls) / np.std(pnls) if len(pnls) > 0 else np.nan

        return granular_sharpe*np.sqrt(365)
    
    def get_granular_sharpe_ratio_window(self, window_size="6ME", period="1D"):
        """
        Calculate the Sharpe Ratio for the portfolio by dividing self.data into windows of a specified size.
        For each window, compute the Sharpe Ratio over periods.
        
        Args:
            window_size (str): Size of each window (e.g., '6M', '1Y', etc.).
            period (str): Frequency for PnL calculations within each window (e.g., '1D', '1H', etc.).
        
        Returns:
            list: A list of Sharpe Ratios for each window.
        """

        self.calc_capital()

        # Resample self.data into windows of the specified size
        data_windows = [
            window for _, window in self.data.resample(window_size)
            if not window.empty
        ]

        # Initialize a list to store Sharpe ratios for each window
        sharpe_ratios = []

        # Iterate over each window
        for window_data in data_windows:
            # Convert period to pandas Timedelta
            offset = pd.to_timedelta(period)

            # Extract capital data and its index
            capitals = window_data["capital"]
            time_index = window_data.index

            # Initialize variables for PnL calculation
            pnls = []
            last_time = time_index[0]
            last_capital = capitals.iloc[0]

            # Calculate PnLs for each period within the window
            for i in range(1, len(time_index)):
                current_time = time_index[i]

                if current_time - last_time >= offset:

                    # Calculate PnL
                    pnls.append(capitals.iloc[i] - last_capital)

                    # Update last checkpoint
                    last_time = current_time
                    last_capital = capitals.iloc[i]

            # Convert to numpy array for Sharpe calculation
            pnls = np.array(pnls)

            # Calculate Sharpe ratio for the current window
            sharpe_ratio = np.sqrt(365)*np.mean(pnls) / np.std(pnls) if len(pnls) > 0 else np.nan

            # Append the Sharpe ratio for the current window
            sharpe_ratios.append(sharpe_ratio)

        return sharpe_ratios

    def make_trade_graph(self):
        self.calc_capital()

        fig = go.Figure(data=[go.Candlestick(x=self.data.index,
                                     open=self.data['open'],
                                     high=self.data['high'],
                                     low=self.data['low'],
                                     close=self.data['close'])])
        

        # Identify regions for trades
        trade_regions = []
        for trade in self.trades:
            init_idx = self.data.index.get_indexer([trade.init_timestamp], method='nearest')[0]
            final_idx = self.data.index.get_indexer([trade.final_timestamp], method='nearest')[0]

            # Ensure indices are within valid range
            if 0 <= init_idx < len(self.data) and 0 <= final_idx < len(self.data):
                trade_regions.append((init_idx, final_idx))

                start_close = self.data['close'].iloc[init_idx]
                end_close = self.data['close'].iloc[final_idx]
                price_change = end_close - start_close
            
                if trade.qty > 0:
                    fig.add_shape(type='rect',
                        x0=self.data.index[init_idx], y0=self.data['low'].min(), 
                        x1=self.data.index[final_idx], y1=self.data['high'].max(),
                        fillcolor='green', opacity=0.08, line=dict(width=0))
                elif trade.qty < 0:
                    fig.add_shape(type='rect',
                        x0=self.data.index[init_idx], y0=self.data['low'].min(), 
                        x1=self.data.index[final_idx], y1=self.data['high'].max(),
                        fillcolor='red', opacity=0.08, line=dict(width=0))

        # Add rectangle for currently open position (if any)
        if self.position.qty != 0:
            init_idx = self.data.index.get_indexer([self.position.timestamp], method='nearest')[0]
            final_idx = len(self.data) - 1  # Current position extends to the end of the data
            
            if 0 <= init_idx < len(self.data):
                if self.position.qty > 0:
                    fig.add_shape(type='rect',
                        x0=self.data.index[init_idx], y0=self.data['low'].min(), 
                        x1=self.data.index[final_idx], y1=self.data['high'].max(),
                        fillcolor='green', opacity=0.08, line=dict(width=0))
                elif self.position.qty < 0:
                    fig.add_shape(type='rect',
                        x0=self.data.index[init_idx], y0=self.data['low'].min(), 
                        x1=self.data.index[final_idx], y1=self.data['high'].max(),
                        fillcolor='red', opacity=0.08, line=dict(width=0))
                    

        # Create a mask for "in-trade" and "out-of-trade" regions
        in_trade_mask = [False] * len(self.data)
        for start, end in trade_regions:
            for i in range(start, end + 1):
                in_trade_mask[i] = True


        # Show the interactive plot
        fig.update_layout(
            xaxis=dict(
                rangeslider=dict(visible=True),  # Enables the range slider below the chart
                type="category"  # Set the axis type, if needed
            ),
            yaxis=dict(
                fixedrange=False  # Allow zooming on the y-axis
            ),
            hovermode="closest",
            dragmode='zoom'  # Sets the drag mode to zoom
        )
        fig.show()

    def make_pnl_graph(self):
        self.calc_capital()

        # Create a subplot with one row and one column
        fig = make_subplots(
            rows=1, cols=1, 
            shared_xaxes=True,  # Share the x-axis between both traces
            vertical_spacing=0.1,  # Space between the subplots
            subplot_titles=["Capital and Close Price Over Time"],
            # Use secondary y-axis for the close price
            specs=[[{"secondary_y": True}]]
        )

        # Identify regions for trades
        trade_regions = []
        for trade in self.trades:
            init_idx = self.data.index.get_indexer([trade.init_timestamp], method='nearest')[0]
            final_idx = self.data.index.get_indexer([trade.final_timestamp], method='nearest')[0]

            # Ensure indices are within valid range
            if 0 <= init_idx < len(self.data) and 0 <= final_idx < len(self.data):
                trade_regions.append((init_idx, final_idx))

        # Create a mask for "in-trade" and "out-of-trade" regions
        in_trade_mask = [False] * len(self.data)
        for start, end in trade_regions:
            for i in range(start, end + 1):
                in_trade_mask[i] = True

        # Segment the capital line and add the traces with appropriate colors
        last_state = None
        start_idx = 0

        for i, in_trade in enumerate(in_trade_mask + [None]):  # Add a sentinel value for the last segment
            if last_state is None:
                last_state = in_trade
            elif in_trade != last_state or in_trade is None:
                color = "blue" if last_state else "red"
                fig.add_trace(go.Scatter(
                    x=self.data.index[start_idx:i],
                    y=self.data["capital"][start_idx:i],
                    mode="lines", 
                    line=dict(color=color, width=2),
                    name="Capital",
                    showlegend=False
                ), row=1, col=1, secondary_y=False)  # Plot capital on primary y-axis
                start_idx = i
                last_state = in_trade

        # Plot close price on the secondary y-axis
        fig.add_trace(go.Scatter(
            x=self.data.index,
            y=self.data["close"],
            mode="lines", 
            line=dict(color="grey", width=1.5),
            showlegend=False,
        ), row=1, col=1, secondary_y=True)  # Plot close price on secondary y-axis

        # Update layout for interactivity and styling
        fig.update_layout(
            title="Capital and Close Price Over Time",
            xaxis_title="Time",
            hovermode="closest",
            showlegend=True,  # Show legends for both traces
            # margin=dict(l=50, r=50, t=50, b=50),
        )

        # Update y-axes titles and other settings
        fig.update_yaxes(title_text="Capital ($)", row=1, col=1, secondary_y=False)
        fig.update_yaxes(title_text="Close Price", row=1, col=1, secondary_y=True)

        # Show the interactive plot
        fig.show()    



if __name__ == "__main__":
    bt = BackTester("BTC", signal_data_path="results_kush.csv", master_file_path="results_kush.csv", compound_flag=1)

    bt.get_trades(1000)

    print(len(bt.data))

    stats = bt.get_statistics()
    for key, val in stats.items():
        print(key, ":", val)

    bt.make_pnl_graph()