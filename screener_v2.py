"""
screener_v2.py  —  Stock Screener V2（戰情室 B）

架構：硬性淘汰 → 5 分選股分數 → 策略標籤 → 風險分數／操作建議

純函式，不連網，可用 history_data.csv 離線測試。
rows      : list[dict]，依日期遞增，含 open/high/low/close/volume（volume 單位：張）
inst_rows : FinMind TaiwanStockInstitutionalInvestorsBuySell 原始列（shares）
"""

# ── 參數（集中放這裡，方便調整）────────────────────────────
MIN_TURNOVER_EXCLUDE = 2_000     # 萬元：20日均成交金額低於此值 → 排除
MIN_TURNOVER_WARN    = 5_000     # 萬元：低於此值 → 流動性偏低（風險加分）
INST_INTENSITY_MIN   = 5.0       # %：投信5日累計買超 / 20日均量
EXT_MID, EXT_HIGH    = 8.0, 15.0 # %：股價距 MA20 乖離
RET20_MAX_FOR_S5     = 20.0      # %：S5 要求 20 日漲幅小於此值
RET20_CHASE_WARN     = 25.0      # %：追高警示
BREAKOUT_VOL_RATIO   = 1.5
BREAKOUT_MAX_CHG     = 8.0       # %：當日漲幅超過視為追高
PULLBACK_K_MAX       = 65
COMPRESSION_GAP      = 3.0       # %：MA5/MA20 糾結


# ── 基礎指標 ───────────────────────────────────────────────
def _ma(vals, n, offset=0):
    end = len(vals) - offset
    if end < n:
        return None
    return sum(vals[end - n:end]) / n


def _kd_series(rows, p=9):
    k, d = 50.0, 50.0
    ks, ds = [], []
    for i in range(p - 1, len(rows)):
        w = rows[i - p + 1:i + 1]
        hh = max(r["high"] for r in w)
        ll = min(r["low"] for r in w)
        rsv = 50 if hh == ll else (rows[i]["close"] - ll) / (hh - ll) * 100
        k = k * (2 / 3) + rsv * (1 / 3)
        d = d * (2 / 3) + k * (1 / 3)
        ks.append(k)
        ds.append(d)
    return ks, ds


def _ema(vals, span):
    a = 2.0 / (span + 1)
    out, e = [], None
    for v in vals:
        e = v if e is None else a * v + (1 - a) * e
        out.append(e)
    return out


def _macd_series(closes):
    e12, e26 = _ema(closes, 12), _ema(closes, 26)
    dif = [a - b for a, b in zip(e12, e26)]
    dea = _ema(dif, 9)
    return dif, dea


def _daily_net_lots(inst_rows, kw1, kw2=""):
    def collect(kw):
        d = {}
        for r in inst_rows:
            if kw in str(r.get("name", "")):
                d[r["date"]] = d.get(r["date"], 0.0) + float(r.get("buy", 0)) - float(r.get("sell", 0))
        return d
    d = collect(kw1) or (collect(kw2) if kw2 else {})
    return [d[k] / 1000.0 for k in sorted(d)]


def _trailing_run(nets, positive=True):
    n = 0
    for v in reversed(nets):
        if (v > 0) if positive else (v < 0):
            n += 1
        else:
            break
    return n


def _prior_buy_run(nets, skip):
    """跳過最後 skip 天之後，再往前連續買超幾天"""
    return _trailing_run(nets[:len(nets) - skip], positive=True) if skip < len(nets) else 0


