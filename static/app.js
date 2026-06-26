const state = {
  portfolio: null,
  selected: null,
  sort: { key: 'market_value_usd', dir: 'desc' }
};

const $ = (id) => document.getElementById(id);
const fmt = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 });
const fmt2 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 });

function money(value) {
  const num = Number(value || 0);
  return `${num >= 0 ? '' : '-'}$${fmt.format(Math.abs(num))}`;
}

function signedMoney(value) {
  const cls = Number(value || 0) >= 0 ? 'gain' : 'loss';
  return `<span class="${cls}">${money(value)}</span>`;
}

function pct(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '-';
  const num = Number(value) * 100;
  return `${num >= 0 ? '+' : ''}${num.toFixed(2)}%`;
}

function pctCell(value) {
  if (value === null || value === undefined) return '<span>-</span>';
  const cls = Number(value) >= 0 ? 'gain' : 'loss';
  return `<span class="${cls}">${pct(value)}</span>`;
}

function dayPct(value) {
  const num = Number(value || 0);
  return `${num >= 0 ? '+' : ''}${num.toFixed(2)}%`;
}

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
}

async function getJson(url) {
  const res = await fetch(url, { cache: 'no-store' });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

async function loadPortfolio() {
  $('sourceLine').textContent = 'Loading account...';
  const data = await getJson('/api/portfolio');
  state.portfolio = data;
  renderPortfolio(data);
  if (!state.selected && data.projects?.length) selectStock(data.projects[0].symbol);
}

function sortableValue(row, key) {
  const value = row?.[key];
  if (value === null || value === undefined || Number.isNaN(Number(value))) return null;
  return Number(value);
}

function sortHoldings(holdings) {
  const { key, dir } = state.sort;
  const multiplier = dir === 'asc' ? 1 : -1;
  return [...holdings].sort((a, b) => {
    const av = sortableValue(a, key);
    const bv = sortableValue(b, key);
    if (av === null && bv === null) return String(a.symbol).localeCompare(String(b.symbol));
    if (av === null) return 1;
    if (bv === null) return -1;
    if (av === bv) return String(a.symbol).localeCompare(String(b.symbol));
    return (av - bv) * multiplier;
  });
}

function renderSortHeaders() {
  document.querySelectorAll('th.sortable').forEach(th => {
    const label = th.dataset.label || th.textContent.replace(/[▲▼]/g, '').trim();
    th.dataset.label = label;
    if (th.dataset.sort === state.sort.key) {
      th.innerHTML = `${escapeHtml(label)} <span class="sort-indicator">${state.sort.dir === 'asc' ? '▲' : '▼'}</span>`;
    } else {
      th.innerHTML = `${escapeHtml(label)} <span class="sort-indicator muted">↕</span>`;
    }
  });
}

function renderPortfolio(data) {
  const account = data.account || {};
  $('equity').innerHTML = money(account.equity_usd);
  $('totalPnl').innerHTML = signedMoney(account.total_pnl_usd);
  $('totalPct').textContent = pct(account.total_pnl_pct);
  $('realizedPnl').innerHTML = signedMoney(account.realized_pnl_usd);
  $('unrealizedPnl').innerHTML = signedMoney(account.unrealized_pnl_usd);
  renderFx(data.fx || {});

  const src = data.source || {};
  $('sourceLine').textContent = src.ok
    ? `Initial Excel: ${src.file} / Manual trades: ${data.transactions?.filter(t => t.source === 'manual_ledger').length || 0}`
    : `Initial Excel not loaded: ${src.error || 'unknown'} / Manual ledger remains active`;

  const holdings = sortHoldings(data.holdings || []);
  $('holdingCount').textContent = holdings.length;
  renderSortHeaders();
  $('holdingsBody').innerHTML = holdings.map(h => `
    <tr>
      <td class="symbol" data-symbol="${escapeHtml(h.symbol)}">${escapeHtml(h.symbol)}</td>
      <td>${fmt2.format(h.quantity || 0)}</td>
      <td>${fmt2.format(h.avg_cost || 0)} ${escapeHtml(h.currency || '')}</td>
      <td>${fmt2.format(h.last_price || 0)}</td>
      <td>${money(h.market_value_usd)}</td>
      <td>${signedMoney(h.unrealized_pnl_usd)}</td>
      <td class="${(h.changes_percentage || 0) >= 0 ? 'gain' : 'loss'}">${dayPct(h.changes_percentage)}</td>
      <td>${pctCell(h.rs_vs_nq_20d)}</td>
      <td>${pctCell(h.rs_vs_sp_20d)}</td>
    </tr>
  `).join('');

  document.querySelectorAll('td.symbol').forEach(el => {
    el.addEventListener('click', () => selectStock(el.dataset.symbol));
  });

  const projects = data.projects || [];
  $('projectCount').textContent = `${account.active_project_count || 0} active / ${account.closed_project_count || 0} closed`;
  $('projectList').innerHTML = projects.map(p => `
    <div class="project ${escapeHtml(p.status)}" data-symbol="${escapeHtml(p.symbol)}">
      <strong>${escapeHtml(p.symbol)} <span>${escapeHtml(p.status)}</span></strong>
      <small>Qty ${fmt2.format(p.quantity || 0)} / Realized ${money((p.realized_pnl || 0) * (p.fx_to_usd || 1))}</small>
      <small>Unrealized ${money(p.unrealized_pnl_usd || 0)} / Last trade ${p.last_trade_date || '-'}</small>
    </div>
  `).join('');
  document.querySelectorAll('.project').forEach(el => {
    el.addEventListener('click', () => selectStock(el.dataset.symbol));
  });

  $('realizedBody').innerHTML = (data.realized || []).slice().reverse().map(r => `
    <tr>
      <td>${r.date || '-'}</td>
      <td>${escapeHtml(r.symbol)}</td>
      <td>${fmt2.format(r.quantity || 0)}</td>
      <td>${fmt2.format(r.price || 0)}</td>
      <td>${signedMoney(r.realized_pnl_usd)}</td>
      <td>${escapeHtml(r.source || '-')}</td>
    </tr>
  `).join('');
}

function renderFx(fx) {
  const spot = fx.spot || {};
  const toUsd = fx.to_usd || {};
  $('fxLine').textContent = `Spot FX used: USD/HKD ${fmt2.format(spot.USDHKD || 0)} / HKD/USD ${Number(toUsd.HKD || 0).toFixed(5)} / CNY/USD ${Number(toUsd.CNY || 0).toFixed(5)} / refreshed ${fx.updated_at ? new Date(fx.updated_at).toLocaleTimeString() : '-'}`;
}

async function loadIndexes() {
  $('indexList').textContent = 'Loading index overview...';
  const data = await getJson('/api/indexes');
  renderIndexes(data);
}

function renderIndexes(data) {
  $('indexList').innerHTML = (data.items || []).map(item => {
    if (!item.available) {
      return `<div class="index-card"><strong>${escapeHtml(item.name)} <span>${escapeHtml(item.symbol)}</span></strong><p>${escapeHtml(item.comment || 'No data')}</p></div>`;
    }
    return `
      <div class="index-card">
        <strong>${escapeHtml(item.name)} <span>${escapeHtml(item.symbol)}</span></strong>
        <div class="index-price">${fmt2.format(item.last || 0)} <span class="${(item.day_return || 0) >= 0 ? 'gain' : 'loss'}">${pct(item.day_return)}</span></div>
        <div class="index-row"><span>5D</span>${pctCell(item.return_5d)}<span>20D</span>${pctCell(item.return_20d)}<span>60D</span>${pctCell(item.return_60d)}</div>
        <p><b>${escapeHtml(item.trend || '-')}</b> ${escapeHtml(item.comment || '')}</p>
      </div>
    `;
  }).join('');
}

async function selectStock(symbol) {
  if (!symbol) return;
  state.selected = symbol;
  $('stockTitle').textContent = symbol;
  $('stockStatus').textContent = 'Loading stock analysis...';
  $('signals').innerHTML = '';
  $('newsList').innerHTML = '';
  $('adviceBox').innerHTML = '';
  const data = await getJson(`/api/stock/${encodeURIComponent(symbol)}`);
  renderStock(data);
}

function renderStock(data) {
  $('stockStatus').textContent = `Updated ${new Date(data.updated_at).toLocaleString()}`;
  const tech = data.technical || {};
  drawPriceChart(tech.history || []);
  const advice = tech.advice || {};
  $('adviceBox').innerHTML = `
    <p><strong>短期：</strong>${escapeHtml(advice.short_term || '-')}</p>
    <p><strong>中期：</strong>${escapeHtml(advice.medium_term || '-')}</p>
  `;
  $('signals').innerHTML = (tech.signals || []).map(x => `<li>${escapeHtml(x)}</li>`).join('');
  renderVolumeProfile(tech.levels?.volume_profile || []);
  renderOptions(data.options || {});
  const sentiment = data.news?.sentiment || {};
  $('heatLine').textContent = `Heat ${sentiment.heat || 0}/100 / Tone ${sentiment.comment || 'neutral'}`;
  const news = data.news?.items || [];
  $('newsList').innerHTML = news.length ? news.map(n => `
    <li><a href="${n.url || '#'}" target="_blank" rel="noreferrer">${escapeHtml(n.title || 'Untitled')}</a>
    <small>${escapeHtml(n.site || '')} / ${escapeHtml(n.publishedDate || '')}</small></li>
  `).join('') : '<li>过去24小时没有返回相关新闻。</li>';
}

function drawPriceChart(rows) {
  const canvas = $('priceChart');
  const ctx = canvas.getContext('2d');
  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = '#fff';
  ctx.fillRect(0, 0, w, h);
  if (!rows.length) {
    ctx.fillStyle = '#68727f';
    ctx.fillText('No price history', 24, 32);
    return;
  }
  const pad = { l: 52, r: 20, t: 24, b: 34 };
  const data = rows.slice(-160);
  const values = data.flatMap(r => [r.high, r.low, r.sma20, r.sma50].filter(Boolean));
  const min = Math.min(...values);
  const max = Math.max(...values);
  const x = i => pad.l + (i / Math.max(1, data.length - 1)) * (w - pad.l - pad.r);
  const y = v => pad.t + (max - v) / Math.max(0.0001, max - min) * (h - pad.t - pad.b);

  ctx.strokeStyle = '#dce1e7';
  ctx.lineWidth = 1;
  for (let i = 0; i < 5; i++) {
    const yy = pad.t + i * (h - pad.t - pad.b) / 4;
    ctx.beginPath();
    ctx.moveTo(pad.l, yy);
    ctx.lineTo(w - pad.r, yy);
    ctx.stroke();
  }

  data.forEach((r, i) => {
    const xx = x(i);
    const up = r.close >= r.open;
    ctx.strokeStyle = up ? '#2f8f6f' : '#b64242';
    ctx.beginPath();
    ctx.moveTo(xx, y(r.low));
    ctx.lineTo(xx, y(r.high));
    ctx.stroke();
    const top = y(Math.max(r.open, r.close));
    const bot = y(Math.min(r.open, r.close));
    ctx.fillStyle = up ? '#2f8f6f' : '#b64242';
    ctx.fillRect(xx - 2, top, 4, Math.max(1, bot - top));
  });

  drawLine(ctx, data, 'sma20', x, y, '#176b87');
  drawLine(ctx, data, 'sma50', x, y, '#a66a00');
  ctx.fillStyle = '#68727f';
  ctx.fillText(`${data[0].date} to ${data[data.length - 1].date}`, pad.l, h - 12);
  ctx.fillText(`High ${max.toFixed(2)} / Low ${min.toFixed(2)}`, pad.l, 16);
}

function drawLine(ctx, data, key, x, y, color) {
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.6;
  ctx.beginPath();
  let started = false;
  data.forEach((r, i) => {
    if (!r[key]) return;
    if (!started) {
      ctx.moveTo(x(i), y(r[key]));
      started = true;
    } else {
      ctx.lineTo(x(i), y(r[key]));
    }
  });
  ctx.stroke();
}

function renderVolumeProfile(rows) {
  const max = Math.max(...rows.map(r => r.volume || 0), 1);
  $('volumeProfile').innerHTML = rows.length ? rows.map(r => `
    <div class="bar-row"><span>${fmt2.format(r.price)}</span><div class="bar-track"><div class="bar-fill" style="width:${(r.volume / max * 100).toFixed(1)}%"></div></div><small>${fmt.format(r.volume)}</small></div>
  `).join('') : '<p>暂无筹码/成交密集区数据。</p>';
}

function renderOptions(opt) {
  if (!opt.available) {
    $('optionsBox').innerHTML = `<p>${escapeHtml(opt.note || 'No options data.')}</p>`;
    return;
  }
  const summary = opt.summary || {};
  const max = Math.max(...opt.distribution.map(r => Math.max(r.call_oi || 0, r.put_oi || 0)), 1);
  const sorted = [...opt.distribution].sort((a, b) => (b.call_oi + b.put_oi) - (a.call_oi + a.put_oi)).slice(0, 14);
  const header = `
    <div class="option-summary">
      <p><strong>来源：</strong>${escapeHtml(opt.source || '-')} ${opt.timestamp ? '/ ' + escapeHtml(opt.timestamp) : ''}</p>
      <p><strong>Put/Call OI：</strong>${summary.put_call_oi_ratio == null ? '-' : fmt2.format(summary.put_call_oi_ratio)}
      / <strong>Call/Put OI：</strong>${summary.call_put_oi_ratio == null ? '-' : fmt2.format(summary.call_put_oi_ratio)}</p>
      <p><strong>最近到期：</strong>${summary.nearest_expiry || '-'} / 最大 Call OI strike ${summary.nearest_max_call_oi_strike ?? '-'} / 最大 Put OI strike ${summary.nearest_max_put_oi_strike ?? '-'}</p>
    </div>
  `;
  const bars = sorted.map(r => `
    <div class="option-row">
      <span class="strike">${fmt2.format(r.strike)}</span>
      <span class="oi-label">C ${fmt.format(r.call_oi)}</span>
      <div class="mini-track"><div class="bar-fill" style="width:${(r.call_oi / max * 100).toFixed(1)}%"></div></div>
      <span class="oi-label">P ${fmt.format(r.put_oi)}</span>
      <div class="mini-track"><div class="bar-fill put" style="width:${(r.put_oi / max * 100).toFixed(1)}%"></div></div>
    </div>
  `).join('');
  $('optionsBox').innerHTML = header + `<div class="options-compact">${bars}</div>`;
}

async function loadMacro() {
  $('macroList').textContent = 'Loading macro updates...';
  $('macroAnalysis').innerHTML = '';
  const data = await getJson('/api/macro');
  $('macroAnalysis').innerHTML = (data.analysis || []).map(x => `<p>${escapeHtml(x)}</p>`).join('');
  $('macroList').innerHTML = (data.items || []).map(item => `
    <div class="macro-item macro-${escapeHtml(item.priority || 'normal')}">
      <strong><span class="macro-tag">${escapeHtml(item.category || '宏观')}</span>${escapeHtml(item.event || 'Macro event')}</strong>
      <small>${item.date || ''} / ${item.country || ''} / ${item.impact || ''} / ${escapeHtml(item.source || 'source')}</small>
      <p>Actual ${item.actual ?? '-'} / Estimate ${item.estimate ?? '-'} / Previous ${item.previous ?? '-'}</p>
      <p>${escapeHtml(item.comment || '')}</p>
    </div>
  `).join('');
}

function wireEvents() {
  $('refreshBtn').addEventListener('click', async () => {
    await loadPortfolio();
    await loadIndexes();
  });
  $('macroBtn').addEventListener('click', loadMacro);
  $('indexBtn').addEventListener('click', loadIndexes);
  document.querySelectorAll('th.sortable').forEach(th => {
    th.addEventListener('click', () => {
      const key = th.dataset.sort;
      if (state.sort.key === key) {
        state.sort.dir = state.sort.dir === 'desc' ? 'asc' : 'desc';
      } else {
        state.sort = { key, dir: 'desc' };
      }
      if (state.portfolio) renderPortfolio(state.portfolio);
    });
  });

  $('tradeForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const payload = Object.fromEntries(form.entries());
    $('tradeMsg').textContent = 'Saving trade...';
    const res = await fetch('/api/trades', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (data.ok) {
      $('tradeMsg').textContent = `Saved ${data.trade.side} ${data.trade.quantity} ${data.trade.symbol}`;
      event.currentTarget.reset();
      await loadPortfolio();
      await loadIndexes();
      await selectStock(data.trade.fmp_symbol);
    } else {
      $('tradeMsg').textContent = data.error || 'Failed to save trade.';
    }
  });

  $('naturalForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    const text = new FormData(event.currentTarget).get('text');
    $('tradeMsg').textContent = 'Parsing trade text...';
    const res = await fetch('/api/parse-trade', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text })
    });
    const data = await res.json();
    if (!data.ok) {
      $('tradeMsg').textContent = data.error || 'Could not parse trade.';
      return;
    }
    const form = $('tradeForm');
    for (const [key, value] of Object.entries(data.trade)) {
      if (form.elements[key]) form.elements[key].value = value ?? '';
    }
    $('tradeMsg').textContent = `Parsed ${data.trade.side} ${data.trade.quantity} ${data.trade.symbol} @ ${fmt2.format(data.trade.price)} ${data.trade.currency}; fee ${fmt2.format(data.trade.fee)}. Click Add Trade to save.`;
  });

  $('excelUpload').addEventListener('change', async (event) => {
    const file = event.target.files[0];
    if (!file) return;
    const form = new FormData();
    form.append('file', file);
    $('sourceLine').textContent = 'Uploading initial Excel...';
    const res = await fetch('/api/upload', { method: 'POST', body: form });
    const data = await res.json();
    $('sourceLine').textContent = data.message || data.error || 'Upload complete';
    await loadPortfolio();
    await loadIndexes();
  });
}

wireEvents();
Promise.all([loadPortfolio(), loadMacro(), loadIndexes()]).catch(err => {
  $('sourceLine').textContent = `Load failed: ${err.message}`;
});
