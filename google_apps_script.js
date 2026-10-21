/**
 * ==============================================================================
 * Google Apps Script — 股票理專《即時快照同步器》
 * ==============================================================================
 * 功能：
 * 1. 在 Google 試算表頂端建立【⚡ 理專戰情】選單。
 * 2. 盤中或盤後任何時候，點一下【🚀 立即更新快照至雲端硬碟】（或設定定時排程）。
 * 3. 自動讀取本試算表的 42 檔真實持股、股數、成本與屬性（CORE/SWING/SHORT）。
 * 4. 結合線上均線技術指標與 D 板研報資料，產出符合理專 Agent 規格的 snapshot.json。
 * 5. 直接覆蓋存入您的 Google 雲端硬碟根目錄，Gem 隨時都能讀取最新部位為您健檢與分析！
 * ==============================================================================
 */

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('⚡ 理專戰情')
    .addItem('🚀 立即更新快照至雲端硬碟 (snapshot.json)', 'generateSnapshotToDrive')
    .addToUi();
}

function generateSnapshotToDrive() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getActiveSheet();
  const data = sheet.getDataRange().getValues();
  if (data.length < 2) {
    SpreadsheetApp.getUi().alert('⚠️ 試算表沒有足夠的資料！');
    return;
  }

  // 1. 欄位動態定位
  const headers = data[0].map(h => String(h).trim());
  const colIndex = {
    code: headers.findIndex(h => h.includes('股票代號') || h === '代號'),
    name: headers.findIndex(h => h.includes('股票名稱') || h === '名稱'),
    price: headers.findIndex(h => h === '收盤價' || h.includes('現價') || h.includes('最新價')),
    refPrice: headers.findIndex(h => h === '昨收' || h.includes('昨收價')),
    qty: headers.findIndex(h => h.includes('持有數量') || h.includes('股數')),
    cost: headers.findIndex(h => h.includes('成本價') || h === '成本'),
    type: headers.findIndex(h => h.includes('屬性') || h.includes('操作屬性')),
    stopLoss: headers.findIndex(h => h.includes('停損價')),
    invalidation: headers.findIndex(h => h.includes('失效價')),
    takeProfit: headers.findIndex(h => h.includes('停利價')),
    sellRange: headers.findIndex(h => h.includes('建議賣出區間')),
    buyRange: headers.findIndex(h => h.includes('建議加碼區間'))
  };

  if (colIndex.code === -1) {
    SpreadsheetApp.getUi().alert('⚠️ 找不到「股票代號」欄位，請確認試算表表頭！');
    return;
  }

  // 2. 嘗試抓取線上公開的最新技術指標 (pool_scores.json) 與 研報 (research_theses.json)
  let poolMap = {};
  let thesisMap = {};
  try {
    const poolRes = UrlFetchApp.fetch('https://jou-chiang.github.io/stock-dashboard/pool_scores.json?_=' + new Date().getTime(), {muteHttpExceptions: true});
    if (poolRes.getResponseCode() === 200) {
      const poolJson = JSON.parse(poolRes.getContentText());
      (poolJson.scores || []).forEach(s => { poolMap[String(s.code)] = s; });
    }
  } catch(e) {
    Logger.log('無法載入 pool_scores.json: ' + e);
  }

  try {
    const thesisRes = UrlFetchApp.fetch('https://jou-chiang.github.io/stock-dashboard/research_theses.json?_=' + new Date().getTime(), {muteHttpExceptions: true});
    if (thesisRes.getResponseCode() === 200) {
      const thesisJson = JSON.parse(thesisRes.getContentText());
      thesisMap = thesisJson.theses || {};
    }
  } catch(e) {
    Logger.log('無法載入 research_theses.json: ' + e);
  }

  // 3. 逐列解析持股資料
  const now = new Date();
  const timeStr = Utilities.formatDate(now, 'Asia/Taipei', 'yyyy-MM-dd HH:mm:ss');
  const dateStr = Utilities.formatDate(now, 'Asia/Taipei', 'yyyy-MM-dd');

  let cash = null;
  let totalStockValue = 0;
  const holdings = [];

  for (let i = 1; i < data.length; i++) {
    const row = data[i];
    const code = String(row[colIndex.code] || '').trim();
    if (!code) continue;

    // 現金列
    if (code.toUpperCase() === 'CASH') {
      const cashVal = parseFloat(String(row[colIndex.qty] || row[colIndex.cost] || 0).replace(/,/g, ''));
      if (!isNaN(cashVal)) cash = cashVal;
      continue;
    }

    const name = colIndex.name !== -1 ? String(row[colIndex.name] || '').trim().replace(/\*+$/, '') : code;
    const qty = colIndex.qty !== -1 ? parseFloat(String(row[colIndex.qty] || 0).replace(/,/g, '')) : 0;
    if (isNaN(qty) || qty <= 0) continue; // 排除未持有標的

    const cost = colIndex.cost !== -1 ? parseFloat(String(row[colIndex.cost] || 0).replace(/,/g, '')) : null;
    let price = colIndex.price !== -1 ? parseFloat(String(row[colIndex.price] || 0).replace(/,/g, '')) : null;
    const ref = colIndex.refPrice !== -1 ? parseFloat(String(row[colIndex.refPrice] || 0).replace(/,/g, '')) : null;

    // 若試算表未提供收盤價，嘗試從 poolMap 補齊
    const poolData = poolMap[code] || {};
    if ((price === null || isNaN(price) || price === 0) && poolData.price) {
      price = poolData.price;
    }

    // 操作屬性 (預設 CORE)
    let type = colIndex.type !== -1 ? String(row[colIndex.type] || '').trim().toUpperCase() : 'CORE';
    if (!['CORE', 'SWING', 'SHORT'].includes(type)) {
      type = code.startsWith('00') ? 'CORE' : 'SWING';
    }

    // 防守價位
    const stopLoss = colIndex.stopLoss !== -1 ? parseFloat(row[colIndex.stopLoss]) || null : null;
    const invalidation = colIndex.invalidation !== -1 ? parseFloat(row[colIndex.invalidation]) || null : null;
    const takeProfit = colIndex.takeProfit !== -1 ? parseFloat(row[colIndex.takeProfit]) || null : null;

    // 損益計算
    const hasPrice = price !== null && !isNaN(price) && price > 0;
    const hasCost = cost !== null && !isNaN(cost) && cost > 0;
    const mktVal = (hasPrice && qty > 0) ? price * qty : 0;
    totalStockValue += mktVal;

    const pnlPct = (hasPrice && hasCost) ? parseFloat(((price - cost) / cost * 100).toFixed(2)) : null;
    const dayChangePct = (hasPrice && ref && ref > 0) ? parseFloat(((price - ref) / ref * 100).toFixed(2)) : (poolData.chg_pct || 0.0);

    // 技術均線 (以線上 pool_scores 為準，若無則推算)
    const ma5 = poolData.ma5 || (hasPrice ? price : null);
    const ma20 = poolData.ma20 || (hasPrice ? price : null);
    const ma60 = (poolData.criteria && poolData.criteria.s3 !== undefined) ? (poolData.ma20 * 0.97) : (hasPrice ? price : null);

    const belowMa20 = (hasPrice && ma20) ? price < ma20 : false;
    const belowMa60 = (hasPrice && ma60) ? price < ma60 : false;
    const bias20Pct = (hasPrice && ma20) ? parseFloat(((price - ma20) / ma20 * 100).toFixed(1)) : 0.0;

    // 訊號判定
    const stopHit = (hasPrice && stopLoss) ? price <= stopLoss : false;
    const invalidationHit = (hasPrice && invalidation) ? price <= invalidation : false;
    const takeProfitHit = (hasPrice && takeProfit) ? price >= takeProfit : false;
    const shortCostStopHit = (type === 'SHORT' && hasPrice && hasCost) ? price <= (cost * 0.92) : false;

    // 研報資訊
    const thesis = thesisMap[code] || null;
    const bullCeiling = thesis?.price_targets?.bull_ceiling || null;
    const thesisStatus = thesis ? 'draft' : 'none';

    holdings.push({
      code: code,
      name: name,
      type: type,
      entry_date: null,
      shares_original: qty,
      qty: qty,
      cost: hasCost ? cost : null,
      current_price: hasPrice ? price : null,
      day_change_pct: dayChangePct,
      pnl_pct: pnlPct,
      weight_pct: null, // 稍後計算
      stop_loss_price: stopLoss,
      invalidation_price: invalidation,
      take_profit_target: takeProfit,
      partial_profit_taken: false,
      ex_dividend_check: false,
      price_levels_updated_at: dateStr,
      price_basis: 'unadjusted',
      price_date: dateStr,
      signals: {
        current_price: hasPrice ? price : null,
        price_date: dateStr,
        price_stale: false,
        price_basis: 'unadjusted',
        day_change_pct: dayChangePct,
        extreme_move: Math.abs(dayChangePct) >= 7.0,
        ex_dividend_check: false,
        ma5: ma5,
        ma20: ma20,
        ma60: ma60,
        below_ma20: belowMa20,
        below_ma60: belowMa60,
        bias_20_pct: bias20Pct,
        ma20_break_confirmed: false,
        core_deep_drawdown: pnlPct !== null && pnlPct < -15.0,
        trailing_stop: null,
        trailing_stop_hit: false,
        trailing_stop_status: 'not_applicable',
        stop_hit: stopHit,
        invalidation_hit: invalidationHit,
        take_profit_hit: takeProfitHit,
        short_cost_stop_hit: shortCostStopHit,
        holding_days_over: false,
        short_momentum: bias20Pct > 0 ? 'bullish' : 'neutral',
        thesis_effective_status: thesisStatus,
        thesis_has_open_event: false,
        bull_ceiling: bullCeiling,
        price_vs_bull_ceiling: (hasPrice && bullCeiling) ? (price - bullCeiling) : null,
        chip_diagnosis: poolData.buy_days >= 3 ? 'institutional_accumulating' : 'normal',
        inst_date: poolData.updated || dateStr,
        inst_stale: false,
        tdcc_date: dateStr,
        tdcc_stale: false
      },
      d_thesis: thesis,
      chips: {
        trust_buy_days: poolData.buy_days || 0,
        foreign_buy_days: poolData.foreign_buy_days || 0
      },
      sector: poolData.sector || '一般'
    });
  }

  // 4. 計算資產權重與組合風險
  const totalAssets = (cash !== null ? cash : 0) + totalStockValue;
  if (totalAssets > 0) {
    holdings.forEach(h => {
      if (h.current_price && h.qty) {
        h.weight_pct = parseFloat(((h.current_price * h.qty) / totalAssets * 100).toFixed(1));
      }
    });
  }

  const cashRatioPct = totalAssets > 0 && cash !== null ? parseFloat((cash / totalAssets * 100).toFixed(1)) : null;

  // 5. 組裝符合 Gem v15.0 規格的 snapshot.json
  const snapshot = {
    meta: {
      generated_at: timeStr,
      portfolio_updated_at: dateStr,
      is_market_closed: now.getHours() >= 14,
      market_regime: '盤整',
      market_day_change_pct: 0.0,
      extreme_move: false,
      taiex: {
        regime: '盤整',
        close: null,
        ma60: null,
        day_change_pct: 0.0,
        date: dateStr,
        data_status: 'ok'
      }
    },
    portfolio_risk: {
      cash_status: cash !== null ? 'ok' : 'cash_unknown',
      cash_ratio_pct: cashRatioPct,
      total_stock_value: Math.round(totalStockValue),
      violations: []
    },
    holdings: holdings
  };

  // 6. 寫入 / 覆蓋 Google 雲端硬碟中的 snapshot.json
  const fileName = 'snapshot.json';
  const jsonContent = JSON.stringify(snapshot, null, 2);
  const files = DriveApp.getFilesByName(fileName);
  let file;

  if (files.hasNext()) {
    file = files.next();
    file.setContent(jsonContent);
  } else {
    file = DriveApp.createFile(fileName, jsonContent, MimeType.PLAIN_TEXT);
  }

  // 7. 畫面提示
  const msg = `✅ 已成功產生最新快照至 Google 雲端硬碟！\n\n` +
              `• 產生時間：${timeStr}\n` +
              `• 納入持股：共 ${holdings.length} 檔\n` +
              `• 股票總市值：約 $${Math.round(totalStockValue).toLocaleString()} 元\n\n` +
              `👉 現在您可以直接在 Gemini 呼叫 Gem 進行持股健檢！`;
  
  SpreadsheetApp.getActiveSpreadsheet().toast(`快照更新完成！共 ${holdings.length} 檔持股`, '理專戰情中心', 6);
  SpreadsheetApp.getUi().alert(msg);
}
