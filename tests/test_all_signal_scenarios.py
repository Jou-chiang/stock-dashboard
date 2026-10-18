# test_all_signal_scenarios.py
import sys
import os
import json
from datetime import datetime

import os
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
from generate_snapshot import compute_stock_signals
from price_adapter import PriceSeries

print("=" * 85)
print("TEST SUITE: COMPREHENSIVE SIGNAL LOGIC & EDGE-CASE VERIFICATION (8 SCENARIOS)")
print("=" * 85)

# Helper to build mock PriceSeries
def make_mock_series(code, closes, vols, dates=None, events=None, price_basis="adjusted"):
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

results = []
def check(desc, actual, expected, detail=""):
    match = (actual == expected)
    results.append(match)
    flag = "[PASS]" if match else "[FAIL]"
    print(f"  {flag} {desc}")
    print(f"        手算預期 (Expected): {expected}")
    print(f"        腳本輸出 (Actual)  : {actual}" + (f" | {detail}" if detail else ""))
    assert match, f"Mismatch in {desc}"

# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO 1 & 2: SWING 連 2 日破 MA20 有量 (Confirmed) vs 無量 (Not confirmed)
# ─────────────────────────────────────────────────────────────────────────────
print("\n[SCENARIO 1 & 2] SWING MA20 破位確認 (有量 vs 無量)")
# 建立 25 天 K 線：前 20 天收在 100 左右 (MA20 ~ 100, 98% = 98)
# 前 5 日均量 (vol[-7:-2]) 為 1000 張
closes_base = [100.0] * 20
vols_base = [1000] * 20

# Case 1: 有量破位 (連 2 日收在 97 < 98，第二日成交量 2000 > 1000)
c_surge = closes_base + [100.0, 100.0, 100.0, 97.0, 96.0]
v_surge = vols_base + [1000, 1000, 1000, 1200, 2500]  # 最後一日 2500 > 均量 1000
ps_surge = make_mock_series("TEST_SW1", c_surge, v_surge)
item_sw1 = {"code": "TEST_SW1", "type": "SWING", "entry_date": "2026-09-01"}
sig1, df1 = compute_stock_signals(item_sw1, ps_surge, False, "2026-09-25", {}, {})

check("Case 1 (有量破位): ma20_break_confirmed 為 True", sig1["ma20_break_confirmed"], True)

# Case 2: 無量破位 (連 2 日收在 97 < 98，但第二日成交量 600 < 1000 均量)
c_shrink = closes_base + [100.0, 100.0, 100.0, 97.0, 96.0]
v_shrink = vols_base + [1000, 1000, 1000, 800, 600]   # 最後一日 600 < 均量 1000
ps_shrink = make_mock_series("TEST_SW2", c_shrink, v_shrink)
item_sw2 = {"code": "TEST_SW2", "type": "SWING", "entry_date": "2026-09-01"}
sig2, df2 = compute_stock_signals(item_sw2, ps_shrink, False, "2026-09-25", {}, {})

check("Case 2 (無量破位): ma20_break_confirmed 為 False", sig2["ma20_break_confirmed"], False)

# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO 3: 停損與停利觸發 (stop_hit & take_profit_hit)
# ─────────────────────────────────────────────────────────────────────────────
print("\n[SCENARIO 3] 手填停損與停利判定")
# 收盤價 90 元，停損設 92 元，停利設 110 元
ps_stop = make_mock_series("TEST_STOP", [100.0]*20 + [90.0], [1000]*21)
item_stop = {
    "code": "TEST_STOP", "type": "SWING", "entry_date": "2026-09-01",
    "stop_loss_price": 92.0, "take_profit_target": 110.0, "invalidation_price": 88.0
}
sig3, df3 = compute_stock_signals(item_stop, ps_stop, False, "2026-09-21", {}, {})

