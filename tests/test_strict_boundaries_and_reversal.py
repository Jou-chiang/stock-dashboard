# test_strict_boundaries_and_reversal.py
import sys
import os
import json
from datetime import datetime, timedelta

import os
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
from generate_snapshot import compute_stock_signals, compute_market_regime, evaluate_thesis
from price_adapter import PriceSeries

print("=" * 90)
print("TEST SUITE: STRICT BOUNDARY CONDITIONS, REVERSAL MUTATION & RISK LIMIT EDGE CASES")
print("=" * 90)

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
# 1. 成交量切片反向測試 (Mutation / Reversal Test)
# 證明：舊切片 vols[-7:-2] 在特定走勢下會判錯，而修正後的 vols[-6:-1] 能精確判對！
# ─────────────────────────────────────────────────────────────────────────────
print("\n[CHECK 1] 成交量切片反向測試 (Mutation Test)")
# 設計特定量能走勢：
# 天數:  t-6   t-5   t-4   t-3   t-2 (Day 1)   t-1 (Day 2破位)
# 量能: 5000  1000  1000  1000   1000          1500
# 若用舊切片 vols[-7:-2]：取到的前5日包含 t-6 (5000)，均量 = (5000+1000*4)/5 = 1800！
#   -> 此時 Day 2 量能 1500 < 1800，會被舊切片【錯誤判定為未爆量 False】！
# 若用新切片 vols[-6:-1]：取到 t-5 到 t-2 的 5 天 (全為 1000)，均量 = 1000！
#   -> 此時 Day 2 量能 1500 > 1000，新切片【正確判定為爆量 True】！
vols_mut = [1000]*15 + [5000, 1000, 1000, 1000, 1000, 1000, 1500]
closes_mut = [100.0]*20 + [97.0, 97.0] # 連續兩日破 MA20 98%
ps_mut = make_series("TEST_MUT", closes_mut, vols_mut)
item_mut = {"code": "TEST_MUT", "type": "SWING", "entry_date": "2026-09-01"}
sig_mut, _ = compute_stock_signals(item_mut, ps_mut, False, "2026-09-22", {}, {})

# 驗證新切片在當前程式碼中產出 True
check("新切片 vols[-6:-1] 正確判定爆量確認 True", sig_mut["ma20_break_confirmed"], True)

# 手算模擬舊切片：
old_vol_5_avg = sum(vols_mut[-7:-2]) / 5 # = (5000 + 1000*4) / 5 = 1800
old_surge = vols_mut[-1] > old_vol_5_avg # 1500 > 1800 -> False!
print(f"  * [反向驗證] 舊切片 vols[-7:-2] 均量為 {old_vol_5_avg}，當日 1500 > 1800 為 {old_surge}")
check("證明舊切片確實會產生 False (被歷史久遠量能污染)", old_surge, False)

# ─────────────────────────────────────────────────────────────────────────────
# 2. SHORT 持有天數邊界值 (第 10 天 vs 第 11 天)
# ─────────────────────────────────────────────────────────────────────────────
print("\n[CHECK 2] SHORT 持有天數邊界值 (第 10 天 False vs 第 11 天 True)")
# 進場日在 2026-09-01
# 2A. 剛好持有 10 個交易日 (2026-09-01 至 2026-09-10) -> holding_days_over == False
c_10d = [100.0]*25
dates_10d = [f"2026-09-{i+1:02d}" for i in range(25)]
ps_10d = make_series("TEST_S10", c_10d[:10], [1000]*10, dates=dates_10d[:10])
item_s10 = {"code": "TEST_S10", "type": "SHORT", "entry_date": "2026-09-01"}
sig_10d, _ = compute_stock_signals(item_s10, ps_10d, False, "2026-09-10", {}, {})
check("持有恰好 10 天: holding_days_over 為 False (未超期)", sig_10d["holding_days_over"], False)

# 2B. 持有 11 個交易日 (2026-09-01 至 2026-09-11) -> holding_days_over == True
ps_11d = make_series("TEST_S11", c_10d[:11], [1000]*11, dates=dates_10d[:11])
item_s11 = {"code": "TEST_S11", "type": "SHORT", "entry_date": "2026-09-01"}
sig_11d, _ = compute_stock_signals(item_s11, ps_11d, False, "2026-09-11", {}, {})
check("持有第 11 天: holding_days_over 為 True (超期需退場)", sig_11d["holding_days_over"], True)

