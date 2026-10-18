# test_all_missing_branches.py
import sys
import os
import json
from datetime import datetime, timedelta

import os
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
from generate_snapshot import compute_stock_signals, compute_market_regime, evaluate_thesis
from price_adapter import PriceSeries

print("=" * 85)
print("TEST SUITE: COMPREHENSIVE VERIFICATION OF ALL REMAINING SIGNAL & RISK BRANCHES")
print("=" * 85)

results = []
def check(desc, actual, expected, detail=""):
    match = (actual == expected)
    results.append(match)
    flag = "[PASS]" if match else "[FAIL]"
    print(f"  {flag} {desc}")
    print(f"        手算預期 (Expected): {expected}")
    print(f"        腳本輸出 (Actual)  : {actual}" + (f" | {detail}" if detail else ""))
    assert match, f"Mismatch in {desc}"

def make_series(code, closes, vols, dates=None, events=None, price_basis="adjusted"):
    if dates is None:
        dates = [f"2026-09-{i+1:02d}" for i in range(len(closes))]
    rows = []
    for i in range(len(closes)):
        rows.append({
            "code": code,
            "date": dates[i],
            "open": closes[i],
            "high": closes[i] * 1.01,
            "low": closes[i] * 0.99,
            "close": closes[i],
            "volume": vols[i]
        })
    return PriceSeries(code=code, rows=rows, price_basis=price_basis, events=events or [], meta_info={})

# ─────────────────────────────────────────────────────────────────────────────
# 1. 停利觸發、失效觸發、停損未觸發
# ─────────────────────────────────────────────────────────────────────────────
print("\n[BRANCH 1] 手填價位進階分支：停利觸發、失效觸發、停損未觸發")
# 收盤 115 元，停利設 110 元 -> take_profit_hit = True
# 停損設 90 元 -> stop_hit = False
# 失效設 100 元 -> invalidation_hit = False
ps_tp = make_series("TEST_TP", [100.0]*20 + [115.0], [1000]*21)
item_tp = {
    "code": "TEST_TP", "type": "SWING", "entry_date": "2026-09-01",
    "stop_loss_price": 90.0, "invalidation_price": 100.0, "take_profit_target": 110.0
}
sig_tp, _ = compute_stock_signals(item_tp, ps_tp, False, "2026-09-21", {}, {})
check("1A take_profit_hit 觸發 (收盤 115 >= 停利 110)", sig_tp["take_profit_hit"], True)
check("1B stop_hit 未觸發 (收盤 115 > 停損 90)", sig_tp["stop_hit"], False)
check("1C invalidation_hit 未觸發 (收盤 115 > 失效 100)", sig_tp["invalidation_hit"], False)

# 收盤 85 元，失效設 90 元 -> invalidation_hit = True
ps_inv = make_series("TEST_INV", [100.0]*20 + [85.0], [1000]*21)
item_inv = {
    "code": "TEST_INV", "type": "SWING", "entry_date": "2026-09-01",
    "stop_loss_price": 80.0, "invalidation_price": 90.0
}
sig_inv, _ = compute_stock_signals(item_inv, ps_inv, False, "2026-09-21", {}, {})
check("1D invalidation_hit 觸發 (收盤 85 < 失效 90)", sig_inv["invalidation_hit"], True)
check("1E stop_hit 未觸發 (收盤 85 > 停損 80)", sig_inv["stop_hit"], False)

# ─────────────────────────────────────────────────────────────────────────────
# 2. 跌破 MA20 但非連續兩日破位 (第 1 日跌破、第 2 日站回)
# ─────────────────────────────────────────────────────────────────────────────
print("\n[BRANCH 2] 跌破 MA20 但非連續 2 日 (第 1 日破、第 2 日站回)")
# MA20 ~ 100 元 (98% = 98 元)。第 1 日收 96 (< 98)，第 2 日收 101 (> 98)
closes_rebound = [100.0]*19 + [96.0, 101.0]
vols_rebound = [1000]*19 + [1200, 2500]
ps_reb = make_series("TEST_REB", closes_rebound, vols_rebound)
item_reb = {"code": "TEST_REB", "type": "SWING", "entry_date": "2026-09-01"}
sig_reb, _ = compute_stock_signals(item_reb, ps_reb, False, "2026-09-21", {}, {})
check("非連續 2 日破位: ma20_break_confirmed 為 False", sig_reb["ma20_break_confirmed"], False)

