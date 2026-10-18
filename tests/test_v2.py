import csv, collections, random, sys
import os
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
import screener_v2

by = collections.defaultdict(list)
with open(os.path.join(BASE_DIR, "history_data.csv"), encoding="utf-8-sig") as f:
    for r in csv.DictReader(f):
        try:
            by[r["code"]].append({"date": r["date"], "open": float(r["open"]), "high": float(r["high"]),
                                  "low": float(r["low"]), "close": float(r["close"]), "volume": float(r["volume"])})
        except Exception:
            pass
random.seed(1)
cnt = collections.Counter(); samples = {}
for code, rows in by.items():
    rows.sort(key=lambda r: r["date"])
    if len(rows) < 60:
        continue
    inst = []
    for r in rows[-13:]:
        for nm in ("Investment_Trust", "Foreign_Investor"):
            n = random.randint(-300, 600) * 1000
            inst.append({"date": r["date"], "name": nm, "buy": max(n, 0), "sell": max(-n, 0)})
    v = screener_v2.evaluate(rows, inst)
    cnt[v["strategy"]] += 1
    samples.setdefault(v["strategy"], (code, v["score"], v["risk"], v["action"], v["risk_reasons"]))
print("stocks:", sum(cnt.values()), dict(cnt))
for k, s in samples.items():
    print(k, s)
v = screener_v2.evaluate(rows, [])
print("no inst ok", v["score"], v["strategy"])
for code in ("2313",):
    if code in by:
        rows = by[code]; v = screener_v2.evaluate(rows, [])
        print(code, v["score"], v["strategy"], v["metrics"]["dist_ma20"], v["exclude_reasons"])