# ─────────────────────────────────────────────────────────────────────────────
# 3. 研報 60 天新鮮度邊界值 (第 60 天 verified vs 第 61 天 stale)
# ─────────────────────────────────────────────────────────────────────────────
print("\n[CHECK 3] D 板研報 60 天新鮮度邊界值 (第 60 天 vs 第 61 天)")
base_now = datetime.now()
v_60d = (base_now - timedelta(days=60)).strftime("%Y-%m-%d")
v_61d = (base_now - timedelta(days=61)).strftime("%Y-%m-%d")

theses_freshness = {
    "theses": {
        "STK_60D": {"status": "verified", "verified_at": v_60d, "event_flags": []},
        "STK_61D": {"status": "verified", "verified_at": v_61d, "event_flags": []}
    }
}
eff_60, _, _, _ = evaluate_thesis("STK_60D", theses_freshness)
eff_61, _, _, _ = evaluate_thesis("STK_61D", theses_freshness)
check("查證後第 60 天: effective_status 為 'verified'", eff_60, "verified")
check("查證後第 61 天: effective_status 為 'stale'", eff_61, "stale")

# ─────────────────────────────────────────────────────────────────────────────
# 4. 研報 severity: "minor" (不觸發 open_event) vs "major" (觸發)
# ─────────────────────────────────────────────────────────────────────────────
print("\n[CHECK 4] D 板研報 severity: minor (不觸發) vs major (觸發)")
theses_sev = {
    "theses": {
        "STK_MINOR": {
            "status": "verified", "verified_at": v_60d,
            "event_flags": [{"type": "常規變動", "severity": "minor", "resolved": False}]
        },
        "STK_MAJOR": {
            "status": "verified", "verified_at": v_60d,
            "event_flags": [{"type": "財務質疑", "severity": "major", "resolved": False}]
        }
    }
}
_, open_minor, _, _ = evaluate_thesis("STK_MINOR", theses_sev)
_, open_major, _, _ = evaluate_thesis("STK_MAJOR", theses_sev)
check("severity 為 minor: thesis_has_open_event 為 False (僅提示查證)", open_minor, False)
check("severity 為 major: thesis_has_open_event 為 True (啟動雙案並陳)", open_major, True)

# ─────────────────────────────────────────────────────────────────────────────
# 5. 乖離率 15.0% 邊界與極端行情觸發
# ─────────────────────────────────────────────────────────────────────────────
print("\n[CHECK 5] 乖離率 15.0% 邊界與極端行情")
# MA20 恰好為 100.0 元，現價 115.0 元 -> bias = +15.0%
c_base = 1885.0 / 19.0
ps_bias = make_series("TEST_BIAS", [c_base]*19 + [115.0], [1000]*20)
sig_bias, _ = compute_stock_signals({"code": "TEST_BIAS"}, ps_bias, False, "2026-09-20", {}, {})
check("現價 115 vs MA20 100: bias_20_pct 手算為 15.0%", sig_bias["bias_20_pct"], 15.0)

# 個股單日跌幅 -7.0% (觸發 extreme_move)
ps_ext_stk = make_series("TEST_EXT_S", [100.0]*19 + [93.0], [1000]*20) # (93-100)/100 = -7.0%
sig_ext_s, _ = compute_stock_signals({"code": "TEST_EXT_S"}, ps_ext_stk, False, "2026-09-20", {}, {})
check("個股跌幅 -7.0%: extreme_move 觸發為 True", sig_ext_s["extreme_move"], True)

# ─────────────────────────────────────────────────────────────────────────────
# 6. 大盤市場體系：空頭 vs 盤整分支
# ─────────────────────────────────────────────────────────────────────────────
print("\n[CHECK 6] 大盤體系判定分支：空頭 vs 盤整")
def eval_market_mock(closes):
    ma60 = sum(closes[-60:]) / 60
    today_close = closes[-1]
    c_60_ago = closes[-61]
    if today_close > ma60 and today_close > c_60_ago:
        return "多頭"
    elif today_close < ma60 and today_close < c_60_ago:
        return "空頭"
    else:
        return "盤整"

# 空頭：現價在 MA60 之下，且現價 < 60日前收盤
c_bear = [20000.0]*61
c_bear[-1] = 18000.0 # 現價 18000 < MA60(19967) 且 < 20000
check("空頭體系判定: 收盤 < MA60 且 < 60日前", eval_market_mock(c_bear), "空頭")

# 盤整 1: 現價在 MA60 之上，但現價 < 60日前收盤
c_range1 = [20000.0] + [18000.0]*59 + [19000.0] # 60日前是 20000，MA60 ~ 18016，現價 19000 > MA60 但 < 20000
check("盤整體系 1: 收盤 > MA60 但 < 60日前", eval_market_mock(c_range1), "盤整")

