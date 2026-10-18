"""
price_adapter.py
L2 確定性引擎之價格來源配接器（Pluggable Price Adapter）

職責：
1. 作為 L2 引擎唯一合法的價格讀取介面，隔離實體 CSV 與下游訊號計算。
2. 預設讀取 history_data_adj.csv 與其伴隨元資料 history_data_adj_meta.json。
3. 嚴格檢查 price_basis：
   - 若為 "adjusted"，標記 is_valid_for_ma = True，允許計算 MA 與回落。
   - 若為 "unadjusted"、檔案缺漏或資料長度不足，標記 is_valid_for_ma = False。
4. 提供安全防呆計算器：在 is_valid_for_ma 為 False 時，MA20、MA60、core_deep_drawdown
   一律強制返回 None，杜絕以未還原價格計算假均線與假跌破。
"""

import os
import csv
import json
from typing import Dict, List, Optional, Any

HISTORY_ADJ_CSV  = "history_data_adj.csv"
HISTORY_ADJ_META = "history_data_adj_meta.json"
HISTORY_RAW_CSV  = "history_data.csv"

class PriceSeries:
    def __init__(self, code: str, rows: List[Dict[str, Any]], price_basis: str, events: List[Dict], meta_info: Dict[str, Any]):
        self.code = code
        self.rows = rows  # 依照日期由舊至新遞增排序
        self.price_basis = price_basis  # "adjusted" | "unadjusted"
        self.events = events
        self.meta_info = meta_info
        self.is_valid_for_ma = (price_basis == "adjusted" and len(rows) >= 20)

    @property
    def latest_close(self) -> Optional[float]:
        if not self.rows:
            return None
        try:
            return float(self.rows[-1]["close"])
        except (ValueError, TypeError):
            return None

    @property
    def closes(self) -> List[float]:
        res = []
        for r in self.rows:
            try:
                res.append(float(r["close"]))
            except (ValueError, TypeError):
                pass
        return res

    def get_ma(self, period: int) -> Optional[float]:
        """計算指定天期之移動平均線。未還原時強制回傳 None。"""
        if not self.is_valid_for_ma:
            return None
        c = self.closes
        if len(c) < period:
            return None
        return round(sum(c[-period:]) / period, 2)

    def get_max_close_since(self, entry_date: Optional[str]) -> Optional[float]:
        """計算進場日後之最高收盤價。未還原時強制回傳 None。"""
        if not self.is_valid_for_ma:
            return None
        if not entry_date:
            return None
        closes_since = [
            float(r["close"]) for r in self.rows 
            if r["date"] >= entry_date and r.get("close") is not None
        ]
        if not closes_since:
            return None
        return max(closes_since)


def load_price_adapter(
    code: str,
    base_dir: str = ".",
    prefer_adjusted: bool = True
) -> PriceSeries:
    """
    可抽換價格配接器：載入指定個股之 K 線序列。
    若指定 prefer_adjusted 且存在合法的還原檔與 meta，優先採用 adjusted；
    否則降級載入 raw 未還原檔案並強制標註 unadjusted。
    """
    code = str(code).strip()
    adj_csv_path  = os.path.join(base_dir, HISTORY_ADJ_CSV)
    adj_meta_path = os.path.join(base_dir, HISTORY_ADJ_META)
    raw_csv_path  = os.path.join(base_dir, HISTORY_RAW_CSV)

    # 1. 嘗試載入還原檔與元資料
    if prefer_adjusted and os.path.exists(adj_csv_path) and os.path.exists(adj_meta_path):
        try:
            with open(adj_meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            stock_meta = meta.get("stocks", {}).get(code)

            if stock_meta and stock_meta.get("price_basis") == "adjusted":
                # 讀取 CSV
                matched_rows = []
                with open(adj_csv_path, "r", encoding="utf-8-sig") as f:
                    reader = csv.DictReader(f)
                    for r in reader:
                        if str(r.get("code", "")).strip() == code:
                            matched_rows.append(r)
                
                if matched_rows:
                    matched_rows.sort(key=lambda x: x["date"])
                    return PriceSeries(
                        code=code,
                        rows=matched_rows,
                        price_basis="adjusted",
                        events=stock_meta.get("events_applied", []),
                        meta_info=stock_meta
                    )
        except Exception as e:
            print(f"[PriceAdapter] 讀取還原檔失敗 ({code}): {e}，自動降級為未還原標記")

    # 2. 降級讀取原始 raw 檔（或找不到還原資料時），強制標註 unadjusted
    matched_raw = []
    if os.path.exists(raw_csv_path):
        try:
            with open(raw_csv_path, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for r in reader:
                    if str(r.get("code", "")).strip() == code:
                        matched_raw.append(r)
            matched_raw.sort(key=lambda x: x["date"])
        except Exception:
            pass

    return PriceSeries(
        code=code,
        rows=matched_raw,
        price_basis="unadjusted",
        events=[],
        meta_info={"reason": "fallback_raw_or_missing_meta"}
    )
