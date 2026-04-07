import os
import json
import time
from datetime import datetime
import shioaji as sj

# 從 GitHub Secrets 讀取 Key
api_key = os.environ["SHIOAJI_API_KEY"]
secret_key = os.environ["SHIOAJI_SECRET_KEY"]

# 讀取股票清單
with open("stocks.json", "r", encoding="utf-8") as f:
    stocks = json.load(f)

# 登入 Shioaji（不下載全部合約）
api = sj.Shioaji()
api.login(api_key=api_key, secret_key=secret_key, fetch_contract=False)
time.sleep(5)

# 只下載需要的個股合約
codes = [s["id"] for s in stocks]
contracts = []
for code in codes:
    try:
        contract = api.Contracts.Stocks[code]
        contracts.append((code, contract))
        print(f"✅ 合約載入 {code}")
    except Exception as e:
        # 合約還沒載入，用搜尋方式取得
        try:
            results = api.Contracts.Stocks.TSE[code]
            contracts.append((code, results))
            print(f"✅ 合約載入 {code} (TSE)")
        except:
            try:
                results = api.Contracts.Stocks.OTC[code]
                contracts.append((code, results))
                print(f"✅ 合約載入 {code} (OTC)")
            except Exception as e2:
                print(f"❌ 合約失敗 {code}: {e2}")

time.sleep(3)

# 抓快照
prices = {}
for code, contract in contracts:
    try:
        snapshot = api.snapshots([contract])
        if snapshot:
            s = snapshot[0]
            prices[code] = {
                "price": s.close,
                "open": s.open,
                "high": s.high,
                "low": s.low,
                "volume": s.volume,
                "change": s.change_price,
                "change_pct": s.change_rate,
                "updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            print(f"✅ {code}: {s.close}")
        else:
            print(f"⚠️ {code}: 無資料")
    except Exception as e:
        print(f"❌ {code} 錯誤: {e}")

# 登出
api.logout()

# 寫入 prices.json
output = {
    "prices": [
        {
            "id": code,
            "price": data["price"],
            "is_realtime": True,
            "vol": data["volume"] // 1000,
            "updated": data["updated"]
        }
        for code, data in prices.items()
    ]
}

with open("prices.json", "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print("✅ prices.json 更新完成")
