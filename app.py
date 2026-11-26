import json
import pandas as pd
import streamlit as st
import yfinance as yf
import plotly.graph_objects as go
from datetime import datetime, timezone
from github import Github

st.set_page_config(page_title="Trade Signal Dashboard v2", layout="wide")

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

# ---------- sidebar ----------
st.sidebar.header("Settings")
fast_n = st.sidebar.number_input("Fast average (hourly bars)", 5, 50, 20)
slow_n = st.sidebar.number_input("Slow average (hourly bars)", 20, 200, 50)
rr = st.sidebar.slider("Reward to risk (minimum 3)", 3.0, 6.0, 3.0, 0.5)
stop_frac = st.sidebar.slider("Stop distance (x daily range)", 0.2, 1.0, 0.5, 0.1)
max_days = st.sidebar.slider("Longest trade (days)", 1, 3, 3)
lookback = st.sidebar.slider("Signal window (bars)", 1, 10, 3)


def rsi(close, n=14):
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + gain / loss)


@st.cache_data(ttl=900)
def load_hourly(symbol):
    df = yf.download(symbol, interval="1h", period="60d",
                     auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df.dropna()


@st.cache_data(ttl=3600)
def load_daily(symbol):
    df = yf.download(symbol, interval="1d", period="3mo",
                     auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df.dropna()


def typical_daily_range(daily):
    # average of the last 14 daily high-to-low ranges
    return float((daily["High"] - daily["Low"]).tail(14).mean())


def analyse(hourly, daily):
    df = hourly.copy()
    df["fast"] = df["Close"].rolling(fast_n).mean()
    df["slow"] = df["Close"].rolling(slow_n).mean()
    df["rsi"] = rsi(df["Close"])
    df["diff"] = df["fast"] - df["slow"]

    last = df.iloc[-1]
    recent = df["diff"].iloc[-(lookback + 1):]
    up = (recent.iloc[0] <= 0) and (recent.iloc[-1] > 0)
    down = (recent.iloc[0] >= 0) and (recent.iloc[-1] < 0)

    entry = float(last["Close"])
    drange = typical_daily_range(daily)
    stop_dist = stop_frac * drange
    target_dist = stop_dist * rr
    days_needed = target_dist / drange  # rough days of normal movement

    out = {"signal": "HOLD", "entry": entry, "stop": None, "target": None,
           "rr": None, "days": None, "rsi": float(last["rsi"]), "why": ""}

    wants = None
    if up and last["rsi"] < 70:
        wants = "BUY"
    elif down and last["rsi"] > 30:
        wants = "SELL"

    if wants is None:
        lean = "up" if last["diff"] > 0 else "down"
        out["why"] = f"No fresh crossover. Trend leans {lean}, RSI {last['rsi']:.0f}."
        return df, out

    if days_needed > max_days:
        out["why"] = (f"{wants} setup found but the 3:1 target needs about "
                      f"{days_needed:.1f} days of movement, over your {max_days} day limit.")
        return df, out

    sign = 1 if wants == "BUY" else -1
    out.update(signal=wants, stop=entry - sign * stop_dist,
               target=entry + sign * target_dist, rr=rr,
               days=round(max(days_needed, 0.5), 1),
               why="Fast average crossed the slow average with RSI not stretched. "
                   f"Target is about {days_needed:.1f} days of normal movement.")
    return df, out


# ---------- tracking via GitHub ----------
def github_file():
    gh = Github(st.secrets["GITHUB_TOKEN"])
    repo = gh.get_repo(st.secrets["GITHUB_REPO"])
    return repo, repo.get_contents("tracked.json")


def track_signal(item):
    repo, f = github_file()
    data = json.loads(f.decoded_content.decode())
    data.append(item)
    repo.update_file("tracked.json", "track signal", json.dumps(data, indent=2), f.sha)


# ---------- page ----------
st.title("Trade Signal Dashboard v2")
st.caption("Minimum 3:1 reward to risk, targets sized for 1 to 3 days. "
           "A starting point for your own analysis, not financial advice.")

rows, frames = [], {}
for name, symbol in WATCHLIST.items():
    try:
        h, d = load_hourly(symbol), load_daily(symbol)
        if len(h) < slow_n + 5 or len(d) < 15:
            raise ValueError("not enough data")
        df, r = analyse(h, d)
        frames[name] = (df, r)
        rows.append({"Market": name, "Signal": r["signal"],
                     "Entry": round(r["entry"], 4),
                     "Stop loss": None if r["stop"] is None else round(r["stop"], 4),
                     "Take profit": None if r["target"] is None else round(r["target"], 4),
                     "R:R": r["rr"], "Est. days": r["days"],
                     "RSI": round(r["rsi"]), "Why": r["why"]})
    except Exception as e:
        rows.append({"Market": name, "Signal": "NO DATA", "Why": str(e)})

summary = pd.DataFrame(rows)


def colour(v):
    return {"BUY": "background-color:#c8f7c5",
            "SELL": "background-color:#f7c5c5"}.get(v, "")


st.dataframe(summary.style.map(colour, subset=["Signal"]),
             use_container_width=True, hide_index=True)

active = [r for r in rows if r.get("Signal") in ("BUY", "SELL")]
st.subheader("Track a signal")
if active:
    pick = st.selectbox("Choose a signal to get alerts for", [r["Market"] for r in active])
    if st.button("Track this signal"):
        r = next(x for x in active if x["Market"] == pick)
        try:
            track_signal({"market": pick, "symbol": WATCHLIST[pick],
                          "signal": r["Signal"], "entry": r["Entry"],
                          "stop": r["Stop loss"], "target": r["Take profit"],
                          "created": datetime.now(timezone.utc).isoformat(),
                          "max_days": max_days})
            st.success(f"Tracking {pick}. You will be emailed when it hits take profit or stop loss.")
        except Exception as e:
            st.error(f"Could not save: {e}. Check the secrets in the setup steps.")
else:
    st.info("No active BUY or SELL signals right now. Check back later.")

st.subheader("Chart")
choice = st.selectbox("Pick a market", list(frames.keys()))
if choice:
    df, r = frames[choice]
    df = df.tail(200)
    fig = go.Figure()
    fig.add_trace(go.Candlestick(x=df.index, open=df["Open"], high=df["High"],
                                 low=df["Low"], close=df["Close"], name="Price"))
    fig.add_trace(go.Scatter(x=df.index, y=df["fast"], name=f"Fast ({fast_n})"))
    fig.add_trace(go.Scatter(x=df.index, y=df["slow"], name=f"Slow ({slow_n})"))
    if r["stop"] is not None:
        fig.add_hline(y=r["stop"], line_dash="dash", line_color="red", annotation_text="Stop loss")
        fig.add_hline(y=r["target"], line_dash="dash", line_color="green", annotation_text="Take profit")
    fig.update_layout(xaxis_rangeslider_visible=False, height=550)
    st.plotly_chart(fig, use_container_width=True)