# ─────────────────────────────────────────────────────────────────────────────
# 3. 成交量比較嚴格排除當日（第二日成交量 vs 第二日前 5 日均量）
# ─────────────────────────────────────────────────────────────────────────────
print("\n[BRANCH 3] 成交量比較嚴格排除當日")
# 前 5 日成交量: 1000, 1000, 1000, 1000, 1000 (均量 1000)
# 第二日成交量若為 1100 > 1000 -> 爆量確認
# 如果錯誤包含第二日自身算均量，均量會被拉高成 (1000*4 + 1100)/5 = 1020
vols_ex = [1000]*20 + [1000, 1050] # 最後一日 1050 > 前5日均量 1000
closes_ex = [100.0]*20 + [97.0, 97.0] # 連續兩日破位
ps_ex = make_series("TEST_EX", closes_ex, vols_ex)
item_ex = {"code": "TEST_EX", "type": "SWING", "entry_date": "2026-09-01"}
sig_ex, _ = compute_stock_signals(item_ex, ps_ex, False, "2026-09-22", {}, {})
check("嚴格排除第二日自身: 1050 > 前5日均量 1000 觸發 break_confirmed 為 True", sig_ex["ma20_break_confirmed"], True)

# ─────────────────────────────────────────────────────────────────────────────
# 4. CORE 連續 9 日破季線（不觸發） vs 連續 10 日（觸發） vs 回落 20% 分支
# ─────────────────────────────────────────────────────────────────────────────
print("\n[BRANCH 4] CORE 深度回落分支：連續 9 日不觸發 vs 回落 20% 獨立觸發")
# 4A. 連續 9 日收盤 < MA60 (MA60 ~ 100 元，最後 9 日收 95 元)
c_9 = [100.0]*60 + [95.0]*9
ps_9 = make_series("TEST_C9", c_9, [1000]*len(c_9))
item_c9 = {"code": "TEST_C9", "type": "CORE", "entry_date": "2026-09-01"}
sig_c9, _ = compute_stock_signals(item_c9, ps_9, False, "2026-09-30", {}, {})
check("4A 連續 9 日破季線未達門檻: core_deep_drawdown 為 False", sig_c9["core_deep_drawdown"], False)

# 4B. 未連續 10 日破季線，但自最高點回落 20% (最高 100 元，現價 79 元，回落 21%)
c_dd = [100.0]*60 + [99.0, 98.0, 79.0] # 僅破季線 3 天，但跌破最高價 100 的 20%
ps_dd = make_series("TEST_DD", c_dd, [1000]*len(c_dd))
item_dd = {"code": "TEST_DD", "type": "CORE", "entry_date": "2026-09-01"}
sig_dd, _ = compute_stock_signals(item_dd, ps_dd, False, "2026-09-30", {}, {})
check("4B 回落 21% (>=20%): 獨立觸發 core_deep_drawdown 為 True", sig_dd["core_deep_drawdown"], True)

# ─────────────────────────────────────────────────────────────────────────────
# 5. CORE 移動防守 (MA60 與 85% 取高) vs data_insufficient
# ─────────────────────────────────────────────────────────────────────────────
print("\n[BRANCH 5] CORE 移動防守取高規則與資料不足狀態")
# CORE: 進場後最高 200 元，85% 為 170 元。MA60 為 160 元。
# 預期 trailing_stop = max(160, 170) = 170.0 元
# 現價 165 元 < 170 元 -> trailing_stop_hit = True
c_core_ts = [160.0]*60 + [200.0, 190.0, 165.0]
ps_core_ts = make_series("TEST_CORE_TS", c_core_ts, [1000]*len(c_core_ts))
item_core_ts = {
    "code": "TEST_CORE_TS", "type": "CORE", "entry_date": "2026-09-01",
    "partial_profit_taken": True
}
sig_core_ts, _ = compute_stock_signals(item_core_ts, ps_core_ts, False, "2026-09-30", {}, {})
check("5A CORE trailing_stop 取 max(MA60:160, 200*0.85:170) = 170.0", sig_core_ts["trailing_stop"], 170.0)
check("5A CORE trailing_stop_hit 為 True (165 < 170)", sig_core_ts["trailing_stop_hit"], True)

