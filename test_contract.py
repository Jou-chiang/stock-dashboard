import shioaji as sj

api = sj.Shioaji()
api.login(
    api_key="3wA2zXBJ95vmEzsMwvSxVPMJJ7xrct1oeE8jQYuB19Rn",
    secret_key="CXL3yqgaKNZz1hb7Xf4UfmbgGY44uBEvMP2CexG6WeY8",
    fetch_contract=True  # 明確要求載入合約
)

# 測試能不能拿到台積電
try:
    contract = api.Contracts.Stocks["2330"]
    print("✅ 合約載入成功！", contract)
except Exception as e:
    print("❌ 失敗：", e)

api.logout()
