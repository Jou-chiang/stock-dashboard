"""
generate_adjusted_history.py
專供 L2 確定性引擎讀取之還原日 K 產出程式。

資料合約與原則：
1. 僅還原 my_portfolio.json 所列之持股標的。
2. 原始價格讀自 history_data.csv（維持 B 板原始資料完整不變動）。
3. 依據「除權除息結果表」、「減資恢復買賣參考價格」、「分割後參考價」、「變更面額」之真實事件，
   以「事件後參考價 ÷ 事件前收盤價」作為還原因子，由最新往歷史方向連乘。
4. 輸出：
   - history_data_adj.csv：還原後日 K
   - history_data_adj_meta.json：還原後中繼元資料（含 price_basis 與事件清單）
5. 若遇無事件支援、事件資料不完整或計算失敗，該標的標記為 "price_basis": "unadjusted"，
   供 L2 引擎防呆降級（輸出 null 均線與回落）。
"""

import os
import json
import csv
import urllib.request
import urllib.parse
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PORTFOLIO_FILE = os.path.join(BASE_DIR, "my_portfolio.json")
HISTORY_FILE   = os.path.join(BASE_DIR, "history_data.csv")
OUTPUT_CSV     = os.path.join(BASE_DIR, "history_data_adj.csv")
OUTPUT_META    = os.path.join(BASE_DIR, "history_data_adj_meta.json")

TOKEN = os.environ.get("FINMIND_TOKEN", "")

def fetch_finmind(dataset, data_id=None, start_date="2026-01-01"):
    params = {"dataset": dataset, "start_date": start_date}
    if data_id:
        params["data_id"] = data_id
    if TOKEN:
        params["token"] = TOKEN
    url = "https://api.finmindtrade.com/api/v4/data?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
            return data.get("data", [])
    except Exception as e:
        print(f"  [API WARN] Failed to fetch {dataset} (data_id={data_id}): {e}")
        return None  # None = 抓取失敗；[] = 抓取成功但無事件（兩者必須分開）