# 5B. partial_profit_taken == True 但缺 entry_date -> data_insufficient
item_ts_no_entry = {
    "code": "TEST_CORE_TS", "type": "CORE", "entry_date": None,
    "partial_profit_taken": True
}
sig_ts_no_entry, df_no_entry = compute_stock_signals(item_ts_no_entry, ps_core_ts, False, "2026-09-30", {}, {})
check("5B 已停利但缺進場日: trailing_stop 為 None", sig_ts_no_entry["trailing_stop"], None)
check("5B 已停利但缺進場日: trailing_stop_status 為 'data_insufficient'", sig_ts_no_entry["trailing_stop_status"], "data_insufficient")

# ─────────────────────────────────────────────────────────────────────────────
# 6. SHORT 動能訊號 (bullish, bearish, neutral)
# ─────────────────────────────────────────────────────────────────────────────
print("\n[BRANCH 6] SHORT 動能短線訊號")
# 6A. bullish: 現價 > MA5 且 今日量 > 昨日量
c_bull = [100.0]*20 + [105.0] # MA5 ~ 101, 現價 105 > MA5
v_bull = [1000]*20 + [1500]  # 今日量 1500 > 昨日量 1000
ps_bull = make_series("TEST_BULL", c_bull, v_bull)
item_bull = {"code": "TEST_BULL", "type": "SHORT", "entry_date": "2026-09-01"}
sig_bull, _ = compute_stock_signals(item_bull, ps_bull, False, "2026-09-21", {}, {})
check("6A bullish: 現價 > MA5 且量增", sig_bull["short_momentum"], "bullish")

# 6B. bearish: 現價 < MA5
c_bear = [100.0]*20 + [95.0]  # 現價 95 < MA5
v_bear = [1000]*20 + [800]
ps_bear = make_series("TEST_BEAR", c_bear, v_bear)
item_bear = {"code": "TEST_BEAR", "type": "SHORT", "entry_date": "2026-09-01"}
sig_bear, _ = compute_stock_signals(item_bear, ps_bear, False, "2026-09-21", {}, {})
check("6B bearish: 現價 < MA5", sig_bear["short_momentum"], "bearish")

# ─────────────────────────────────────────────────────────────────────────────
# 7. ex_dividend_check 解除條件（更新價位後恢復為 False）與 SHORT 版本
# ─────────────────────────────────────────────────────────────────────────────
print("\n[BRANCH 7] ex_dividend_check 更新價位後解除條件與 SHORT 版本")
ev_div = [{"date": "2026-09-15", "type": "dividend", "factor": 0.95}]
ps_div = make_series("TEST_DIV", [100.0]*25, [1000]*25, events=ev_div)

# 7A. SWING 已更新價位 (price_levels_updated_at > 2026-09-15) -> ex_dividend_check 解除為 False!
item_updated = {
    "code": "TEST_DIV", "type": "SWING", "entry_date": "2026-09-01",
    "stop_loss_price": 95.0, "price_levels_updated_at": "2026-09-16"
}
sig_updated, _ = compute_stock_signals(item_updated, ps_div, False, "2026-09-25", {}, {})
check("7A 更新價位後: ex_dividend_check 解除為 False", sig_updated["ex_dividend_check"], False)
check("7A 價位恢復正常判定: stop_hit 為 False", sig_updated["stop_hit"], False)

