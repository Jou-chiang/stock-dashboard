"""
generate_snapshot.py
L2 確定性彙整引擎（Deterministic Snapshot Engine）
版本：對齊架構與規格書 v3.3（實作凍結版 - 嚴格無虛構修訂）

修訂重點：
1. 進場日 (entry_date) 為空時：
   - max_close_since_entry 嚴格輸出 None。
   - holding_days_over 嚴格輸出 None。
   - core_deep_drawdown 若無連續 10 日破季線則輸出 None，絕不假裝已完成回落計算。
2. 區分 trailing_stop 之「不適用」與「資料不足」：
   - 增加 trailing_stop_status ("not_applicable" | "active" | "data_insufficient")。
3. 嚴防草稿估值洩漏：
   - bull_ceiling 僅在 thesis_effective_status == "verified" 時輸出，草稿一律為 None。
4. 籌碼診斷嚴格化：
   - 缺少法人或集保資料時 chip_diagnosis 輸出 None，絕不以 "divergent_dir" 充數。
5. 補齊資料日期與新鮮度旗標：
   - 每檔包含 price_basis, price_date, price_stale, inst_date, inst_stale, tdcc_date, tdcc_stale。
"""

import os
import sys
import json
import csv
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple

from price_adapter import load_price_adapter, PriceSeries

# ── 設定檔與相依檔案路徑 ───────────────────────────────────────
BASE_DIR          = os.path.dirname(os.path.abspath(__file__))
PORTFOLIO_FILE    = os.path.join(BASE_DIR, "my_portfolio.json")
CONFIG_FILE       = os.path.join(BASE_DIR, "config.json")
THESES_FILE       = os.path.join(BASE_DIR, "research_theses.json")
TDCC_FILE         = os.path.join(BASE_DIR, "tdcc_data.json")
SNAPSHOT_FILE     = os.path.join(BASE_DIR, "snapshot.json")

FINMIND_URL       = "https://api.finmindtrade.com/api/v4/data"
TOKEN             = os.environ.get("FINMIND_TOKEN", "")

api_call_tracker = 0

def fetch_finmind(dataset: str, data_id: Optional[str] = None, start_date: str = "2026-05-01") -> List[Dict]:
    global api_call_tracker
    api_call_tracker += 1
    params = {"dataset": dataset, "start_date": start_date}
    if data_id:
        params["data_id"] = data_id
    if TOKEN:
        params["token"] = TOKEN
    url = f"{FINMIND_URL}?" + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return data.get("data", [])
    except Exception as e:
        print(f"  [API WARN] Failed to fetch {dataset} ({data_id}): {e}")
        return []

# ── 1. 大盤環境計算 (Market Regime & Extreme Move) ─────────────
def compute_market_regime() -> Tuple[Dict[str, Any], bool]:
    start_d = (datetime.today() - timedelta(days=120)).strftime("%Y-%m-%d")
    rows = fetch_finmind("TaiwanStockPrice", data_id="TAIEX", start_date=start_d)
    if not rows or len(rows) < 61:
        return {
            "regime": "盤整",
            "close": None,
            "ma60": None,
            "day_change_pct": 0.0,
            "date": None,
            "data_status": "insufficient_market_data"
        }, False

    rows.sort(key=lambda x: x["date"])
    closes = [float(r["close"]) for r in rows if r.get("close") is not None]
    today_close = closes[-1]
    prev_close = closes[-2]
    day_change_pct = round((today_close - prev_close) / prev_close * 100, 2)

    ma60 = round(sum(closes[-60:]) / 60, 2)
    close_60_ago = closes[-61]

    if today_close > ma60 and today_close > close_60_ago:
        regime = "多頭"
    elif today_close < ma60 and today_close < close_60_ago:
        regime = "空頭"
    else:
        regime = "盤整"

    market_extreme = (day_change_pct <= -3.0)

    market_meta = {
        "regime": regime,
        "close": today_close,
        "ma60": ma60,
        "day_change_pct": day_change_pct,
        "date": rows[-1]["date"]
    }
    return market_meta, market_extreme

