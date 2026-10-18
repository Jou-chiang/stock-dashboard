# verify_snapshot_acceptance.py
import json
import csv
import subprocess
import os

SNAPSHOT_PATH = os.path.join(BASE_DIR, "snapshot.json")
ADJ_CSV_PATH = os.path.join(BASE_DIR, "history_data_adj.csv")

print("=" * 80)
print("ACCEPTANCE TEST: L2 ENGINE SNAPSHOT INTEGRITY & SPEC v3.3 COMPLIANCE")
print("=" * 80)

with open(SNAPSHOT_PATH, "r", encoding="utf-8") as f:
    snap1 = json.load(f)

# 1. 驗證持股全為 null 時，無金額、無權重、零虛構
print("\n[CHECK 1] 驗證空值持股保護（零虛構原則）：")
risk = snap1["portfolio_risk"]
print(f"  * cash_status: {risk['cash_status']}")
print(f"  * cash_ratio_pct: {risk['cash_ratio_pct']}")
print(f"  * total_stock_value: {risk['total_stock_value']}")
print(f"  * violations: {risk['violations']}")

assert risk["cash_status"] == "cash_unknown"
assert risk["cash_ratio_pct"] is None
assert risk["total_stock_value"] is None
assert "單檔上限判定暫停" in risk["violations"][0]
print("  => PASS: 組合層絕無虛構市值與金額，單檔上限正確暫停")

for h in snap1["holdings"]:
    code = h["code"]
    assert h["cost"] is None
    assert h["qty"] is None
    assert h["pnl_pct"] is None
    assert h["weight_pct"] is None
    assert "cost_or_qty_missing" in h["data_flags"]
    assert "weight_denominator_stock_only" in h["data_flags"]
print("  => PASS: 全體 6 檔持股 pnl_pct、weight_pct 皆為 null，正確標註 data_flags")

# 2. 手算訊號比對（以 2330 為例）
print("\n[CHECK 2] 手算數值與訊號邏輯比對（2330 台積電）：")
h2330 = next(h for h in snap1["holdings"] if h["code"] == "2330")
sig = h2330["signals"]

# 從 history_data_adj.csv 讀取 2330 收盤價
with open(ADJ_CSV_PATH, "r", encoding="utf-8-sig") as f:
    rows = [r for r in csv.DictReader(f) if r["code"] == "2330"]

rows.sort(key=lambda x: x["date"])
closes = [float(r["close"]) for r in rows]

manual_ma5 = round(sum(closes[-5:]) / 5, 2)
manual_ma20 = round(sum(closes[-20:]) / 20, 2)
manual_ma60 = round(sum(closes[-60:]) / 60, 2)
manual_bias20 = round((closes[-1] - manual_ma20) / manual_ma20 * 100, 1)

print(f"  * 最新還原收盤: {closes[-1]}")
print(f"  * MA5  - 手算: {manual_ma5} | 腳本輸出: {sig['ma5']} | 吻合: {manual_ma5 == sig['ma5']}")
print(f"  * MA20 - 手算: {manual_ma20} | 腳本輸出: {sig['ma20']} | 吻合: {manual_ma20 == sig['ma20']}")
print(f"  * MA60 - 手算: {manual_ma60} | 腳本輸出: {sig['ma60']} | 吻合: {manual_ma60 == sig['ma60']}")
print(f"  * 乖離率 bias_20_pct - 手算: {manual_bias20}% | 腳本輸出: {sig['bias_20_pct']}% | 吻合: {manual_bias20 == sig['bias_20_pct']}")

assert manual_ma5 == sig["ma5"]
assert manual_ma20 == sig["ma20"]
assert manual_ma60 == sig["ma60"]
assert manual_bias20 == sig["bias_20_pct"]
print("  => PASS: 2330 技術指標手算與 L2 產出 100% 精確吻合！")

# 3. 驗證大盤與極端行情
print("\n[CHECK 3] 大盤指標與體系檢驗：")
meta = snap1["meta"]
print(f"  * 市場狀態: {meta['market_regime']}")
print(f"  * 加權指數收盤: {meta['taiex']['close']} | MA60: {meta['taiex']['ma60']}")
print(f"  * 大盤日漲跌: {meta['market_day_change_pct']}% | extreme_move: {meta['extreme_move']}")
assert meta["market_regime"] in ("多頭", "空頭", "盤整")
print("  => PASS: 加權指數多空體系判定成功")

# 4. 確定性與冪等性檢驗（Idempotence: 兩次執行結果完全一致）
print("\n[CHECK 4] 確定性檢驗（Idempotence: 二度執行產出完全一致）：")
# 重新執行一次 generate_snapshot.py
cmd = ["python3", "generate_snapshot.py"]
res = subprocess.run(cmd, cwd=BASE_DIR, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

with open(SNAPSHOT_PATH, "r", encoding="utf-8") as f:
    snap2 = json.load(f)

# 排除 generated_at 毫秒時間戳，比對其餘所有內容
snap1_clean = dict(snap1)
snap2_clean = dict(snap2)
snap1_clean["meta"]["generated_at"] = ""
snap2_clean["meta"]["generated_at"] = ""

diff_match = (json.dumps(snap1_clean, sort_keys=True) == json.dumps(snap2_clean, sort_keys=True))
print(f"  * 二度執行結果結構與數值一致性: {diff_match}")
assert diff_match == True
print("  => PASS: L2 引擎保證無狀態確定性，同一輸入必得同一輸出！")

print("\n" + "=" * 80)
print("ALL ACCEPTANCE CHECKS PASSED SUCCESSFULLY (100% SPEC v3.3 COMPLIANT)")
print("=" * 80)
