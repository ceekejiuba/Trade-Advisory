import pandas as pd
import streamlit as st
import yfinance as yf
import plotly.graph_objects as go

st.set_page_config(page_title="Trade Signal Dashboard", layout="wide")

# Yahoo Finance symbols. Add or remove markets freely.
WATCHLIST = {
    "EUR/USD": "EURUSD=X",
    "GBP/USD": "GBPUSD=X",
    "USD/JPY": "JPY=X",
    "USD/NGN": "NGN=X",
    "Gold": "GC=F",
    "Silver": "SI=F",
    "Crude Oil": "CL=F",
    "S&P 500": "^GSPC",
    "Nasdaq 100": "^NDX",
    "FTSE 100": "^FTSE",
}

INTERVALS = {"Daily": ("1d", "1y"), "Hourly": ("1h", "60d")}

# ---------- sidebar controls ----------
st.sidebar.header("Settings")
timeframe = st.sidebar.selectbox("Timeframe", list(INTERVALS.keys()))
fast_n = st.sidebar.number_input("Fast average", 5, 50, 20)
slow_n = st.sidebar.number_input("Slow average", 20, 200, 50)
stop_mult = st.sidebar.slider("Stop loss (x ATR)", 0.5, 4.0, 1.5, 0.1)
tp_mult = st.sidebar.slider("Take profit (x ATR)", 1.0, 8.0, 3.0, 0.1)
lookback = st.sidebar.slider("Signal window (bars)", 1, 10, 3,
                             help="A crossover within this many recent bars still counts as fresh.")


# ---------- indicators ----------
def rsi(close, n=14):
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = gain / loss
    return 100 - 100 / (1 + rs)


def atr(df, n=14):
    prev_close = df["Close"].shift()
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - prev_close).abs(),
        (df["Low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


@st.cache_data(ttl=900)  # refresh data at most every 15 minutes
def load(symbol, interval, period):
    df = yf.download(symbol, interval=interval, period=period,
                     auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df.dropna()


def analyse(df):
    df = df.copy()
    df["fast"] = df["Close"].rolling(fast_n).mean()
    df["slow"] = df["Close"].rolling(slow_n).mean()
    df["rsi"] = rsi(df["Close"])
    df["atr"] = atr(df)
    df["diff"] = df["fast"] - df["slow"]

    last = df.iloc[-1]
    recent = df["diff"].iloc[-(lookback + 1):]
    crossed_up = (recent.iloc[0] <= 0) and (recent.iloc[-1] > 0)
    crossed_down = (recent.iloc[0] >= 0) and (recent.iloc[-1] < 0)

    entry, a = float(last["Close"]), float(last["atr"])
    result = {"signal": "HOLD", "reason": "", "entry": entry,
              "stop": None, "target": None, "rsi": float(last["rsi"]),
              "lean": "up" if last["diff"] > 0 else "down"}

    if crossed_up and last["rsi"] < 70:
        result.update(signal="BUY",
                      reason="Fast average crossed above slow average, RSI not overbought.",
                      stop=entry - stop_mult * a, target=entry + tp_mult * a)
    elif crossed_down and last["rsi"] > 30:
        result.update(signal="SELL",
                      reason="Fast average crossed below slow average, RSI not oversold.",
                      stop=entry + stop_mult * a, target=entry - tp_mult * a)
    else:
        result["reason"] = (f"No fresh crossover. Trend leans {result['lean']}, "
                            f"RSI {last['rsi']:.0f}.")
    return df, result


# ---------- page ----------
st.title("Trade Signal Dashboard")
st.caption("A starting point for your own analysis. Not financial advice.")

interval, period = INTERVALS[timeframe]
rows, frames = [], {}

for name, symbol in WATCHLIST.items():
    try:
        data = load(symbol, interval, period)
        if len(data) < slow_n + 5:
            raise ValueError("not enough data")
        df, r = analyse(data)
        frames[name] = df
        rows.append({
            "Market": name,
            "Signal": r["signal"],
            "Entry": round(r["entry"], 4),
            "Stop loss": None if r["stop"] is None else round(r["stop"], 4),
            "Take profit": None if r["target"] is None else round(r["target"], 4),
            "RSI": round(r["rsi"], 0),
            "Why": r["reason"],
        })
    except Exception as e:
        rows.append({"Market": name, "Signal": "NO DATA", "Why": str(e)})

summary = pd.DataFrame(rows)


def colour(val):
    return {"BUY": "background-color:#c8f7c5",
            "SELL": "background-color:#f7c5c5"}.get(val, "")


st.dataframe(summary.style.map(colour, subset=["Signal"]),
             use_container_width=True, hide_index=True)

st.subheader("Chart")
choice = st.selectbox("Pick a market", [m for m in WATCHLIST if m in frames])
if choice:
    df = frames[choice].tail(150)
    fig = go.Figure()
    fig.add_trace(go.Candlestick(x=df.index, open=df["Open"], high=df["High"],
                                 low=df["Low"], close=df["Close"], name="Price"))
    fig.add_trace(go.Scatter(x=df.index, y=df["fast"], name=f"Fast ({fast_n})"))
    fig.add_trace(go.Scatter(x=df.index, y=df["slow"], name=f"Slow ({slow_n})"))
    row = summary[summary["Market"] == choice].iloc[0]
    if pd.notna(row.get("Stop loss")):
        fig.add_hline(y=row["Stop loss"], line_dash="dash", line_color="red",
                      annotation_text="Stop loss")
        fig.add_hline(y=row["Take profit"], line_dash="dash", line_color="green",
                      annotation_text="Take profit")
    fig.update_layout(xaxis_rangeslider_visible=False, height=550)
    st.plotly_chart(fig, use_container_width=True)