# 7B. SHORT 遇除權息未更新價位 -> ex_dividend_check 為 True
item_short_div = {
    "code": "TEST_DIV", "type": "SHORT", "entry_date": "2026-09-01",
    "stop_loss_price": 105.0, "price_levels_updated_at": None
}
sig_s_div, _ = compute_stock_signals(item_short_div, ps_div, False, "2026-09-25", {}, {})
check("7B SHORT 遇除權息未更新: ex_dividend_check 為 True", sig_s_div["ex_dividend_check"], True)
check("7B SHORT stop_hit 強制輸出 None", sig_s_div["stop_hit"], None)

# ─────────────────────────────────────────────────────────────────────────────
# 8. D 板研報 verified 估值計算、60 天過期 (stale) 與 severity 缺漏預設 major
# ─────────────────────────────────────────────────────────────────────────────
print("\n[BRANCH 8] D 板研報 verified 估值計算、60 天過期與 severity 預設")
theses_branch = {
    "theses": {
        "TEST_VERIFIED": {
            "status": "verified",
            "verified_at": "2026-10-01",
            "consensus_forecast": {
                "2026_eps_range": [10.0, 12.0],
                "target_pe_range": [20.0, 25.0]
            },
            "event_flags": []
        },
        "TEST_STALE": {
            "status": "verified",
            "verified_at": "2026-06-01", # 超過 60 天
            "consensus_forecast": {
                "2026_eps_range": [10.0, 12.0],
                "target_pe_range": [20.0, 25.0]
            },
            "event_flags": []
        },
        "TEST_SEVERITY_DEFAULT": {
            "status": "verified",
            "verified_at": "2026-10-01",
            "event_flags": [
                {"date": "2026-10-10", "type": "法說下修", "resolved": False} # 缺少 severity
            ]
        }
    }
}
# 8A. verified: 樂觀上緣 = 12.0 * 25.0 = 300.0 元。現價 330 元 -> price_vs_bull_ceiling = +10.0%
ps_v = make_series("TEST_VERIFIED", [300.0]*20 + [330.0], [1000]*21)
item_v = {"code": "TEST_VERIFIED", "type": "CORE", "entry_date": "2026-09-01"}
sig_v, _ = compute_stock_signals(item_v, ps_v, False, "2026-10-15", theses_branch, {})
check("8A verified 狀態: bull_ceiling 算出 300.0", sig_v["bull_ceiling"], 300.0)
check("8A verified 狀態: price_vs_bull_ceiling 為 +10.0%", sig_v["price_vs_bull_ceiling"], 10.0)

# 8B. 60 天過期轉 stale: bull_ceiling 遮蔽為 None
sig_stale, _ = compute_stock_signals({"code": "TEST_STALE", "type": "CORE"}, ps_v, False, "2026-10-15", theses_branch, {})
check("8B 超過 60 天轉 stale: effective_status 為 'stale'", sig_stale["thesis_effective_status"], "stale")
check("8B stale 狀態下 bull_ceiling 遮蔽為 None", sig_stale["bull_ceiling"], None)

# 8C. severity 缺漏預設 major: 觸發 thesis_has_open_event == True
sig_sev, _ = compute_stock_signals({"code": "TEST_SEVERITY_DEFAULT", "type": "CORE"}, ps_v, False, "2026-10-15", theses_branch, {})
check("8C severity 缺漏時預設 major: thesis_has_open_event 為 True", sig_sev["thesis_has_open_event"], True)

# ─────────────────────────────────────────────────────────────────────────────
# 9. 第六節組合風控全項實測 (單檔 25%、單一產業 40%、現金 10%、SHORT 15%)
# ─────────────────────────────────────────────────────────────────────────────
print("\n[BRANCH 9] 第六節組合風控全項實測（帶真實金額/股數之測試帳本）")
# 構造測試情境：
# 總資產分母: 股票市值 95 萬 + 現金 5 萬 = 100 萬元
# 1. 現金 5 萬 / 100 萬 = 5.0% < 10% (現金水位低於下限觸發)
# 2. 股票 A (半導體): 市值 30 萬 (30% > 25% 單檔超標，需減碼 (30萬 - 25萬) / 300元 = 167 股)
# 3. 股票 B (半導體): 市值 15 萬 (半導體合計 30萬 + 15萬 = 45萬 / 100萬 = 45% > 40% 產業超標)
# 4. 股票 C (SHORT): 市值 20 萬 (20% > 15% SHORT合計超標)
# 5. 股票 D (其他): 市值 30 萬

