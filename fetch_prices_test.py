import os
import json
import time
from datetime import datetime
import shioaji as sj

api_key = os.environ.get("SHIOAJI_API_KEY", "")
secret_key = os.environ.get("SHIOAJI_SECRET_KEY", "")

if not api_key or not secret_key:
    api_key = input("請輸入 API Key: ").strip()
    secret_key = input("請輸入 Secret Key: ").strip()

# 讀取股票清單
with open("stocks.json", "r", encoding="utf-8") as f:
    stocks = json.load(f)

print("正在執行登入...")
api = sj.Shioaji()
try:
    api.login(
        api_key=api_key,
        secret_key=secret_key,
        fetch_contract=True  # ← 改這裡，要載入合約
    )
    print("✅ 登入成功！")
except Exception as e:
    print(f"❌ 登入失敗: {e}")
    exit(1)

time.sleep(3)

# 逐支抓合約和報價
prices = {}
for stock in stocks:
    code = stock["id"]
    try:
        contract = api.Contracts.Stocks[code]
        snapshot = api.snapshots([contract])
        if snapshot:
            s = snapshot[0]
            prices[code] = {"price": s.close}
            print(f"✅ {code}: {s.close}")
        else:
            print(f"⚠️ {code}: 無資料")
    except Exception as e:
        print(f"❌ {code}: {e}")

# 儲存結果
with open("prices.json", "w", encoding="utf-8") as f:
    json.dump(prices, f, ensure_ascii=False, indent=2)
print(f"\n結果：成功 {len(prices)} 支，失敗 {len(stocks)-len(prices)} 支")

try:
    api.logout()
except:
    pass  # M4 Mac 上 logout 會 crash，忽略即可