def main():
    print("=" * 70)
    print("開始產出 L2 還原日 K 線資料 (generate_adjusted_history.py)")
    print("=" * 70)

    # 1. 讀取持股清單
    if not os.path.exists(PORTFOLIO_FILE):
        print(f"錯誤：找不到 {PORTFOLIO_FILE}")
        return

    with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
        pf = json.load(f)
    
    holdings = pf.get("holdings", [])
    portfolio_codes = [str(h["code"]).strip() for h in holdings if h.get("code")]
    print(f"持股標的清單: {portfolio_codes}")

    # 2. 讀取 history_data.csv
    if not os.path.exists(HISTORY_FILE):
        print(f"錯誤：找不到 {HISTORY_FILE}")
        return

    raw_rows = []
    with open(HISTORY_FILE, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        raw_rows = list(reader)

    print(f"歷史資料總筆數: {len(raw_rows)} 筆")

    # 3. 預先抓取市場全域事件（分割與變更面額，單次請求節省額度）
    api_calls = 0
    split_records = fetch_finmind("TaiwanStockSplitPrice", start_date="2025-01-01")
    api_calls += 1
    par_records = fetch_finmind("TaiwanStockParValueChange", start_date="2025-01-01")
    api_calls += 1

    adjusted_csv_rows = []
    meta_output = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_stocks": len(portfolio_codes),
        "api_calls_used": 0,
        "stocks": {}
    }

    for code in portfolio_codes:
        stock_rows = [r for r in raw_rows if str(r.get("code", "")).strip() == code]
        if not stock_rows:
            print(f"[{code}] 警告：history_data.csv 中無此標的，標記為 unadjusted")
            meta_output["stocks"][code] = {
                "price_basis": "unadjusted",
                "reason": "missing_history_data",
                "events_applied": []
            }
            continue

        # 排序以防資料日期顛倒
        stock_rows.sort(key=lambda x: x["date"])
        min_date = stock_rows[0]["date"]
        max_date = stock_rows[-1]["date"]

        # 抓取該股專屬事件（除權息結果、減資）
        events = []
        div_data = fetch_finmind("TaiwanStockDividendResult", data_id=code, start_date=min_date)
        api_calls += 1
        for d in (div_data or []):
            bp = d.get("before_price")
            ap = d.get("reference_price") or d.get("after_price")
            if bp and ap and bp > 0:
                events.append({
                    "date": d["date"],
                    "type": "dividend",
                    "subtype": d.get("stock_or_cache_dividend", ""),
                    "before_price": bp,
                    "after_price": ap,
                    "factor": ap / bp,
                    "detail": f"股利 {d.get('stock_and_cache_dividend')}"
                })

        cap_data = fetch_finmind("TaiwanStockCapitalReductionReferencePrice", data_id=code, start_date=min_date)
        api_calls += 1
        for c in (cap_data or []):
            bp = c.get("ClosingPriceonTheLastTradingDay")
            ap = c.get("PostReductionReferencePrice")
            if bp and ap and bp > 0:
                events.append({
                    "date": c["date"],
                    "type": "capital_reduction",
                    "subtype": c.get("ReasonforCapitalReduction", ""),
                    "before_price": bp,
                    "after_price": ap,
                    "factor": ap / bp,
                    "detail": c.get("ReasonforCapitalReduction", "")
                })

        for sp in (split_records or []):
            if str(sp.get("stock_id", "")).strip() == code and sp.get("date") >= min_date:
                bp = sp.get("before_price")
                ap = sp.get("after_price")
                if bp and ap and bp > 0:
                    events.append({
                        "date": sp["date"],
                        "type": "split",
                        "subtype": sp.get("type", ""),
                        "before_price": bp,
                        "after_price": ap,
                        "factor": ap / bp,
                        "detail": "股票分割"
                    })

        for pv in (par_records or []):
            if str(pv.get("stock_id", "")).strip() == code and pv.get("date") >= min_date:
                bp = pv.get("before_close")
                ap = pv.get("after_ref_close")
                if bp and ap and bp > 0:
                    events.append({
                        "date": pv["date"],
                        "type": "par_value_change",
                        "subtype": "變更面額",
                        "before_price": bp,
                        "after_price": ap,
                        "factor": ap / bp,
                        "detail": "變更面額"
                    })

        events.sort(key=lambda x: x["date"])

        # 事件資料抓取失敗（None）≠ 無事件（[]）：失敗一律降級為 unadjusted
        if div_data is None or cap_data is None or split_records is None or par_records is None:
            print(f"[{code}] 警告：事件資料抓取失敗，標記為 unadjusted（不得當成無事件）")
            meta_output["stocks"][code] = {
                "price_basis": "unadjusted",
                "reason": "event_fetch_failed",
                "events_applied": []
            }
            continue

        # 進行向後復權（Backward Adjustment）：
        # 對於任一日 t，其乘數為所有發生在 t 之後（T_i > t）的事件還原因子之連乘積
        cum_factor_oldest = 1.0
        for r in stock_rows:
            r_date = r["date"]
            # 找出所有在 r_date 之後發生的事件
            subsequent_events = [ev for ev in events if ev["date"] > r_date]
            mult = 1.0
            for ev in subsequent_events:
                mult *= ev["factor"]

            if r_date == min_date:
                cum_factor_oldest = mult

            adj_r = dict(r)
            for col in ["open", "high", "low", "close"]:
                try:
                    val = float(r[col])
                    adj_r[col] = f"{(val * mult):.2f}"
                except (ValueError, TypeError):
                    adj_r[col] = r[col]

            adjusted_csv_rows.append(adj_r)

        meta_output["stocks"][code] = {
            "price_basis": "adjusted",
            "date_range": f"{min_date} ~ {max_date}",
            "records_count": len(stock_rows),
            "events_count": len(events),
            "events_applied": events,
            "cumulative_factor_oldest": round(cum_factor_oldest, 6)
        }
        print(f"[{code}] 完成還原：共套用 {len(events)} 個事件，最舊日累積因子: {cum_factor_oldest:.6f}")

    meta_output["api_calls_used"] = api_calls

    # 4. 寫入 history_data_adj.csv
    with open(OUTPUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(adjusted_csv_rows)

    # 5. 寫入 history_data_adj_meta.json
    with open(OUTPUT_META, "w", encoding="utf-8") as f:
        json.dump(meta_output, f, ensure_ascii=False, indent=2)

    print("=" * 70)
    print(f"產出完成！")
    print(f"  * 還原價格檔: {OUTPUT_CSV} ({len(adjusted_csv_rows)} 筆)")
    print(f"  * 中繼元資料: {OUTPUT_META}")
    print(f"  * 本次總 API 呼叫次數: {api_calls} 次 (每小時 300/600 額度安全無虞)")
    print("=" * 70)

if __name__ == "__main__":
    main()