check("stop_hit 觸發 (收盤 90 < 停損 92)", sig3["stop_hit"], True)
check("invalidation_hit 未觸發 (收盤 90 > 失效 88)", sig3["invalidation_hit"], False)
check("take_profit_hit 未觸發 (收盤 90 < 停利 110)", sig3["take_profit_hit"], False)

# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO 4: 已階段停利後之移動防守 (partial_profit_taken == True) vs 不適用
# ─────────────────────────────────────────────────────────────────────────────
print("\n[SCENARIO 4] 移動防守 trailing_stop 與狀態區分")
# SWING: 進場後最高 120 元，MA20 為 100 元。
# 預期 trailing_stop = max(MA20, 120 * 0.92) = max(100, 110.4) = 110.4 元
# 現價 108 元 < 110.4 元 -> trailing_stop_hit = True
closes_ts = [100.0]*15 + [115.0, 120.0, 118.0, 112.0, 108.0]
ps_ts = make_mock_series("TEST_TS", closes_ts, [1000]*len(closes_ts))

# 4A. partial_profit_taken == True
item_ts_active = {
    "code": "TEST_TS", "type": "SWING", "entry_date": "2026-09-01",
    "partial_profit_taken": True
}
sig4a, df4a = compute_stock_signals(item_ts_active, ps_ts, False, "2026-09-20", {}, {})
check("4A trailing_stop 手算為 max(MA20, 120*0.92) = 110.4", sig4a["trailing_stop"], 110.4)
check("4A trailing_stop_hit 為 True (現價 108 < 110.4)", sig4a["trailing_stop_hit"], True)
check("4A trailing_stop_status 為 'active'", sig4a["trailing_stop_status"], "active")

# 4B. partial_profit_taken == False (不適用)
item_ts_na = {
    "code": "TEST_TS", "type": "SWING", "entry_date": "2026-09-01",
    "partial_profit_taken": False
}
sig4b, df4b = compute_stock_signals(item_ts_na, ps_ts, False, "2026-09-20", {}, {})
check("4B 未階段停利時 trailing_stop 為 None", sig4b["trailing_stop"], None)
check("4B 未階段停利時 trailing_stop_hit 為 None", sig4b["trailing_stop_hit"], None)
check("4B trailing_stop_status 為 'not_applicable' (非資料不足)", sig4b["trailing_stop_status"], "not_applicable")

# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO 5: CORE 連續 10 日跌破 MA60 (core_deep_drawdown == True)
# ─────────────────────────────────────────────────────────────────────────────
print("\n[SCENARIO 5] CORE 連續 10 日跌破 MA60")
# 建立 70 天資料，MA60 ~ 100 元，最後 10 天皆收在 95 元 (< 100)
c_c60 = [100.0]*60 + [95.0]*10
ps_c60 = make_mock_series("TEST_CORE", c_c60, [1000]*len(c_c60))
item_core = {"code": "TEST_CORE", "type": "CORE", "entry_date": "2026-09-01"}
sig5, df5 = compute_stock_signals(item_core, ps_c60, False, "2026-09-30", {}, {})
check("CORE 連 10 日破季線觸發 core_deep_drawdown 為 True", sig5["core_deep_drawdown"], True)

# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO 6: SWING 除權息防呆 (ex_dividend_check == True 鎖定手填價位)
# ─────────────────────────────────────────────────────────────────────────────
print("\n[SCENARIO 6] SWING 除權息防呆鎖定")
# 事件日在 2026-09-15，進場日在 2026-09-01，price_levels_updated_at 為空
ev_div = [{"date": "2026-09-15", "type": "dividend", "factor": 0.95}]
ps_div = make_mock_series("TEST_DIV", [100.0]*25, [1000]*25, events=ev_div)
item_sw_div = {
    "code": "TEST_DIV", "type": "SWING", "entry_date": "2026-09-01",
    "stop_loss_price": 95.0, "price_levels_updated_at": None
}
sig6, df6 = compute_stock_signals(item_sw_div, ps_div, False, "2026-09-25", {}, {})
check("SWING 遇除權息且未更新價位: ex_dividend_check 為 True", sig6["ex_dividend_check"], True)
check("SWING ex_dividend_check 作用下 stop_hit 強制輸出 None", sig6["stop_hit"], None)
check("SWING ex_dividend_check 作用下 take_profit_hit 強制輸出 None", sig6["take_profit_hit"], None)
check("SWING 包含 ex_dividend_check_active 旗標", "ex_dividend_check_active" in df6, True)

# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO 7: CORE 排除除權息防呆 (CORE 不受 ex_dividend_check 影響)
# ─────────────────────────────────────────────────────────────────────────────
print("\n[SCENARIO 7] CORE 嚴格排除除權息鎖定")
item_core_div = {
    "code": "TEST_DIV", "type": "CORE", "entry_date": "2026-09-01",
    "price_levels_updated_at": None
}
sig7, df7 = compute_stock_signals(item_core_div, ps_div, False, "2026-09-25", {}, {})
check("CORE 之 ex_dividend_check 嚴格為 False", sig7["ex_dividend_check"], False)
check("CORE 均線照常輸出 (MA20 不受手填價位影響)", sig7["ma20"] is not None, True)
check("CORE 不含 ex_dividend_check_active 旗標", "ex_dividend_check_active" not in df7, True)

# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO 8: 進場日 (entry_date) 為空之零虛構驗證
# ─────────────────────────────────────────────────────────────────────────────
print("\n[SCENARIO 8] 進場日 entry_date 為空之零虛構防呆")
item_no_entry = {
    "code": "TEST_NO_ENTRY", "type": "SHORT", "entry_date": None
}
ps_no_entry = make_mock_series("TEST_NO_ENTRY", [100.0]*25, [1000]*25)
sig8, df8 = compute_stock_signals(item_no_entry, ps_no_entry, False, "2026-09-25", {}, {})
check("進場日為空時 max_close_since_entry 嚴格為 None", sig8["max_close_since_entry"], None)
check("SHORT 進場日為空時 holding_days_over 嚴格為 None (非 False)", sig8["holding_days_over"], None)
check("進場日為空時正確標註 entry_date_missing 旗標", "entry_date_missing" in df8, True)

# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO 9: D 研報草稿狀態不洩漏 bull_ceiling
# ─────────────────────────────────────────────────────────────────────────────
print("\n[SCENARIO 9] D 板研報草稿狀態遮蔽樂觀上緣 (bull_ceiling)")
theses_draft_fixture = {
    "theses": {
        "TEST_DRAFT": {
            "status": "draft",
            "consensus_forecast": {
                "2026_eps_range": [10.0, 12.0],
                "target_pe_range": [20.0, 25.0]
            }
        }
    }
}
item_draft = {"code": "TEST_DRAFT", "type": "CORE", "entry_date": "2026-09-01"}
sig9, df9 = compute_stock_signals(item_draft, ps_no_entry, False, "2026-09-25", theses_draft_fixture, {})
check("D 板為 draft 狀態時 bull_ceiling 嚴格為 None (不洩漏 300)", sig9["bull_ceiling"], None)
check("D 板為 draft 狀態時 price_vs_bull_ceiling 嚴格為 None", sig9["price_vs_bull_ceiling"], None)

# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO 10: 籌碼資料不足時 chip_diagnosis 嚴格為 None
# ─────────────────────────────────────────────────────────────────────────────
print("\n[SCENARIO 10] 籌碼資料不足時 chip_diagnosis 輸出 None")
sig10, df10 = compute_stock_signals(item_draft, ps_no_entry, False, "2026-09-25", {}, tdcc_data={})
check("缺少集保資料時 chip_diagnosis 嚴格為 None (非 divergent_dir)", sig10["chip_diagnosis"], None)
check("缺少籌碼資料時正確標註 chip_data_insufficient", "chip_data_insufficient" in df10, True)

print("\n" + "=" * 85)
print(f"TEST SUMMARY: {len(results)} tests executed. ALL PASSED: {all(results)}")
print("=" * 85)
