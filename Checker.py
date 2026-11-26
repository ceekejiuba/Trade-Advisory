import json
import os
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

import yfinance as yf

SENDER = os.environ["ALERT_EMAIL"]
PASSWORD = os.environ["ALERT_APP_PASSWORD"]


def send(subject, body):
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, SENDER, SENDER
    msg.set_content(body)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context()) as s:
        s.login(SENDER, PASSWORD)
        s.send_message(msg)


def outcome(item):
    created = datetime.fromisoformat(item["created"])
    df = yf.download(item["symbol"], interval="15m", period="5d",
                     auto_adjust=True, progress=False)
    if df.empty:
        return None
    if hasattr(df.columns, "get_level_values") and df.columns.nlevels > 1:
        df.columns = df.columns.get_level_values(0)
    df = df[df.index >= created]
    for _, bar in df.iterrows():
        hi, lo = float(bar["High"]), float(bar["Low"])
        if item["signal"] == "BUY":
            hit_stop, hit_tp = lo <= item["stop"], hi >= item["target"]
        else:
            hit_stop, hit_tp = hi >= item["stop"], lo <= item["target"]
        if hit_stop and hit_tp:
            return "STOP LOSS"  # unclear order, assume the worse case
        if hit_tp:
            return "TAKE PROFIT"
        if hit_stop:
            return "STOP LOSS"
    if datetime.now(timezone.utc) - created > timedelta(days=item.get("max_days", 3)):
        return "EXPIRED"
    return None


def main():
    with open("tracked.json") as f:
        items = json.load(f)
    remaining = []
    for item in items:
        result = outcome(item)
        if result is None:
            remaining.append(item)
            continue
        send(f"{item['market']} {item['signal']}: {result}",
             f"{item['market']} {item['signal']} signal from entry {item['entry']}\n"
             f"Stop loss {item['stop']}, take profit {item['target']}\n"
             f"Result: {result}")
    with open("tracked.json", "w") as f:
        json.dump(remaining, f, indent=2)


if __name__ == "__main__":
    main()