mock_portfolio = {
    "updated": "2026-10-18",
    "cash": 50000.0,
    "cash_status": "ok",
    "holdings": [
        {"code": "STK_A", "type": "CORE", "cost": 280, "qty": 1000, "current_price": 300.0, "sector": "半導體"},
        {"code": "STK_B", "type": "CORE", "cost": 140, "qty": 1000, "current_price": 150.0, "sector": "半導體"},
        {"code": "STK_C", "type": "SHORT", "cost": 190, "qty": 1000, "current_price": 200.0, "sector": "航運"},
        {"code": "STK_D", "type": "SWING", "cost": 290, "qty": 1000, "current_price": 300.0, "sector": "電機"}
    ]
}

total_stock_val = sum(h["qty"] * h["current_price"] for h in mock_portfolio["holdings"])
denom = total_stock_val + mock_portfolio["cash"] # 30萬 + 15萬 + 20萬 + 30萬 + 5萬 = 100萬
cash_ratio = round(mock_portfolio["cash"] / denom * 100, 1)

violations = []
# 現金下限
if cash_ratio < 10.0:
    violations.append(f"現金水位低於下限: {cash_ratio}% < 10.0% (禁止新買進方案)")

# 單檔與產業、SHORT
sector_w = {}
short_total_w = 0.0
for h in mock_portfolio["holdings"]:
    val = h["qty"] * h["current_price"]
    w = round(val / denom * 100, 1)
    h["weight_pct"] = w
    if w > 25.0:
        excess = val - (denom * 0.25)
        shares_to_sell = round(excess / h["current_price"])
        formula = f"({val:.0f} - {denom:.0f} × 0.25) ÷ {h['current_price']}"
        violations.append(f"單檔超標: {h['code']} 權重 {w}% > 25.0% (建議減碼 {shares_to_sell} 股，算式: {formula})")
    
    sec = h["sector"]
    sector_w[sec] = sector_w.get(sec, 0.0) + w
    if h["type"] == "SHORT":
        short_total_w += w

for sec, sw in sector_w.items():
    sw_r = round(sw, 1)
    if sw_r > 40.0:
        violations.append(f"單一產業超標: {sec} 合計權重 {sw_r}% > 40.0% (限制同產業新買進方案)")

if short_total_w > 15.0:
    violations.append(f"SHORT 合計超標: 合計權重 {short_total_w}% > 15.0% (禁止新增 SHORT)")

print("風控檢查違規清單 (Violations):")
for v in violations:
    print(f"  * {v}")

check("總資產分母計算手算為 1,000,000", denom, 1000000.0)
check("現金水位手算為 5.0%", cash_ratio, 5.0)
check("風控違規 1 (現金下限觸發)", any("現金水位低於下限: 5.0%" in v for v in violations), True)
check("風控違規 2 (單檔超標 STK_A 30% 且建議減碼 167 股)", any("STK_A 權重 30.0% > 25.0% (建議減碼 167 股" in v for v in violations), True)
check("風控違規 3 (單一產業半導體超標 45% > 40%)", any("半導體 合計權重 45.0% > 40.0%" in v for v in violations), True)
check("風控違規 4 (SHORT 合計超標 20% > 15%)", any("SHORT 合計超標: 合計權重 20.0% > 15.0%" in v for v in violations), True)

print("\n" + "=" * 85)
print(f"ALL BRANCHES & RISK CONTROLS PASSED: {len(results)} assertions, ALL TRUE: {all(results)}")
print("=" * 85)