# ── 主函式 ─────────────────────────────────────────────────
def evaluate(rows, inst_rows):
    closes = [r["close"] for r in rows]
    vols = [r["volume"] for r in rows]
    last, prev = rows[-1], rows[-2]
    price = last["close"]
    chg_pct = (price - prev["close"]) / prev["close"] * 100 if prev["close"] else 0.0

    ma5, ma20, ma60 = _ma(closes, 5), _ma(closes, 20), _ma(closes, 60)
    ma20_5ago = _ma(closes, 20, offset=5)
    ma20_up = ma20 is not None and ma20_5ago is not None and ma20 >= ma20_5ago

    ks, ds = _kd_series(rows)
    k, d = ks[-1], ds[-1]
    k_prev, d_prev = (ks[-2], ds[-2]) if len(ks) >= 2 else (k, d)
    dif_s, dea_s = _macd_series(closes) if len(closes) >= 26 else ([None], [None])
    dif, dea = dif_s[-1], dea_s[-1]
    dif_prev = dif_s[-2] if len(dif_s) >= 2 else None

    avg_vol5 = _ma(vols[:-1], 5)
    vol_ratio = last["volume"] / avg_vol5 if avg_vol5 else 0.0
    avg_vol20 = _ma(vols, 20) or 0.0
    turnover20 = (_ma([c * v for c, v in zip(closes, vols)], 20) or 0.0) * 1000 / 10_000  # 萬元

    dist_ma20 = (price / ma20 - 1) * 100 if ma20 else 0.0
    ret20 = (price / closes[-21] - 1) * 100 if len(closes) >= 21 else 0.0
    high20_prev = max(closes[-21:-1]) if len(closes) >= 21 else None

    rng = last["high"] - last["low"]
    upper_shadow = (last["high"] - max(last["open"], price)) / rng if rng > 0 else 0.0
    bad_candle = vol_ratio >= 2.0 and upper_shadow >= 0.5

    # 法人
    trust = _daily_net_lots(inst_rows, "Investment_Trust", "投信")
    foreign = _daily_net_lots(inst_rows, "Foreign_Investor", "外資")
    trust_buy_days = _trailing_run(trust, True)
    foreign_buy_days = _trailing_run(foreign, True)
    trust5 = sum(trust[-5:])
    trust_intensity = trust5 / avg_vol20 * 100 if avg_vol20 else 0.0
    trust3, foreign3 = sum(trust[-3:]), sum(foreign[-3:])

    # ── 第一層：硬性淘汰 ──────────────────────────────────
    bear = (ma20 is not None and price < ma20 and dif is not None and dif < 0)
    low_liq = turnover20 < MIN_TURNOVER_EXCLUDE
    exclude_reasons = []
    if bear:
        exclude_reasons.append("空頭：股價<MA20 且 DIF<0")
    if low_liq:
        exclude_reasons.append(f"流動性不足：20日均成交金額 {turnover20:.0f} 萬 < {MIN_TURNOVER_EXCLUDE} 萬")

    # ── 第二層：5 分 ──────────────────────────────────────
    # S1 法人累積（整組最多 1 分，不重複計分）
    strong_int = trust_intensity >= INST_INTENSITY_MIN
    if trust_buy_days >= 3 and strong_int:
        s1 = 1.0
    elif trust5 > 0 and (trust_buy_days >= 2 or strong_int):
        s1 = 0.5
    else:
        s1 = 0.0
    # S2 法人共識
    if trust3 > 0 and foreign3 > 0:
        s2 = 1.0
    elif trust3 > 0 or foreign3 > 0:
        s2 = 0.5
    else:
        s2 = 0.0
    # S3 趨勢
    s3 = 1.0 if (ma20 and ma60 and price > ma20 and ma20 > ma60 and ma20_up) else 0.0
    # S4 觸發：突破 / 回檔轉強
    breakout = bool(high20_prev and price > high20_prev and vol_ratio >= BREAKOUT_VOL_RATIO
                    and ma5 and price > ma5 and chg_pct <= BREAKOUT_MAX_CHG)
    pullback = bool(ma20 and ma60 and ma20 > ma60 and k < PULLBACK_K_MAX and k > d
                    and dif is not None and dea is not None and dif > dea)
    s4 = 1.0 if (breakout or pullback) else 0.0
    # S5 價位 / 風險報酬
    s5 = 1.0 if (ma20 and dist_ma20 <= EXT_MID and ret20 < RET20_MAX_FOR_S5 and not bad_candle) else 0.0

    score = s1 + s2 + s3 + s4 + s5

    # 均線蓄勢（策略標籤用）
    ma_gap = abs(ma5 - ma20) / ma20 * 100 if (ma5 and ma20) else 999.0
    compression = bool(ma5 and ma20 and ma_gap <= COMPRESSION_GAP and price > ma5
                       and ma5 >= ma20 and ma20_up)

    # 低檔反轉觀察（Reversal Watch）：不進主選股池，另列
    kd_cross_up = k > d and k_prev <= d_prev
    reversal_watch = bool(bear and k < 30 and kd_cross_up and dif_prev is not None
                          and dif > dif_prev and vol_ratio >= 1.0 and not low_liq)

    # ── 第四層：風險 ─────────────────────────────────────
    risk_pts, risk_reasons = 0, []
    if dist_ma20 > EXT_HIGH:
        risk_pts += 2; risk_reasons.append(f"高乖離：距MA20 +{dist_ma20:.1f}%（等回測，勿追）")
    elif dist_ma20 > EXT_MID:
        risk_pts += 1; risk_reasons.append(f"乖離偏高：距MA20 +{dist_ma20:.1f}%")
    if ret20 > RET20_CHASE_WARN:
        risk_pts += 1; risk_reasons.append(f"20日漲幅 +{ret20:.0f}%，追價風險")
    if bad_candle:
        risk_pts += 1; risk_reasons.append("爆量長上影")
    if not low_liq and turnover20 < MIN_TURNOVER_WARN:
        risk_pts += 1; risk_reasons.append(f"流動性偏低：均成交金額 {turnover20:.0f} 萬")

    # 法人反轉
    t_sell_run = _trailing_run(trust, False)
    prior_run = _prior_buy_run(trust, t_sell_run) if t_sell_run else 0
    inst_reversal = None
    if t_sell_run >= 3 and foreign3 < 0 and ma20 and price < ma20:
        inst_reversal = "strong"
        risk_pts += 3; risk_reasons.append("🔴 法人轉弱警報：投信連賣3日＋外資同步賣＋跌破MA20")
    elif prior_run >= 5 and t_sell_run >= 2:
        inst_reversal = "warn"
        risk_pts += 2; risk_reasons.append(f"🟠 投信連買{prior_run}日後連賣{t_sell_run}日")
    elif prior_run >= 5 and t_sell_run == 1:
        inst_reversal = "notice"
        risk_pts += 1; risk_reasons.append(f"🟡 投信連買{prior_run}日後今日轉賣")

    risk = "high" if risk_pts >= 3 else "mid" if risk_pts == 2 else "low"

    # ── 第三層：策略標籤 ─────────────────────────────────
    excluded = bool(exclude_reasons)
    tags = []
    if not excluded:
        if breakout:
            tags.append("breakout")
        if pullback and s3:
            tags.append("pullback")
        if compression:
            tags.append("compression")
        if s1 >= 1.0 or (s1 >= 0.5 and s2 >= 1.0):
            tags.append("accumulation")
    if reversal_watch:
        strategy = "reversal"
    elif excluded:
        strategy = "excluded"
    else:
        strategy = tags[0] if tags else "watch"
    if inst_reversal in ("warn", "strong"):
        tags.append("weakening")

    # 操作建議（分數與建議分開）
    if strategy == "reversal":
        action = "低檔反轉觀察：K 上穿 D、DIF 回升，等站回月線再評估"
    elif excluded:
        action = "不進主選股池：" + "；".join(exclude_reasons)
    elif inst_reversal in ("warn", "strong"):
        action = "法人轉弱，持有者檢查停利／停損，空手勿進"
    elif score >= 4 and risk == "high":
        action = "高分高風險：禁止直接追價，等回測"
    elif score >= 4 and risk == "mid":
        action = "分數佳但乖離偏高，分批或等拉回"
    elif score >= 4:
        action = "可列入研究進場"
    elif score >= 3 and risk != "high":
        action = "觀察名單"
    else:
        action = "排除／僅追蹤" if risk == "high" else "觀察"

    final_score = 0.0 if (excluded and strategy != "reversal") else score

    r2 = lambda v: None if v is None else round(v, 2)
    return {
        "score": final_score,
        "score_raw": score,
        "strategy": strategy,
        "strategies": tags,
        "risk": risk,
        "risk_score": risk_pts,
        "risk_reasons": risk_reasons,
        "action": action,
        "excluded": excluded and strategy != "reversal",
        "exclude_reasons": exclude_reasons,
        "criteria": {"s1": s1, "s2": s2, "s3": s3, "s4": s4, "s5": s5},
        "metrics": {
            "trust_buy_days": trust_buy_days,
            "foreign_buy_days": foreign_buy_days,
            "trust5_lots": round(trust5),
            "trust_intensity": round(trust_intensity, 2),
            "turnover20_wan": round(turnover20),
            "dist_ma20": round(dist_ma20, 1),
            "ret20": round(ret20, 1),
            "ma60": r2(ma60),
            "dea": r2(dea),
            "breakout": breakout,
            "pullback": pullback,
            "inst_reversal": inst_reversal,
        },
    }
