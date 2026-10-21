"""sync_portfolio.py — 從 Google 試算表《我的股票即時戰情中心》同步持股帳本到 my_portfolio.json
試算表需開放「知道連結者可檢視」。用法：python3 sync_portfolio.py

必要欄位：股票代號、股票名稱、持有數量、成本價
選用欄位（試算表有加才會讀；沒有就沿用 my_portfolio.json 既有值）：
  操作屬性或屬性(CORE/SWING/SHORT，大小寫皆可)、進場日、停損價、失效價、停利價
現金：在試算表任一列的「股票代號」填 CASH，「持有數量」填現金金額。"""
import csv, io, json, os, urllib.request
from datetime import date

SHEET = "1Lt1BMWqwNVvwX2NP8d5dnBWBTyeEgbGNZzwXLuBeyHE"
GID = "704962987"
here = os.path.dirname(os.path.abspath(__file__))
out_path = os.path.join(here, "my_portfolio.json")

url = f"https://docs.google.com/spreadsheets/d/{SHEET}/export?format=csv&gid={GID}"
rows = list(csv.DictReader(io.StringIO(urllib.request.urlopen(url, timeout=30).read().decode("utf-8-sig"))))

def num(s):
    try:
        return float(str(s).replace(",", "").strip())
    except ValueError:
        return None

old = json.load(open(out_path, encoding="utf-8")) if os.path.exists(out_path) else {}
old_h = {h["code"]: h for h in old.get("holdings", [])}
cash, holdings = None, []
for r in rows:
    code = (r.get("股票代號") or "").strip()
    if not code:
        continue
    if code.upper() == "CASH":
        cash = num(r.get("持有數量"))
        continue
    qty = num(r.get("持有數量"))
    if not qty:  # 空白或 0 視為未持有
        continue
    h = {"code": code, "name": (r.get("股票名稱") or "").strip().rstrip("*"),
         "type": None, "entry_date": None, "shares_original": None, "qty": int(qty),
         "cost": num(r.get("成本價")) or None, "stop_loss_price": None, "invalidation_price": None,
         "take_profit_target": None, "partial_profit_taken": False, "ex_dividend_check": False,
         "price_levels_updated_at": None}
    h.update({k: v for k, v in old_h.get(code, {}).items() if k not in ("qty", "cost", "name")})
    t = (r.get("操作屬性") or r.get("屬性") or "").strip().upper()
    if t in ("CORE", "SWING", "SHORT"):
        h["type"] = t
    if (r.get("進場日") or "").strip():
        h["entry_date"] = r["進場日"].strip()
    for col, key in (("停損價", "stop_loss_price"), ("失效價", "invalidation_price"), ("停利價", "take_profit_target")):
        if num(r.get(col)) is not None:
            h[key] = num(r[col])
    holdings.append(h)

pf = {"updated": date.today().isoformat(), "cash": cash,
      "cash_status": "ok" if cash is not None else "cash_unknown", "holdings": holdings}
json.dump(pf, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
no_type = sum(1 for h in holdings if not h["type"])
print(f"同步 {len(holdings)} 檔｜現金={'已填' if cash is not None else '未提供'}｜未設操作屬性 {no_type} 檔")