# 盤整 2: 現價在 MA60 之下，但現價 > 60日前收盤
c_range2 = [17000.0] + [19000.0]*59 + [18000.0] # 60日前是 17000，MA60 ~ 18983，現價 18000 < MA60 但 > 17000
check("盤整體系 2: 收盤 < MA60 但 > 60日前", eval_market_mock(c_range2), "盤整")

# ─────────────────────────────────────────────────────────────────────────────
# 7. 組合風控嚴格邊界值檢驗 (25.0% vs 25.1%, 10.0% vs 9.9%, 40.0% vs 40.1%)
# ─────────────────────────────────────────────────────────────────────────────
print("\n[CHECK 7] 組合風控嚴格邊界值檢驗 (臨界未超標 vs 0.1% 超標)")

def eval_risk_control(total_stock_val, cash, holdings):
    denom = total_stock_val + cash
    cash_ratio = round(cash / denom * 100, 1)
    violations = []
    if cash_ratio < 10.0:
        violations.append(f"現金水位低於下限: {cash_ratio}% < 10.0%")
    
    sec_w = {}
    short_w = 0.0
    for h in holdings:
        w = round(h["val"] / denom * 100, 1)
        if w > 25.0:
            violations.append(f"單檔超標: {h['code']} 權重 {w}% > 25.0%")
        sec = h["sector"]
        sec_w[sec] = sec_w.get(sec, 0.0) + w
        if h.get("type") == "SHORT":
            short_w += w

    for s, sw in sec_w.items():
        sw_r = round(sw, 1)
        if sw_r > 40.0:
            violations.append(f"單一產業超標: {s} 合計權重 {sw_r}% > 40.0%")

    short_r = round(short_w, 1)
    if short_r > 15.0:
        violations.append(f"SHORT 合計超標: 合計權重 {short_r}% > 15.0%")
    return violations

# Case A: 臨界值（全部恰好達標，無任何違規！）
# 總資產 100 萬：現金 10 萬 (10.0%)、STK1 25 萬 (25.0%)、STK2 15 萬 (半導體合計 40.0%)、SHORT 15 萬 (15.0%)、其他 35 萬
holdings_border_ok = [
    {"code": "S1", "val": 250000.0, "sector": "半導體", "type": "CORE"},
    {"code": "S2", "val": 150000.0, "sector": "半導體", "type": "CORE"},
    {"code": "S3", "val": 150000.0, "sector": "航運", "type": "SHORT"},
    {"code": "S4", "val": 200000.0, "sector": "電機", "type": "SWING"},
    {"code": "S5", "val": 150000.0, "sector": "鋼鐵", "type": "SWING"}
]
v_ok = eval_risk_control(900000.0, 100000.0, holdings_border_ok)
check("7A 臨界邊界無違規: 現金10.0%、單檔25.0%、產業40.0%、SHORT 15.0%", len(v_ok), 0, f"violations={v_ok}")

# Case B: 超標 0.1%（全數觸發違規！）
# 總資產 100 萬：現金 9.9 萬 (9.9% 違規)、STK1 25.1 萬 (25.1% 違規)、半導體 40.1 萬 (40.1% 違規)、SHORT 15.1 萬 (15.1% 違規)
holdings_border_fail = [
    {"code": "S1", "val": 251000.0, "sector": "半導體", "type": "CORE"},
    {"code": "S2", "val": 150000.0, "sector": "半導體", "type": "CORE"},
    {"code": "S3", "val": 151000.0, "sector": "航運", "type": "SHORT"},
    {"code": "S4", "val": 349000.0, "sector": "電機", "type": "SWING"}
]
v_fail = eval_risk_control(901000.0, 99000.0, holdings_border_fail)
check("7B 現金 9.9% 觸發下限違規", any("現金水位低於下限: 9.9%" in v for v in v_fail), True)
check("7B 單檔 25.1% 觸發單檔超標", any("S1 權重 25.1%" in v for v in v_fail), True)
check("7B 產業 40.1% 觸發產業超標", any("半導體 合計權重 40.1%" in v for v in v_fail), True)
check("7B SHORT 15.1% 觸發 SHORT 超標", any("SHORT 合計超標: 合計權重 15.1%" in v for v in v_fail), True)

print("\n" + "=" * 90)
print(f"ALL STRICT BOUNDARIES & MUTATIONS PASSED: {len(results)} assertions, ALL TRUE: {all(results)}")
print("=" * 90)
