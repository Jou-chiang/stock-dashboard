import json
import csv
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
POOL_SCORES_FILE = os.path.join(BASE_DIR, "pool_scores.json")
PRICES_FILE = os.path.join(BASE_DIR, "prices.json")
THESES_FILE = os.path.join(BASE_DIR, "research_theses.json")
SHEET_SCORES_CSV = os.path.join(BASE_DIR, "sheet_scores.csv")
SHEET_THESES_CSV = os.path.join(BASE_DIR, "sheet_theses.csv")

def export_scores_csv():
    if not os.path.exists(POOL_SCORES_FILE):
        print(f"⚠️ 找不到 {POOL_SCORES_FILE}，跳過 CSV 匯出")
        return

    with open(POOL_SCORES_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    scores = data.get("scores", [])
    updated = data.get("updated", "")

    # 即時價格補充 (若 prices.json 有更即時價格)
    rt_prices = {}
    if os.path.exists(PRICES_FILE):
        try:
            with open(PRICES_FILE, "r", encoding="utf-8") as f:
                p_data = json.load(f)
                rt_prices = p_data.get("prices", {})
        except Exception:
            pass

    rows = []
    headers = [
        "股票代號", "股票名稱", "產業", "最新股價", "漲跌幅%", "5星總分", 
        "K值", "D值", "J值", "MA5", "MA20", "均線差%", 
        "成交量", "5日均量", "量比", "投信連買天數", "投信淨買比%", 
        "外資連買天數", "外資買超張數", "投信買超張數", "自營商買超張數", "DIF", 
        "低流動性風險", "均線過發散", "黑名單否決", "更新時間"
    ]

    for item in scores:
        code = str(item.get("code", ""))
        price = item.get("price", 0)
        chg_pct = item.get("chg_pct", 0)

        # 若有盤中即時價格，優先覆蓋
        if code in rt_prices and "price" in rt_prices[code]:
            price = rt_prices[code]["price"]
            if "chg_pct" in rt_prices[code]:
                chg_pct = rt_prices[code]["chg_pct"]

        rc = item.get("risk_checks", {})

        rows.append([
            code,
            item.get("name", ""),
            item.get("sector", ""),
            price,
            f"{chg_pct:+.2f}%" if isinstance(chg_pct, (int, float)) else chg_pct,
            item.get("score", 0),
            item.get("k", 0),
            item.get("d", 0),
            item.get("j", 0),
            item.get("ma5", ""),
            item.get("ma20", ""),
            item.get("ma_gap", 0),
            item.get("volume", 0),
            item.get("avg_vol5", 0),
            item.get("vol_ratio", 0),
            item.get("buy_days", 0),
            item.get("net_buy_ratio", 0),
            item.get("foreign_buy_days", 0),
            item.get("foreign_lots", 0),
            item.get("trust_lots", 0),
            item.get("dealer_lots", 0),
            item.get("dif", 0),
            "⚠️低流動" if rc.get("low_volume") else "正常",
            "⚠️過發散" if rc.get("ma_divergence") else "正常",
            "🔴否決黑名單" if rc.get("blacklisted") else "正常",
            updated
        ])

    with open(SHEET_SCORES_CSV, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)

    print(f"✅ 已成功匯出 Google Sheets 專用格式：{SHEET_SCORES_CSV} ({len(rows)} 筆)")

def export_theses_csv():
    if not os.path.exists(THESES_FILE):
        print(f"⚠️ 找不到 {THESES_FILE}，跳過 Thesis CSV 匯出")
        return

    with open(THESES_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    theses = data.get("theses", {})
    last_updated = data.get("last_updated", "")

    headers = [
        "股票代號", "股票名稱", "標的分類", 
        "2026_EPS共識區間", "目標PE區間", 
        "Bull樂觀情境", "Base基準情境", "Bear悲觀情境", 
        "核心營運催化劑", "法說研報摘要註記", "最後更新日期"
    ]

    rows = []
    for code, item in theses.items():
        forecast = item.get("consensus_forecast", {})
        eps_range = forecast.get("2026_eps_range", [])
        eps_str = f"{eps_range[0]} ~ {eps_range[1]} 元" if len(eps_range) == 2 else "未提供"

        pe_range = forecast.get("target_pe_range", [])
        pe_str = f"{pe_range[0]} ~ {pe_range[1]} 倍" if len(pe_range) == 2 else "未提供"

        points = item.get("thesis_points", {})
        catalysts = item.get("catalysts", [])
        cat_str = " ; ".join(catalysts)

        rows.append([
            code,
            item.get("stock_name", ""),
            item.get("category", ""),
            eps_str,
            pe_str,
            points.get("bull", ""),
            points.get("base", ""),
            points.get("bear", ""),
            cat_str,
            item.get("last_report_note", ""),
            last_updated
        ])

    with open(SHEET_THESES_CSV, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)

    print(f"✅ 已成功匯出 Google Sheets Thesis 專用格式：{SHEET_THESES_CSV} ({len(rows)} 筆)")

SHEET_HISTORY_CSV = os.path.join(BASE_DIR, "sheet_history.csv")

def export_history_csv():
    headers = ["日期", "股票代號", "股票名稱", "5星分數", "最新股價", "漲跌幅%", "建議操作", "防守價位", "歷史核心結論與評語"]
    
    # 預設僅針對核心關注/持股清單生成歷史紀錄 (如 2330, 1513, 6282, 2618, 6274, 3163 等)
    portfolio_codes = {"2330", "1513", "6282", "2618", "6274", "3163"}
    
    rows = [headers]
    if os.path.exists(POOL_SCORES_FILE):
        try:
            with open(POOL_SCORES_FILE, "r", encoding="utf-8") as f:
                pdata = json.load(f)
            today = pdata.get("updated", "")
            scores = pdata.get("scores", [])
            for s in scores:
                code = str(s.get("code", ""))
                if code in portfolio_codes:
                    sc = s.get("score", 0)
                    op = "強勢續抱" if sc >= 4 else "偏多觀察" if sc == 3 else "拉回觀望"
                    rows.append([
                        today,
                        code,
                        s.get("name", ""),
                        sc,
                        s.get("price", 0),
                        f"{s.get('chg_pct', 0):+.2f}%" if isinstance(s.get('chg_pct'), (int, float)) else s.get('chg_pct', 0),
                        op,
                        f"MA20: {s.get('ma20', '')}",
                        f"KDJ: {s.get('k',0)}/{s.get('d',0)}，量比: {s.get('vol_ratio',0)}"
                    ])
        except Exception:
            pass

    with open(SHEET_HISTORY_CSV, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(rows)

    print(f"✅ 已成功匯出個人持股專屬歷史紀錄：{SHEET_HISTORY_CSV} ({len(rows)-1} 筆)")

if __name__ == "__main__":
    export_scores_csv()
    export_theses_csv()
    export_history_csv()
