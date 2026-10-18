# test_corporate_actions.py
import urllib.request
import urllib.parse
import json
import os
import csv
from datetime import datetime

TOKEN = os.environ.get("FINMIND_TOKEN", "")
api_call_count = 0

def fetch_finmind(dataset, data_id=None, start_date="2026-04-01"):
    global api_call_count
    api_call_count += 1
    params = {
        "dataset": dataset,
        "start_date": start_date
    }
    if data_id:
        params["data_id"] = data_id
    if TOKEN:
        params["token"] = TOKEN
        
    url = "https://api.finmindtrade.com/api/v4/data?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
            return data.get("data", [])
    except Exception as e:
        print(f"Error fetching {dataset} (data_id={data_id}): {e}")
        return []

# Check corporate events for the 6 portfolio stocks
portfolio_stocks = ['2330', '6274', '1513', '2618', '2317', '2454']
print("Checking events for portfolio stocks...")

# 1. Split price (no data_id needed, single API call)
split_records = fetch_finmind("TaiwanStockSplitPrice", start_date="2026-01-01")
print(f"SplitPrice total records: {len(split_records)}")

# 2. Par value change (no data_id needed, single API call)
par_records = fetch_finmind("TaiwanStockParValueChange", start_date="2026-01-01")
print(f"ParValueChange total records: {len(par_records)}")

events_by_stock = {}

for s in portfolio_stocks:
    events = []
    # Dividend result
    div_data = fetch_finmind("TaiwanStockDividendResult", data_id=s, start_date="2026-04-01")
    for d in div_data:
        # factor = after_price / before_price
        bp = d.get("before_price")
        ap = d.get("reference_price") or d.get("after_price")
        if bp and ap and bp > 0:
            events.append({
                "date": d["date"],
                "type": "dividend",
                "subtype": d.get("stock_or_cache_dividend", ""),
                "before_price": bp,
                "after_price": ap,
                "factor": ap / bp,
                "detail": f"股利 {d.get('stock_and_cache_dividend')}"
            })
    
    # Capital reduction
    cap_data = fetch_finmind("TaiwanStockCapitalReductionReferencePrice", data_id=s, start_date="2026-04-01")
    for c in cap_data:
        bp = c.get("ClosingPriceonTheLastTradingDay")
        ap = c.get("PostReductionReferencePrice")
        if bp and ap and bp > 0:
            events.append({
                "date": c["date"],
                "type": "capital_reduction",
                "subtype": c.get("ReasonforCapitalReduction", ""),
                "before_price": bp,
                "after_price": ap,
                "factor": ap / bp,
                "detail": c.get("ReasonforCapitalReduction", "")
            })
            
    # Splits and Par value matching
    for sp in split_records:
        if str(sp.get("stock_id")) == s:
            bp = sp.get("before_price")
            ap = sp.get("after_price")
            if bp and ap and bp > 0:
                events.append({
                    "date": sp["date"],
                    "type": "split",
                    "subtype": sp.get("type", ""),
                    "before_price": bp,
                    "after_price": ap,
                    "factor": ap / bp,
                    "detail": "股票分割"
                })
                
    for pv in par_records:
        if str(pv.get("stock_id")) == s:
            bp = pv.get("before_close")
            ap = pv.get("after_ref_close")
            if bp and ap and bp > 0:
                events.append({
                    "date": pv["date"],
                    "type": "par_value_change",
                    "subtype": "變更面額",
                    "before_price": bp,
                    "after_price": ap,
                    "factor": ap / bp,
                    "detail": "變更面額"
                })
                
    # Sort events chronologically
    events.sort(key=lambda x: x["date"])
    events_by_stock[s] = events
    print(f"Stock {s}: found {len(events)} events")
    for ev in events:
        print(f"   -> {ev['date']} [{ev['type']}|{ev['subtype']}] before={ev['before_price']} after={ev['after_price']} factor={ev['factor']:.6f} ({ev['detail']})")

print(f"\nTotal API calls made so far: {api_call_count}")
