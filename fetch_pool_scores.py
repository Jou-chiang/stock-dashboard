"""
fetch_pool_scores.py
每天 17:00 由 GitHub Actions 自動執行。
1. 讀取 history_data.csv
2. 抓今日最新 1 天資料 append 進去（刪最舊一天維持 60 天）
3. 計算 KDJ / MA / 均量 / 投信連買
4. 輸出 pool_scores.json 供儀表板 B 讀取
"""

import os
import json
import time
import requests
import pandas as pd
from datetime import datetime, timedelta

# ── 設定 ────────────────────────────────────────────────
POOL_FILE    = "pool.json"
HISTORY_FILE = "history_data.csv"
OUTPUT_FILE  = "pool_scores.json"
FINMIND_URL  = "https://api.finmindtrade.com/api/v4/data"
SLEEP_SEC    = 0.8
KEEP_DAYS    = 60

# ── Token ────────────────────────────────────────────────
TOKEN = os.environ.get("FINMIND_TOKEN", "")
if not TOKEN:
    raise Exception("請設定 FINMIND_TOKEN 環境變數（GitHub Secrets）")

# ── 讀取股票池 ───────────────────────────────────────────
with open(POOL_FILE, "r", encoding="utf-8") as f:
    pool = json.load(f)

pool_map = {s["code"]: s for s in pool}
codes = [s["code"] for s in pool]

print(f"股票池 {len(codes)} 支，開始更新...")

# ── 讀取歷史資料 ─────────────────────────────────────────
df_hist = pd.read_csv(HISTORY_FILE, dtype=str, encoding="utf-8-sig")
# 數值欄位轉回 float
for col in ["open","high","low","close","volume"]:
    df_hist[col] = pd.to_numeric(df_hist[col], errors="coerce")
print(f"歷史資料：{len(df_hist)} 筆，{df_hist['code'].nunique()} 支")

# ── 抓今日資料 ───────────────────────────────────────────
today = datetime.today().strftime("%Y-%m-%d")
yesterday = (datetime.today() - timedelta(days=1)).strftime("%Y-%m-%d")

new_records = []
inst_data_map = {}  # 投信資料

for i, code in enumerate(codes):
    info = pool_map.get(code, {})
    print(f"[{i+1}/{len(codes)}] {code} {info.get('name','')}...", end=" ")

    try:
        # 抓最新價格
        r = requests.get(FINMIND_URL, params={
            "dataset":    "TaiwanStockPrice",
            "data_id":    code,
            "start_date": yesterday,
            "token":      TOKEN,
        }, timeout=10)
        j = r.json()
        if j.get("status") != 200:
            raise Exception(j.get("msg", "API error"))

        data = j["data"]
        if not data:
            raise Exception("無資料")

        for row in data:
            new_records.append({
                "code":   code,
                "name":   info.get("name", code),
                "sector": info.get("sector", ""),
                "date":   row["date"],
                "open":   float(row["open"]),
                "high":   float(row["max"]),
                "low":    float(row["min"]),
                "close":  float(row["close"]),
                "volume": float(row["Trading_Volume"]) / 1000,
            })

        print(f"✅", end=" ")

    except Exception as e:
        print(f"❌ {e}", end=" ")

    # 抓投信資料
    try:
        start_inst = (datetime.today() - timedelta(days=20)).strftime("%Y-%m-%d")
        r2 = requests.get(FINMIND_URL, params={
            "dataset":    "TaiwanStockInstitutionalInvestorsBuySell",
            "data_id":    code,
            "start_date": start_inst,
            "token":      TOKEN,
        }, timeout=10)
        j2 = r2.json()
        if j2.get("status") == 200 and j2["data"]:
            inst_data_map[code] = j2["data"]
            print("📊")
        else:
            print("")
    except:
        print("")

    time.sleep(SLEEP_SEC)

# ── 合併新舊資料 ─────────────────────────────────────────
df_new = pd.DataFrame(new_records)
df_all = pd.concat([df_hist, df_new], ignore_index=True)
df_all = df_all.drop_duplicates(subset=["code", "date"], keep="last")
df_all = df_all.sort_values(["code", "date"])

