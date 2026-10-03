"""
fetch_tdcc.py
從臺灣集中保管結算所 (TDCC) 官方網站 (https://www.tdcc.com.tw/portal/zh/smWeb/qryStock)
自動抓取股票池中所有標的前 30 週「集保戶股權分散表」歷史走勢資料，
解析大戶 (>=1000張) 與散戶 (<50張) 持股數據與人數，輸出至 tdcc_data.json 供 Dashboard C 使用。
"""

import os
import json
import re
import urllib.request
import urllib.parse
import http.cookiejar
import time
from concurrent.futures import ThreadPoolExecutor

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
POOL_FILE = os.path.join(BASE_DIR, "pool.json")
OUTPUT_FILE = os.path.join(BASE_DIR, "tdcc_data.json")

TDCC_URL = "https://www.tdcc.com.tw/portal/zh/smWeb/qryStock"

def get_available_dates():
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}
    req = urllib.request.Request(TDCC_URL, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode('utf-8')
            dates = re.findall(r'option\s+value=[\"\']?(20\d{6})[\"\']?', html)
            if dates:
                return sorted(list(set(dates)), reverse=True)
    except Exception as e:
        print(f"⚠️ 抓取 TDCC 日期選單失敗: {e}")
    return []

def fetch_stock_tdcc_history(code, dates):
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
        'Content-Type': 'application/x-www-form-urlencoded',
        'Referer': TDCC_URL
    }

    req1 = urllib.request.Request(TDCC_URL, headers={'User-Agent': headers['User-Agent']})
    try:
        html1 = opener.open(req1, timeout=15).read().decode('utf-8')
    except Exception:
        return code, []

    token_m = re.search(r'name=\"SYNCHRONIZER_TOKEN\"\s+value=\"([^\"]+)\"', html1)
    uri_m = re.search(r'name=\"SYNCHRONIZER_URI\"\s+value=\"([^\"]+)\"', html1)
    token = token_m.group(1) if token_m else ''
    uri = uri_m.group(1) if uri_m else ''

    history = []
    # 按照時間由舊到新排序抓取
    for d in reversed(dates):
        form_data = {
            'SYNCHRONIZER_TOKEN': token,
            'SYNCHRONIZER_URI': uri,
            'method': 'submit',
            'scaDate': d,
            'sqlMethod': 'StockNo',
            'stockNo': code,
            'stockName': ''
        }
        req = urllib.request.Request(
            TDCC_URL,
            data=urllib.parse.urlencode(form_data).encode('utf-8'),
            headers=headers
        )
        try:
            resp_html = opener.open(req, timeout=15).read().decode('utf-8')
            tm = re.search(r'name=\"SYNCHRONIZER_TOKEN\"\s+value=\"([^\"]+)\"', resp_html)
            if tm: token = tm.group(1)

            rows = re.findall(r'<tr[^>]*>\s*<td[^>]*>(\d+)</td>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>([\d,]+)</td>\s*<td[^>]*>([\d,]+)</td>\s*<td[^>]*>([\d\.]+)', resp_html)
            if rows:
                l15_list = [r for r in rows if r[0] == '15']
                l_retail = [r for r in rows if 1 <= int(r[0]) <= 8]
                l400 = [r for r in rows if 12 <= int(r[0]) <= 15]

                if l15_list:
                    l15 = l15_list[0]
                    p1000 = int(l15[2].replace(',', ''))
                    pct1000 = float(l15[4].replace(',', ''))
                    s1000 = int(l15[3].replace(',', ''))

                    pct400 = round(sum(float(r[4].replace(',', '')) for r in l400), 2)
                    pretail = sum(int(r[2].replace(',', '')) for r in l_retail)
                    pctretail = round(sum(float(r[4].replace(',', '')) for r in l_retail), 2)

                    history.append({
                        'date': d,
                        'over1000_people': p1000,
                        'over1000_pct': pct1000,
                        'over1000_shares': s1000,
                        'over400_pct': pct400,
                        'retail_people': pretail,
                        'retail_pct': pctretail
                    })
        except Exception:
            pass

    # 計算週變動 (Week-over-Week)
    for i in range(len(history)):
        cur = history[i]
        prv = history[i-1] if i > 0 else cur
        cur['over1000_pct_chg'] = round(cur['over1000_pct'] - prv['over1000_pct'], 2)
        cur['over1000_people_chg'] = cur['over1000_people'] - prv['over1000_people']
        cur['retail_pct_chg'] = round(cur['retail_pct'] - prv['retail_pct'], 2)
        cur['over400_pct_chg'] = round(cur['over400_pct'] - prv['over400_pct'], 2)

    return code, history

def fetch_tdcc():
    print("開始從 TDCC 官方網站獲取歷史週集保戶股權分散表...")
    avail_dates = get_available_dates()
    if not avail_dates:
        print("❌ 無法取得 TDCC 日期列表")
        return

    target_dates = avail_dates[:30] # 保留最多 30 週
    print(f"📅 最新集保日期: {target_dates[0]}，共擷取歷史 {len(target_dates)} 週數據 ({target_dates[-1]} ~ {target_dates[0]})")

    # 讀取股票池
    target_codes = []
    if os.path.exists(POOL_FILE):
        with open(POOL_FILE, "r", encoding="utf-8") as f:
            pool = json.load(f)
            target_codes = [s["code"] for s in pool if "code" in s]

    if not target_codes:
        print("❌ 未能讀取 pool.json 股票池")
        return

    print(f"🚀 開始平行下載 {len(target_codes)} 支標的歷史集保數據...")
    t0 = time.time()
    
    tdcc_map = {}
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(fetch_stock_tdcc_history, code, target_dates) for code in target_codes]
        for f in futures:
            code, history = f.result()
            if history:
                tdcc_map[code] = {
                    "latest": history[-1],
                    "history": history
                }

    output_data = {
        "last_updated": target_dates[0],
        "total_stocks": len(tdcc_map),
        "data": tdcc_map
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    print(f"✅ 完成！共耗時 {time.time()-t0:.1f} 秒，成功輸出 {len(tdcc_map)} 支標的歷史 30 週數據至 {OUTPUT_FILE}")

if __name__ == "__main__":
    fetch_tdcc()
