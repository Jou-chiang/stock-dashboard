import os
import json
import time
from datetime import datetime
import shioaji as sj

# 從環境變數讀取 API key（GitHub Secrets）
api_key = os.environ.get("SHIOAJI_API_KEY", "")
secret_key = os.environ.get("SHIOAJI_SECRET_KEY", "")

if not api_key or not secret_key:
    raise Exception("請設定 SHIOAJI_API_KEY 和 SHIOAJI_SECRET_KEY 環境變數")

# 讀取股票清單
with open("stocks.json", "r", encoding="utf-8") as f:
    stocks = json.load(f)

print(f"股票清單：{len(stocks)} 支，開始登入...")

api = sj.Shioaji()
try:
    api.login(
        api_key=api_key,
        secret_key=secret_key,
        fetch_contract=True
    )
    print("✅ 登入成功！")
except Exception as e:
    print(f"❌ 登入失敗: {e}")
    exit(1)

time.sleep(3)

# 逐支抓報價
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

# 儲存成 prices.json
output = {"prices": [{"id": k, "price": v["price"]} for k, v in prices.items()]}
with open("prices.json", "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f"\n✅ prices.json 更新完成，共 {len(prices)} 支")

try:
    api.logout()
except:
    pass