# ── 2. 法人與籌碼診斷計算 (Chip Diagnosis) ─────────────────────
def compute_chip_diagnosis(
    code: str,
    tdcc_data_map: Dict,
    recent_close_high: bool,
    latest_market_date: Optional[str]
) -> Tuple[Optional[str], Optional[str], bool, Optional[str], bool]:
    """
    客觀三態診斷：
    - 資料不足時一律輸出 None，絕不預設為 "divergent_dir"
    - improving：千張大戶持股比例上升 ＋ 散戶持股/人數下降 ＋ 近 5 日法人合計買超
    - structural_divergence：股價近波段高點，但千張大戶比例下滑 ＋ 散戶持股/人數上升
    - divergent_dir：資料完整，但方向分歧或無顯著集中現象
    回傳: (diagnosis, inst_date, inst_stale, tdcc_date, tdcc_stale)
    """
    stock_tdcc = tdcc_data_map.get(code, {})
    latest_tdcc = stock_tdcc.get("latest")

    start_d = (datetime.today() - timedelta(days=20)).strftime("%Y-%m-%d")
    inst_rows = fetch_finmind("TaiwanStockInstitutionalInvestorsBuySell", data_id=code, start_date=start_d)

    inst_date = None
    inst_stale = True
    inst_5d_net = 0.0

    if inst_rows:
        inst_rows.sort(key=lambda x: x.get("date", ""))
        inst_date = inst_rows[-1].get("date")
        if latest_market_date and inst_date:
            inst_stale = (inst_date < latest_market_date)

        inst_by_date = {}
        for r in inst_rows:
            d = r.get("date")
            net = float(r.get("buy", 0)) - float(r.get("sell", 0))
            inst_by_date[d] = inst_by_date.get(d, 0.0) + net
        sorted_dates = sorted(inst_by_date.keys())
        last_5_dates = sorted_dates[-5:] if len(sorted_dates) >= 5 else sorted_dates
        inst_5d_net = sum(inst_by_date[d] for d in last_5_dates) / 1000.0

    tdcc_date = None
    tdcc_stale = True
    if latest_tdcc and latest_tdcc.get("date"):
        raw_d = str(latest_tdcc.get("date"))
        if len(raw_d) == 8:
            tdcc_date = f"{raw_d[:4]}-{raw_d[4:6]}-{raw_d[6:]}"
        else:
            tdcc_date = raw_d
        try:
            t_dt = datetime.strptime(tdcc_date, "%Y-%m-%d")
            tdcc_stale = ((datetime.now() - t_dt).days > 8)
        except ValueError:
            pass

    # 若任一關鍵籌碼來源完全無資料，判定為資料不足 (None)
    if not latest_tdcc or not inst_rows:
        return None, inst_date, inst_stale, tdcc_date, tdcc_stale

    over1000_pct_chg = latest_tdcc.get("over1000_pct_chg", 0.0) or 0.0
    retail_pct_chg   = latest_tdcc.get("retail_pct_chg", 0.0) or 0.0
    retail_ppl_chg   = latest_tdcc.get("over1000_people_chg", 0) or 0

    is_improving = (over1000_pct_chg > 0 and (retail_pct_chg < 0 or retail_ppl_chg < 0) and inst_5d_net > 0)
    is_divergence = (recent_close_high and over1000_pct_chg < 0 and (retail_pct_chg > 0 or retail_ppl_chg > 0))

    if is_improving:
        diag = "improving"
    elif is_divergence:
        diag = "structural_divergence"
    else:
        diag = "divergent_dir"

    return diag, inst_date, inst_stale, tdcc_date, tdcc_stale

