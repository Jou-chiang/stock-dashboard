"""
init_scores_v2.py
用現有歷史資料 + 抓取投信資料，產生完整的 pool_scores.json。
需要 FINMIND_TOKEN 環境變數。
"""

import os
import json
import time
import requests
import pandas as pd
from datetime import datetime, timedelta

POOL_FILE    = "pool.json"
HISTORY_FILE = "history_data.csv"
OUTPUT_FILE  = "pool_scores.json"
FINMIND_URL  = "https://api.finmindtrade.com/api/v4/data"
SLEEP_SEC    = 0.8

TOKEN = os.environ.get("FINMIND_TOKEN", "")
if not TOKEN:
    raise Exception("請先設定 FINMIND_TOKEN：export FINMIND_TOKEN='你的token'")

# 讀取股票池
with open(POOL_FILE, "r", encoding="utf-8") as f:
    pool = json.load(f)
pool_map = {s["code"]: s for s in pool}
codes = [s["code"] for s in pool]

# 讀取歷史資料
df = pd.read_csv(HISTORY_FILE, dtype=str, encoding="utf-8-sig")
for col in ["open","high","low","close","volume"]:
    df[col] = pd.to_numeric(df[col], errors="coerce")
print(f"歷史資料：{len(df)} 筆，{df['code'].nunique()} 支")

# 抓投信資料
start_inst = (datetime.today() - timedelta(days=20)).strftime("%Y-%m-%d")
inst_map = {}
print(f"\n開始抓投信資料（{len(codes)} 支）...")

for i, code in enumerate(codes):
    print(f"[{i+1}/{len(codes)}] {code}...", end=" ")
    try:
        r = requests.get(FINMIND_URL, params={
            "dataset":    "TaiwanStockInstitutionalInvestorsBuySell",
            "data_id":    code,
            "start_date": start_inst,
            "token":      TOKEN,
        }, timeout=10)
        j = r.json()
        if j.get("status") == 200 and j["data"]:
            inst_map[code] = j["data"]
            print("✅")
        else:
            print("⚠️ 無資料")
    except Exception as e:
        print(f"❌ {e}")
    time.sleep(SLEEP_SEC)

# 計算連買天數（通用）
def calc_consecutive_buy(inst_rows, keyword):
    rows = sorted(
        [r for r in inst_rows if keyword in str(r.get("name",""))],
        key=lambda x: x["date"]
    )
    days = 0
    for r in reversed(rows):
        net = float(r.get("buy",0)) - float(r.get("sell",0))
        if net > 0:
            days += 1
        else:
            break
    return days

# 計算指標
def calc_kdj(rows):
    k, d = 50.0, 50.0
    for i in range(len(rows)):
        w = rows[max(0,i-8):i+1]
        hh = max(p["high"] for p in w)
        ll = min(p["low"] for p in w)
        rsv = 50 if hh==ll else (rows[i]["close"]-ll)/(hh-ll)*100
        k = k*(2/3)+rsv*(1/3)
        d = d*(2/3)+k*(1/3)
    return round(k,1), round(d,1), round(3*k-2*d,1)

def calc_ma(closes, n):
    if len(closes)<n: return None
    return round(sum(closes[-n:])/n, 2)

def calc_avg_vol(volumes, n):
    if len(volumes)<n+1: return None
    return round(sum(volumes[-(n+1):-1])/n, 1)

# 計算積分
print("\n計算積分中...")
scores = []
today = datetime.today().strftime("%Y-%m-%d")

for code in codes:
    subset = df[df["code"]==code].sort_values("date")
    if len(subset) < 10:
        continue

    rows    = subset.to_dict("records")
    closes  = [r["close"] for r in rows]
    volumes = [r["volume"] for r in rows]
    last    = rows[-1]
    prev    = rows[-2] if len(rows)>=2 else last

    k, d, j  = calc_kdj(rows)
    ma5      = calc_ma(closes, 5)
    ma20     = calc_ma(closes, 20)
    avg_vol5 = calc_avg_vol(volumes, 5)

    chg_pct   = round((last["close"]-prev["close"])/prev["close"]*100, 2) if prev["close"] else 0
    ma_gap    = round(abs(ma5-ma20)/ma20*100, 1) if ma5 and ma20 else 999
    vol_ratio = round(last["volume"]/avg_vol5, 2) if avg_vol5 else 0

    buy_days = calc_consecutive_buy(inst_map.get(code, []), "Investment_Trust")
    foreign_days = calc_consecutive_buy(inst_map.get(code, []), "Foreign_Investor")

    s1 = buy_days >= 3
    s2 = 0 < buy_days < 15
    s3 = k < 50
    s4 = vol_ratio >= 1.5
    s5 = ma_gap < 3
    s6 = foreign_days >= 3

    score = sum([s1, s2, s3, s4, s5, s6])
    info  = pool_map.get(code, {})

    scores.append({
        "code":      code,
        "name":      info.get("name", code),
        "sector":    info.get("sector", ""),
        "price":     last["close"],
        "chg_pct":   chg_pct,
        "k":         k,
        "d":         d,
        "j":         j,
        "ma5":       ma5,
        "ma20":      ma20,
        "ma_gap":    ma_gap,
        "volume":    round(last["volume"]),
        "avg_vol5":  avg_vol5,
        "vol_ratio": vol_ratio,
        "buy_days":     buy_days,
        "foreign_days": foreign_days,
        "score":        score,
        "criteria":     {"s1":s1,"s2":s2,"s3":s3,"s4":s4,"s5":s5,"s6":s6},
        "updated":   today,
    })

scores.sort(key=lambda x: -x["score"])

output = {
    "updated": today,
    "total":   len(scores),
    "scores":  scores,
}

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

z5 = [s for s in scores if s["score"]>=5]
z4 = [s for s in scores if s["score"]==4]
print(f"\n✅ pool_scores.json 完成：{len(scores)} 支（滿分 6 分）")
print(f"   🏆 5-6分：{len(z5)} 支")
print(f"   ⚔️  4分：{len(z4)} 支")
if z5:
    print("\n5-6分股：")
    for s in z5:
        print(f"   {s['code']} {s['name']} {s['score']}分 K={s['k']} 投信{s['buy_days']}天 外資{s['foreign_days']}天")
