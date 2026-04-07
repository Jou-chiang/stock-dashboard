"""
fetch_init.py
初始化腳本，只需執行一次。
抓取 pool.json 內所有股票的 60 日歷史 K 線，存成 history_data.csv。
執行方式：python fetch_init.py
"""

import os
import json
import time
import requests
import pandas as pd
from datetime import datetime, timedelta

# ── 設定 ────────────────────────────────────────────────
POOL_FILE   = "pool.json"
OUTPUT_FILE = "history_data.csv"
FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"
DAYS        = 60  # 抓幾天的歷史資料
SLEEP_SEC   = 1.0 # 每支股票間隔秒數（避免超過 API 限制）

# ── 讀取 Token ───────────────────────────────────────────
# 優先從環境變數讀（GitHub Actions 用），沒有就手動填
TOKEN = os.environ.get("FINMIND_TOKEN", "")
if not TOKEN:
    TOKEN = input("請輸入 FinMind Token：").strip()

# ── 讀取股票池 ───────────────────────────────────────────
with open(POOL_FILE, "r", encoding="utf-8") as f:
    pool = json.load(f)

print(f"股票池共 {len(pool)} 支，開始抓取 {DAYS} 日歷史 K 線...")

# ── 計算日期範圍 ─────────────────────────────────────────
end_date   = datetime.today().strftime("%Y-%m-%d")
start_date = (datetime.today() - timedelta(days=DAYS + 10)).strftime("%Y-%m-%d")
# 多抓 10 天緩衝，排除假日後剛好夠 60 個交易日

# ── 抓資料 ──────────────────────────────────────────────
all_records = []
success = 0
failed  = []

for i, stock in enumerate(pool):
    code = stock["code"]
    name = stock["name"]
    sector = stock.get("sector", "")

    print(f"[{i+1}/{len(pool)}] {code} {name}...", end=" ")

    try:
        r = requests.get(FINMIND_URL, params={
            "dataset":  "TaiwanStockPrice",
            "data_id":  code,
            "start_date": start_date,
            "token":    TOKEN,
        }, timeout=10)

        j = r.json()
        if j.get("status") != 200:
            raise Exception(j.get("msg", "API error"))

        data = j["data"]
        if not data:
            raise Exception("無資料")

        # 整理欄位
        for row in data:
            all_records.append({
                "code":   code,
                "name":   name,
                "sector": sector,
                "date":   row["date"],
                "open":   float(row["open"]),
                "high":   float(row["max"]),
                "low":    float(row["min"]),
                "close":  float(row["close"]),
                "volume": float(row["Trading_Volume"]) / 1000,  # 張
            })

        print(f"✅ {len(data)} 筆")
        success += 1

    except Exception as e:
        print(f"❌ {e}")
        failed.append(f"{code} {name}: {e}")

    time.sleep(SLEEP_SEC)

# ── 存成 CSV ─────────────────────────────────────────────
df = pd.DataFrame(all_records)
df = df.sort_values(["code", "date"])

# 每支股票只保留最近 60 個交易日
def keep_latest(group):
    return group.tail(60)

df = df.groupby("code", group_keys=False).apply(keep_latest)
df.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig")

# ── 結果報告 ─────────────────────────────────────────────
print("\n" + "="*50)
print(f"✅ 成功：{success} 支")
print(f"❌ 失敗：{len(failed)} 支")
if failed:
    print("失敗清單：")
    for f in failed:
        print(f"  {f}")
print(f"\n📁 已存檔：{OUTPUT_FILE}")
print(f"   共 {len(df)} 筆資料，{df['code'].nunique()} 支股票")
print(f"   日期範圍：{df['date'].min()} ～ {df['date'].max()}")