# ── 3. 研報狀態計算 (D Panel Thesis) ──────────────────────────
def evaluate_thesis(code: str, theses_data: Dict) -> Tuple[str, bool, Optional[float], Dict[str, Any]]:
    """
    評估 D 板研究卡片：
    - bull_ceiling 僅在 verified 時暴露，草稿或過期時強制輸出 None 避免 Gem 幻覺
    - 未解事件之 severity 缺漏時預設為 'major'
    """
    item = theses_data.get("theses", {}).get(code)
    if not item:
        return "draft", False, None, {"status": "none"}

    status = item.get("status", "draft")
    verified_at_str = item.get("verified_at")
    event_flags = item.get("event_flags", [])

    has_open_major_event = False
    for ev in event_flags:
        if not ev.get("resolved", False):
            sev = ev.get("severity", "major")
            if sev != "minor":
                has_open_major_event = True
                break

    is_verified_active = False
    if status == "verified" and verified_at_str:
        try:
            v_date = datetime.strptime(verified_at_str[:10], "%Y-%m-%d")
            days_diff = (datetime.now() - v_date).days
            if days_diff <= 60 and not has_open_major_event:
                is_verified_active = True
        except ValueError:
            pass

    if is_verified_active:
        eff_status = "verified"
    elif status == "draft":
        eff_status = "draft"
    else:
        eff_status = "stale"

    # 樂觀估值上緣：僅在 verified 狀態下暴露，草稿或過期狀態一律為 None
    bull_ceiling = None
    if eff_status == "verified":
        forecast = item.get("consensus_forecast", {})
        eps_range = forecast.get("2026_eps_range")
        pe_range = forecast.get("target_pe_range")
        if eps_range and pe_range and len(eps_range) >= 2 and len(pe_range) >= 2:
            if eps_range[1] is not None and pe_range[1] is not None:
                bull_ceiling = round(float(eps_range[1]) * float(pe_range[1]), 2)

    return eff_status, has_open_major_event, bull_ceiling, item

