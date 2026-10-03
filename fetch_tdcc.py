"""
fetch_tdcc.py
自動從臺灣集中保管結算所 (TDCC) 官方 Open Data 下載最新的「集保戶股權分散表」，
解析大戶與散戶持股數據，更新至 tdcc_data.json 中供 Dashboard C 使用。
"""

import os
import json
import csv
import io
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
POOL_FILE = os.path.join(BASE_DIR, "pool.json")
OUTPUT_FILE = os.path.join(BASE_DIR, "tdcc_data.json")

TDCC_URL = "https://smart.tdcc.com.tw/opendata/getOD.ashx?id=1-5"

def fetch_tdcc():
    print("開始從 TDCC 官方下載最新集保戶股權分散表...")
    req = urllib.request.Request(TDCC_URL, headers={'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'})
    
    content = ""
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                content = resp.read().decode('utf-8-sig')
                if content:
                    break
        except Exception as e:
            print(f"⚠️ 第 {attempt+1} 次下載嘗試失敗: {e}")
            if attempt == 2:
                print(f"❌ 下載 TDCC 資料失敗: {e}")
                return

    reader = csv.reader(io.StringIO(content))
    header = next(reader, None)
    
    raw_by_date = {}
    
    # 讀取現有歷史紀錄
    existing_data = {}
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                existing_data = json.load(f).get("data", {})
        except Exception:
            pass

    # 解析全場 CSV
    # Columns: 資料日期, 證券代號, 持股分級, 人數, 股數, 占集保庫存數比例%
    current_date = ""
    for row in reader:
        if len(row) < 6:
            continue
        d, code, level, people, shares, pct = [x.strip() for x in row[:6]]
        if not code:
            continue
        current_date = d
        if code not in raw_by_date:
            raw_by_date[code] = {}
        
        try:
            lvl = int(level)
            p = int(people) if people.isdigit() else 0
            s = int(shares) if shares.isdigit() else 0
            pc = float(pct) if pct.replace('.','',1).isdigit() else 0.0
            raw_by_date[code][lvl] = {"people": p, "shares": s, "pct": pc}
        except ValueError:
            continue

    if not current_date:
        print("❌ 未能解析出有效日期")
        return

    print(f"✅ TDCC 資料下載完成，最新資料日期: {current_date}，涵蓋 {len(raw_by_date)} 支標的")

    # 讀取股票池清單
    target_codes = set()
    if os.path.exists(POOL_FILE):
        with open(POOL_FILE, "r", encoding="utf-8") as f:
            pool = json.load(f)
            target_codes = {s["code"] for s in pool}
    
    # 若股票池為空，預設包含 raw_by_date 中所有的股票
    if not target_codes:
        target_codes = set(raw_by_date.keys())

    # 為每支標的計算大戶 (>=1000張, level 15) 與 散戶 (<50張, level 1-9) 數據
    updated_count = 0
    for code in target_codes:
        if code not in raw_by_date:
            continue

        levels = raw_by_date[code]
        l15 = levels.get(15, {})
        
        over1000_people = l15.get("people", 0)
        over1000_pct = round(l15.get("pct", 0.0), 2)
        over1000_shares = l15.get("shares", 0)

        # 400張以上大戶 (level 11-15)
        over400_pct = round(sum(levels.get(lvl, {}).get("pct", 0.0) for lvl in range(11, 16)), 2)
        
        # 散戶 (<50張, level 1-9)
        retail_people = sum(levels.get(lvl, {}).get("people", 0) for lvl in range(1, 10))
        retail_pct = round(sum(levels.get(lvl, {}).get("pct", 0.0) for lvl in range(1, 10)), 2)

        record = {
            "date": current_date,
            "over1000_people": over1000_people,
            "over1000_pct": over1000_pct,
            "over1000_shares": over1000_shares,
            "over400_pct": over400_pct,
            "retail_people": retail_people,
            "retail_pct": retail_pct
        }

        if code not in existing_data:
            existing_data[code] = {"history": []}
        
        history = existing_data[code].get("history", [])
        
        # 避免重複插入相同日期
        history = [h for h in history if h.get("date") != current_date]
        history.append(record)
        
        # 按日期排序並限制最多保留 30 週
        history.sort(key=lambda x: x["date"])
        history = history[-30:]

        # 計算最新週變動 (Week-over-Week)
        latest = history[-1]
        prev = history[-2] if len(history) >= 2 else latest
        
        latest["over1000_pct_chg"] = round(latest["over1000_pct"] - prev["over1000_pct"], 2)
        latest["over1000_people_chg"] = latest["over1000_people"] - prev["over1000_people"]
        latest["retail_pct_chg"] = round(latest["retail_pct"] - prev["retail_pct"], 2)
        latest["over400_pct_chg"] = round(latest["over400_pct"] - prev["over400_pct"], 2)

        existing_data[code]["latest"] = latest
        existing_data[code]["history"] = history
        updated_count += 1

    output_data = {
        "last_updated": current_date,
        "total_stocks": updated_count,
        "data": existing_data
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    print(f"✅ {OUTPUT_FILE} 輸出完成，包含 {updated_count} 支標的最新集保數據")

if __name__ == "__main__":
    fetch_tdcc()