# 每支只保留最近 KEEP_DAYS 天
def keep_latest(group):
    return group.tail(KEEP_DAYS)

df_all = df_all.groupby("code", group_keys=False).apply(keep_latest)
df_all.to_csv(HISTORY_FILE, index=False, encoding="utf-8-sig")
print(f"\n✅ history_data.csv 更新完成：{len(df_all)} 筆")

# ── 計算指標 ─────────────────────────────────────────────
def calc_kdj(prices):
    k, d = 50.0, 50.0
    for i in range(len(prices)):
        window = prices[max(0, i-8): i+1]
        hh = max(p["high"] for p in window)
        ll = min(p["low"]  for p in window)
        rsv = 50 if hh == ll else (prices[i]["close"] - ll) / (hh - ll) * 100
        k = k * (2/3) + rsv * (1/3)
        d = d * (2/3) + k * (1/3)
    return round(k, 1), round(d, 1), round(3*k - 2*d, 1)

def calc_ma(closes, n):
    if len(closes) < n:
        return None
    return round(sum(closes[-n:]) / n, 2)

def calc_avg_vol(volumes, n):
    if len(volumes) < n + 1:
        return None
    return round(sum(volumes[-(n+1):-1]) / n, 1)

def calc_inst_buy_days(inst_rows):
    rows = sorted(
        [r for r in inst_rows if "投信" in str(r.get("name", ""))],
        key=lambda x: x["date"]
    )
    days = 0
    for r in reversed(rows):
        net = float(r.get("buy", 0)) - float(r.get("sell", 0))
        if net > 0:
            days += 1
        else:
            break
    return days

# ── 計算積分並輸出 ────────────────────────────────────────
scores = []

for code in codes:
    subset = df_all[df_all["code"] == code].sort_values("date")
    if len(subset) < 10:
        continue

    rows = subset.to_dict("records")
    closes  = [r["close"]  for r in rows]
    highs   = [r["high"]   for r in rows]
    lows    = [r["low"]    for r in rows]
    volumes = [r["volume"] for r in rows]

    last = rows[-1]
    prev = rows[-2] if len(rows) >= 2 else last

    k, d, j = calc_kdj(rows)
    ma5  = calc_ma(closes, 5)
    ma20 = calc_ma(closes, 20)
    avg_vol5 = calc_avg_vol(volumes, 5)

    chg_pct = round((last["close"] - prev["close"]) / prev["close"] * 100, 2) if prev["close"] else 0
    ma_gap  = round(abs(ma5 - ma20) / ma20 * 100, 1) if ma5 and ma20 else 999
    vol_ratio = round(last["volume"] / avg_vol5, 2) if avg_vol5 else 0

    # 投信連買天數
    inst_rows = inst_data_map.get(code, [])
    buy_days = calc_inst_buy_days(inst_rows)

    # 積分計算
    s1 = buy_days >= 3           # 投信連買 ≥ 3天
    s2 = buy_days > 0 and buy_days < 15  # 投信持股尚低（代理：連買天數合理）
    s3 = k < 50                  # K < 50
    s4 = vol_ratio >= 1.5        # 量 > 均量 1.5倍
    s5 = ma_gap < 3              # 均線糾結

    score = sum([s1, s2, s3, s4, s5])
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
        "buy_days":  buy_days,
        "score":     score,
        "criteria":  {"s1": s1, "s2": s2, "s3": s3, "s4": s4, "s5": s5},
        "updated":   today,
    })

# 依積分排序
scores.sort(key=lambda x: -x["score"])

output = {
    "updated": today,
    "total":   len(scores),
    "scores":  scores,
}

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f"✅ pool_scores.json 輸出完成：{len(scores)} 支")
top5 = [s for s in scores if s["score"] == 5]
top4 = [s for s in scores if s["score"] == 4]
print(f"   5分：{len(top5)} 支，4分：{len(top4)} 支")