# ── 4. 單檔訊號計算管線 (Section IV Signals) ───────────────────
def compute_stock_signals(
    item: Dict[str, Any],
    p_series: PriceSeries,
    market_extreme: bool,
    latest_market_date: Optional[str],
    theses_data: Dict,
    tdcc_data: Dict,
    taiex_regime: str = "盤整"
) -> Tuple[Dict[str, Any], List[str]]:
    data_flags = []
    signals: Dict[str, Any] = {}

    code = item["code"]
    st_type = item.get("type")
    entry_date = item.get("entry_date")
    cost = item.get("cost")
    stop_loss_price = item.get("stop_loss_price")
    invalidation_price = item.get("invalidation_price")
    take_profit_target = item.get("take_profit_target")
    partial_profit_taken = bool(item.get("partial_profit_taken"))
    price_levels_updated_at = item.get("price_levels_updated_at")

    # 1. 價格基礎與新鮮度
    if not p_series.rows:
        data_flags.append("price_data_missing")
        return signals, data_flags

    curr_p = p_series.latest_close
    signals["current_price"] = curr_p
    closes = p_series.closes
    vols = [float(r.get("volume", 0)) for r in p_series.rows]

    price_date = p_series.rows[-1]["date"]
    price_stale = (price_date < latest_market_date) if (price_date and latest_market_date) else False
    if price_stale:
        data_flags.append("price_stale")

    signals["price_date"] = price_date
    signals["price_stale"] = price_stale
    signals["price_basis"] = p_series.price_basis

    # 日漲跌幅
    if len(closes) >= 2 and closes[-2] > 0:
        day_chg_pct = round((closes[-1] - closes[-2]) / closes[-2] * 100, 2)
    else:
        day_chg_pct = 0.0
    signals["day_change_pct"] = day_chg_pct

    # 極端行情判定
    signals["extreme_move"] = (day_chg_pct <= -7.0 or market_extreme)

    # 2. 除權息防呆判定 (ex_dividend_check)
    # 嚴格守則：僅在有手動設定防守價位（停損/失效/停利）時才需檢查是否失準；未設價位者不受除權息標記干擾
    ex_div_check = False
    has_manual_price_levels = any([stop_loss_price, invalidation_price, take_profit_target])
    if st_type in ("SWING", "SHORT") and has_manual_price_levels:
        for ev in p_series.events:
            ev_date = ev.get("date")
            is_subsequent = False
            if entry_date:
                is_subsequent = (ev_date > entry_date)
            else:
                is_subsequent = True

            if is_subsequent:
                if not price_levels_updated_at or price_levels_updated_at <= ev_date:
                    ex_div_check = True
                    break

    signals["ex_dividend_check"] = ex_div_check
    if ex_div_check:
        data_flags.append("ex_dividend_check_active")

    # 3. 均線與進場後最高價計算
    ma5 = p_series.get_ma(5)
    ma20 = p_series.get_ma(20)
    ma60 = p_series.get_ma(60)

    signals["ma5"] = ma5
    signals["ma20"] = ma20
    signals["ma60"] = ma60

    # 零虛構原則：進場日為空時，max_close_since_entry 嚴格為 None！
    if entry_date and p_series.is_valid_for_ma:
        max_since_entry = p_series.get_max_close_since(entry_date)
    else:
        max_since_entry = None
        if not entry_date:
            data_flags.append("entry_date_missing")

    signals["max_close_since_entry"] = max_since_entry

    if not p_series.is_valid_for_ma:
        data_flags.append("unadjusted_price_ma_disabled")
        signals["below_ma20"] = None
        signals["below_ma60"] = None
        signals["bias_20_pct"] = None
        signals["ma20_break_confirmed"] = False
        signals["core_deep_drawdown"] = None
        signals["trailing_stop"] = None
        signals["trailing_stop_hit"] = None
        signals["trailing_stop_status"] = "data_insufficient"
    else:
        signals["below_ma20"] = (curr_p < ma20) if (curr_p and ma20) else None
        signals["below_ma60"] = (curr_p < ma60) if (curr_p and ma60) else None
        signals["bias_20_pct"] = round((curr_p - ma20) / ma20 * 100, 1) if (curr_p and ma20) else None

        # ma20_break_confirmed：連 2 日收盤 < MA20 × 98%，且第二日量 > 前 5 日均量
        # 嚴格排除當日（第二日 vols[-1]）：取第二日前 5 個交易日均量（vols[-6:-1]）
        break_confirmed = False
        if len(closes) >= 2 and ma20 and len(vols) >= 6:
            day1_break = closes[-2] < (ma20 * 0.98)
            day2_break = closes[-1] < (ma20 * 0.98)
            vol_5_avg = sum(vols[-6:-1]) / 5
            vol_surge = vols[-1] > vol_5_avg
            break_confirmed = (day1_break and day2_break and vol_surge)
        signals["ma20_break_confirmed"] = break_confirmed

        # CORE ETF 加碼觀察指標 (0% ~ +3% 貼近季線且未破，限大盤多頭)
        s_name = item.get("name", "")
        is_etf = code.startswith("00")
        is_bond_or_lev = ("美債" in s_name or "正2" in s_name or "反1" in s_name or "債" in s_name)
        if st_type == "CORE" and is_etf and not is_bond_or_lev and ma60 and curr_p:
            dist_ma60_pct = round((curr_p - ma60) / ma60 * 100, 2)
            signals["etf_dist_ma60_pct"] = dist_ma60_pct
            signals["core_etf_accumulate_watch"] = bool(0.0 <= dist_ma60_pct <= 3.0 and taiex_regime == "多頭")
        else:
            signals["etf_dist_ma60_pct"] = None
            signals["core_etf_accumulate_watch"] = False

        # core_deep_drawdown：連續 10 個交易日收盤 < MA60，或回落 20% 以上
        if st_type == "CORE":
            below_10 = False
            if len(closes) >= 10 and ma60:
                below_10 = all(c < ma60 for c in closes[-10:])
            
            if max_since_entry and curr_p:
                dd_pct = (curr_p - max_since_entry) / max_since_entry
                dd_20 = (dd_pct <= -0.20)
                signals["core_deep_drawdown"] = (below_10 or dd_20)
            elif below_10:
                # 即使 entry_date 為空，若客觀收盤已連續 10 日破季線，依然確定觸發
                signals["core_deep_drawdown"] = True
            else:
                # 尚未連續 10 日破季線，且因缺進場日無法計算回落 20%，嚴格輸出 None！
                signals["core_deep_drawdown"] = None
                data_flags.append("drawdown_calc_impossible_missing_entry_date")
        else:
            signals["core_deep_drawdown"] = None

        # trailing_stop (移動防守)：清楚區分「不適用」與「資料不足」
        if not partial_profit_taken:
            signals["trailing_stop"] = None
            signals["trailing_stop_hit"] = None
            signals["trailing_stop_status"] = "not_applicable"
        else:
            if max_since_entry:
                trailing_stop_val = None
                if st_type in ("SWING", "SHORT") and ma20:
                    trailing_stop_val = round(max(ma20, max_since_entry * 0.92), 2)
                elif st_type == "CORE" and ma60:
                    trailing_stop_val = round(max(ma60, max_since_entry * 0.85), 2)
                
                signals["trailing_stop"] = trailing_stop_val
                signals["trailing_stop_hit"] = (curr_p < trailing_stop_val) if (trailing_stop_val and curr_p) else None
                signals["trailing_stop_status"] = "active" if trailing_stop_val else "data_insufficient"
            else:
                # 已階段停利但缺進場日無法算最高價，標註資料不足
                signals["trailing_stop"] = None
                signals["trailing_stop_hit"] = None
                signals["trailing_stop_status"] = "data_insufficient"
                data_flags.append("trailing_stop_impossible_missing_entry_date")

    # 4. 手填價位觸發 (stop_hit, invalidation_hit, take_profit_hit)
    if ex_div_check or curr_p is None:
        signals["stop_hit"] = None
        signals["invalidation_hit"] = None
        signals["take_profit_hit"] = None
    else:
        signals["stop_hit"] = (curr_p < stop_loss_price) if stop_loss_price else None
        signals["invalidation_hit"] = (curr_p < invalidation_price) if invalidation_price else None
        signals["take_profit_hit"] = (curr_p >= take_profit_target) if take_profit_target else None

    # 5. 短線成本停損與動能 (SHORT)
    if st_type == "SHORT":
        # 成本 8% 硬停損
        if cost and curr_p:
            signals["short_cost_stop_hit"] = (curr_p < cost * 0.92)
        else:
            signals["short_cost_stop_hit"] = None

        if entry_date:
            days_held = len([r for r in p_series.rows if r["date"] >= entry_date])
            signals["holding_days_over"] = (days_held > 10)
        else:
            signals["holding_days_over"] = None

        if len(closes) >= 2 and len(vols) >= 2 and ma5:
            if curr_p > ma5 and vols[-1] > vols[-2]:
                mom = "bullish"
            elif curr_p < ma5:
                mom = "bearish"
            else:
                mom = "neutral"
        else:
            mom = "neutral"
        signals["short_momentum"] = mom
    else:
        signals["short_cost_stop_hit"] = None
        signals["holding_days_over"] = None
        signals["short_momentum"] = "neutral"

    # 6. D 研報關聯
    eff_status, has_open_event, bull_ceiling, thesis_raw = evaluate_thesis(code, theses_data)
    signals["thesis_effective_status"] = eff_status
    signals["thesis_has_open_event"] = has_open_event
    signals["bull_ceiling"] = bull_ceiling

    p_vs_bull = None
    if eff_status == "verified" and bull_ceiling and curr_p:
        p_vs_bull = round((curr_p - bull_ceiling) / bull_ceiling * 100, 1)
    signals["price_vs_bull_ceiling"] = p_vs_bull

    # 7. 籌碼診斷 (chip_diagnosis) 與新鮮度
    recent_high = False
    if len(closes) >= 20 and curr_p:
        h20 = max(closes[-20:])
        recent_high = (curr_p >= h20 * 0.97)

    chip_diag, inst_date, inst_stale, tdcc_date, tdcc_stale = compute_chip_diagnosis(
        code, tdcc_data, recent_high, latest_market_date
    )
    signals["chip_diagnosis"] = chip_diag
    signals["inst_date"] = inst_date
    signals["inst_stale"] = inst_stale
    signals["tdcc_date"] = tdcc_date
    signals["tdcc_stale"] = tdcc_stale

    if chip_diag is None:
        data_flags.append("chip_data_insufficient")
    if inst_stale:
        data_flags.append("inst_stale")
    if tdcc_stale:
        data_flags.append("tdcc_stale")

    return signals, data_flags

