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

# 登入 Shioaji，失敗自動重試最多 3 次
api = None
for attempt in range(3):
    try:
        print(f"登入嘗試 {attempt+1}/3...")
        api = sj.Shioaji()
        api.login(api_key=api_key, secret_key=secret_key, fetch_contract=True, contracts_timeout=120)
        time.sleep(10)
        # 確認合約有載入
        _ = api.Contracts.Stocks
        print("✅ 登入成功，合約載入完成")
        break
    except Exception as e:
        print(f"❌ 嘗試 {attempt+1} 失敗: {e}")
        try:
            api.logout()
        except:
            pass
        api = None
        if attempt < 2:
            print("等待 10 秒後重試...")
            time.sleep(10)

if api is None:
    print("❌ 登入失敗，無法抓取報價")
    # 寫入空的 prices.json 避免覆蓋舊資料
    exit(1)

prices = {}
for stock in stocks:
    code = stock["id"]
    try:
        contract = api.Contracts.Stocks[code]
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

# 只有有資料才寫入，避免覆蓋舊資料
if prices:
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
else:
    print("⚠️ 無資料，保留舊版 prices.json")