# ── 5. 主程式與組合風控 (Main Pipeline) ────────────────────────
def generate_snapshot():
    print("=" * 70)
    print("開始執行 L2 確定性彙整引擎 (generate_snapshot.py)")
    print("=" * 70)

    # 1. 現場重算價格還原
    print("[1/5] 執行價格還原程式 (generate_adjusted_history.py)...")
    if os.environ.get("SKIP_GEN_ADJ") != "1":
        import generate_adjusted_history
        generate_adjusted_history.main()
    else:
        print("  * 偵測到 SKIP_GEN_ADJ=1，沿用現有 history_data_adj.csv 避免浪費 API 額度")

    # 2. 讀取帳本配置與研究資料
    print("\n[2/5] 讀取帳本配置與研究資料...")
    with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
        pf_data = json.load(f)
    
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)

    theses_data = {}
    if os.path.exists(THESES_FILE):
        with open(THESES_FILE, "r", encoding="utf-8") as f:
            theses_data = json.load(f)

    tdcc_data = {}
    if os.path.exists(TDCC_FILE):
        with open(TDCC_FILE, "r", encoding="utf-8") as f:
            tdcc_data = json.load(f).get("data", {})

    # 3. 計算大盤環境
    print("[3/5] 計算大盤環境指標 (TAIEX)...")
    market_meta, market_extreme = compute_market_regime()
    taiex_date = market_meta.get("date")
    print(f"  * 加權指數體系: {market_meta.get('regime')} (收盤: {market_meta.get('close')}, 日漲跌: {market_meta.get('day_change_pct')}%, 日期: {taiex_date})")

    # 4. 逐檔持股訊號計算
    print("[4/5] 逐檔計算持股訊號與客觀事實...")
    raw_holdings = pf_data.get("holdings", [])
    processed_holdings = []
    
    total_stock_value = 0.0
    has_valid_valuation = True

    for h in raw_holdings:
        code = str(h.get("code", "")).strip()
        name = h.get("name", "")
        p_series = load_price_adapter(code, base_dir=BASE_DIR, prefer_adjusted=True)

        signals, data_flags = compute_stock_signals(
            h, p_series, market_extreme, taiex_date, theses_data, tdcc_data, market_meta.get("regime", "盤整")
        )
        curr_p = signals.get("current_price")

        # 成本與損益計算防呆
        cost = h.get("cost")
        qty = h.get("qty")
        pnl_pct = None
        if cost and cost > 0 and curr_p:
            pnl_pct = round((curr_p - cost) / cost * 100, 2)

        if cost is None or qty is None:
            data_flags.append("cost_or_qty_missing")
            has_valid_valuation = False
        else:
            if curr_p:
                total_stock_value += curr_p * qty

        hold_entry = {
            "code": code,
            "name": name,
            "type": h.get("type"),
            "entry_date": h.get("entry_date"),
            "shares_original": h.get("shares_original"),
            "qty": qty,
            "cost": cost,
            "current_price": curr_p,
            "day_change_pct": signals.get("day_change_pct"),
            "pnl_pct": pnl_pct,
            "weight_pct": None,
            "stop_loss_price": h.get("stop_loss_price"),
            "invalidation_price": h.get("invalidation_price"),
            "take_profit_target": h.get("take_profit_target"),
            "partial_profit_taken": bool(h.get("partial_profit_taken")),
            "ex_dividend_check": signals.get("ex_dividend_check", False),
            "price_levels_updated_at": h.get("price_levels_updated_at"),
            "price_basis": signals.get("price_basis"),
            "price_date": signals.get("price_date"),
            "signals": signals,
            "d_thesis": {
                "effective_status": signals.get("thesis_effective_status"),
                "has_open_event": signals.get("thesis_has_open_event"),
                "bull_ceiling": signals.get("bull_ceiling"),
                "price_vs_bull_ceiling": signals.get("price_vs_bull_ceiling")
            },
            "chips": {
                "diagnosis": signals.get("chip_diagnosis"),
                "inst_date": signals.get("inst_date"),
                "tdcc_date": signals.get("tdcc_date")
            },
            "data_flags": sorted(list(set(data_flags)))
        }
        processed_holdings.append(hold_entry)

    # 建立產業對應表
    sector_map = {}
    if os.path.exists(os.path.join(BASE_DIR, "history_data.csv")):
        try:
            with open(os.path.join(BASE_DIR, "history_data.csv"), "r", encoding="utf-8-sig") as f:
                for r in csv.DictReader(f):
                    c = str(r.get("code", "")).strip()
                    if c and r.get("sector") and c not in sector_map:
                        sector_map[c] = r["sector"]
        except Exception:
            pass

    for h in processed_holdings:
        h["sector"] = sector_map.get(h["code"], "未分類")

    # 5. 組合風控與權重計算 (Portfolio Risk - Section VI)
    print("[5/5] 計算組合風險與權重分母...")
    cash_val = pf_data.get("cash")
    cash_status = pf_data.get("cash_status", "cash_unknown")
    if cash_val is None:
        cash_status = "cash_unknown"

    violations = []
    cash_ratio_pct = None

    risk_cfg = config.get("risk_control", {})
    max_single_stock = risk_cfg.get("single_stock_max_weight_pct", 25.0)
    max_single_sector = risk_cfg.get("single_sector_max_weight_pct", 40.0)
    min_cash_floor = risk_cfg.get("cash_min_reserve_pct", 10.0)
    max_short_total = risk_cfg.get("short_total_max_weight_pct", 15.0)

    # 大盤空頭風控
    if market_meta.get("regime") == "空頭":
        violations.append("大盤空頭警示: 加權指數處於空頭體系 (B板候選只列觀察，不給買進方案)")

    if cash_status == "ok" and cash_val is not None and has_valid_valuation:
        denom = total_stock_value + cash_val
        cash_ratio_pct = round(cash_val / denom * 100, 1)

        # 1. 現金下限檢查 (10%)
        if cash_ratio_pct < min_cash_floor:
            violations.append(f"現金水位低於下限: {cash_ratio_pct}% < {min_cash_floor}% (禁止新買進方案)")

        # 2. 單檔權重上限 (25%)
        sector_weights: Dict[str, float] = {}
        short_total_weight = 0.0

        for h in processed_holdings:
            if h["qty"] and h["current_price"]:
                val = h["qty"] * h["current_price"]
                w = round(val / denom * 100, 1)
                h["weight_pct"] = w

                # 單檔上限超標與算式
                if w > max_single_stock:
                    excess_val = val - (denom * (max_single_stock / 100.0))
                    shares_to_sell = round(excess_val / h["current_price"]) if h["current_price"] > 0 else 0
                    formula_str = f"({val:.0f} - {denom:.0f} × {max_single_stock/100:.2f}) ÷ {h['current_price']}"
                    violations.append(f"單檔超標: {h['code']} 權重 {w}% > {max_single_stock}% (建議減碼 {shares_to_sell} 股，算式: {formula_str})")

                # 產業權重累加
                sec = h.get("sector", "未分類")
                sector_weights[sec] = sector_weights.get(sec, 0.0) + w

                # SHORT 權重累加
                if h.get("type") == "SHORT":
                    short_total_weight += w

        # 3. 單一產業上限 (40%)
        for sec, sec_w in sector_weights.items():
            sec_w_rnd = round(sec_w, 1)
            if sec_w_rnd > max_single_sector:
                violations.append(f"單一產業超標: {sec} 合計權重 {sec_w_rnd}% > {max_single_sector}% (限制同產業新買進方案)")

        # 4. SHORT 合計上限 (15%)
        short_total_rnd = round(short_total_weight, 1)
        if short_total_rnd > max_short_total:
            violations.append(f"SHORT 合計超標: 合計權重 {short_total_rnd}% > {max_short_total}% (禁止新增 SHORT)")

    else:
        cash_status = "cash_unknown"
        for h in processed_holdings:
            h["weight_pct"] = None
            h["data_flags"].append("weight_denominator_stock_only")
            h["data_flags"] = sorted(list(set(h["data_flags"])))
        violations.append("單檔上限判定暫停 (因現金或持股資料不足)")

    # 封裝 snapshot.json
    snapshot_output = {
        "meta": {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "portfolio_updated_at": pf_data.get("updated"),
            "is_market_closed": True,
            "market_regime": market_meta.get("regime"),
            "market_day_change_pct": market_meta.get("day_change_pct"),
            "extreme_move": market_extreme,
            "taiex": market_meta
        },
        "portfolio_risk": {
            "cash_status": cash_status,
            "cash_ratio_pct": cash_ratio_pct,
            "total_stock_value": round(total_stock_value, 2) if has_valid_valuation else None,
            "violations": violations
        },
        "holdings": processed_holdings,
        "candidates": []
    }

    with open(SNAPSHOT_FILE, "w", encoding="utf-8") as f:
        json.dump(snapshot_output, f, ensure_ascii=False, indent=2)

    print("=" * 70)
    print(f"✓ 產出成功！已輸出至 {SNAPSHOT_FILE}")
    print(f"  * 總評估持股: {len(processed_holdings)} 檔")
    print(f"  * 大盤體系: {market_meta.get('regime')} (加權收盤: {market_meta.get('close')})")
    print(f"  * 現金狀態: {cash_status}")
    print(f"  * 總 API 調用次數: {api_call_tracker} 次")
    print("=" * 70)

if __name__ == "__main__":
    generate_snapshot()
