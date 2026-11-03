const $ = id => document.getElementById(id);
const PER_PAGE = 20;
let unitTimer = null;
let importTimer = null;
let toastTimer = null;
let current = null;
let detailTab = 'procedures';
let page = 1;

const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fmt = n => Number(n || 0).toLocaleString('pt-BR');
const money = cents => (Number(cents || 0) / 100).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
const signed = n => (n > 0 ? '+' : '') + fmt(n);
const pctText = p => (p === null || p === undefined) ? 'novo' : (p > 0 ? '+' : '') + p.toLocaleString('pt-BR', { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + '%';
const tone = n => n > 0 ? 'rep-blue-text' : n < 0 ? 'rep-red-text' : '';
const deltaClass = n => n > 0 ? 'positive' : n < 0 ? 'negative' : 'neutral';
const unitCode = value => (String(value || '').match(/\d{7}/) || [''])[0];
const errorText = data => typeof data.detail === 'string' ? data.detail : 'Verifique os campos e tente de novo.';
const competenceLabel = c => c ? `${c.slice(4)}/${c.slice(0, 4)}` : '';

function showView(view) {
  $('overview').hidden = view !== 'overview';
  $('reports').hidden = view !== 'reports';
  document.querySelectorAll('.nav-item').forEach(a => a.classList.toggle('active', a.dataset.view === view));
}

function toast(text) {
  const t = $('toast');
  t.textContent = text;
  t.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove('show'), 4000);
}

function showNote(text) {
  $('filterNote').textContent = text;
}

function setMessage(text) {
  $('reportMessage').textContent = text;
}

async function searchUnits(term) {
  const res = await fetch(`/api/units?q=${encodeURIComponent(term)}`);
  if (!res.ok) return;
  const list = await res.json();
  $('unitList').innerHTML = list.map(u => `<option value="${esc(u.cnes)}">${esc(u.name)}</option>`).join('');
}

async function loadStatus() {
  const res = await fetch('/api/status');
  if (!res.ok) return null;
  const s = await res.json();
  $('footLeft').textContent = s.imported_files
    ? `${fmt(s.imported_files)} arquivos DBC importados · de ${competenceLabel(s.first_competence)} a ${competenceLabel(s.last_competence)}`
    : 'Aguardando importação dos arquivos DBC.';
  return s;
}

async function fetchReport({ cnes, start, end, compare, exams, procedures }) {
  const params = new URLSearchParams({ cnes, start, end, compare, exams, procedures });
  const res = await fetch(`/api/report?${params}`);
  const data = await res.json();
  if (!res.ok) throw new Error(errorText(data));
  return data;
}

async function applyFilters() {
  const cnes = unitCode($('unitSearch').value);
  const start = $('startMonth').value;
  const end = $('endMonth').value;
  if (!cnes || !start || !end) return showNote('Selecione um estabelecimento e um período para visualizar a produção.');
  if (start > end) return showNote('A competência inicial deve ser igual ou anterior à final.');
  showNote('Carregando produção…');
  try {
    current = await fetchReport({ cnes, start, end, compare: $('compare').checked, exams: true, procedures: true });
    page = 1;
    const empty = !current.summary.quantity && !current.exam_items.length && !current.procedure_items.length;
    showNote(empty ? 'Não há produção aprovada para esta unidade no período selecionado.' : '');
    renderOverview();
  } catch (err) {
    current = null;
    renderOverview();
    showNote(err.message);
  }
}

function renderOverview() {
  const d = current;
  if (!d) {
    ['mQty', 'mValue', 'mDistinct', 'mSubmitted'].forEach(id => { $(id).textContent = '—'; });
    $('mQtyFoot').textContent = 'vs. mesmo período anterior';
    $('prevLegend').hidden = true;
    $('chart').innerHTML = '<div class="empty-state">Selecione uma unidade para carregar o gráfico.</div>';
    $('highlights').innerHTML = '<div class="empty-state">Os destaques aparecerão após selecionar os filtros.</div>';
    renderDetail();
    return;
  }
  const s = d.summary;
  const items = [...d.exam_items, ...d.procedure_items];
  $('mQty').textContent = fmt(s.quantity);
  $('mQtyFoot').innerHTML = !d.compare
    ? 'Ative a comparação para ver a variação'
    : s.pct === null
      ? 'Sem produção no ano anterior'
      : `<span class="change-badge ${deltaClass(s.pct)}">${pctText(s.pct)}</span> vs. mesmo período anterior`;
  $('mValue').textContent = money(s.value_cents);
  $('mDistinct').textContent = fmt(items.filter(i => i.qty > 0).length);
  $('mSubmitted').textContent = fmt(s.submitted);
  $('prevLegend').hidden = !d.compare;
  $('chart').innerHTML = chartSvg(d.monthly, d.compare);
  renderHighlights(items, d.compare);
  renderDetail();
}

function renderHighlights(items, compare) {
  const box = $('highlights');
  if (!compare) {
    box.innerHTML = '<div class="empty-state">Marque “Comparar com mesmo período do ano anterior” para ver as variações.</div>';
    return;
  }
  const top = items.filter(i => i.diff !== 0).sort((a, b) => Math.abs(b.diff) - Math.abs(a.diff)).slice(0, 8);
  if (!top.length) {
    box.innerHTML = '<div class="empty-state">Sem variações no período.</div>';
    return;
  }
  box.innerHTML = top.map(i => `<div class="highlight-row">
    <div><span class="highlight-name">${esc(i.name || 'Sem descrição cadastrada')}</span><span class="highlight-code">${esc(i.code)}</span></div>
    <span class="highlight-change ${i.diff > 0 ? 'increase' : 'decrease'}">${signed(i.diff)} (${pctText(i.pct)})</span>
  </div>`).join('');
}

function renderDetail() {
  const body = $('detailBody');
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === detailTab));
  if (!current) {
    body.innerHTML = '<tr><td colspan="5" class="table-empty">Selecione uma unidade para ver os procedimentos.</td></tr>';
    $('detailFoot').textContent = 'Aguardando filtros';
    $('pageIndicator').textContent = 'Página 1 de 1';
    $('prevPage').disabled = true;
    $('nextPage').disabled = true;
    return;
  }
  const term = $('detailSearch').value.trim().toLowerCase();
  const sort = $('detailSort').value;
  const source = detailTab === 'exams' ? current.exam_items : current.procedure_items;
  const rows = source
    .filter(i => !term || i.code.toLowerCase().includes(term) || (i.name || '').toLowerCase().includes(term))
    .sort((a, b) => sort === 'diff' ? b.diff - a.diff : sort === 'value' ? b.value_cents - a.value_cents : b.qty - a.qty);
  const pages = Math.max(1, Math.ceil(rows.length / PER_PAGE));
  page = Math.min(page, pages);
  const slice = rows.slice((page - 1) * PER_PAGE, page * PER_PAGE);
  const compare = current.compare;
  body.innerHTML = slice.length
    ? slice.map(i => `<tr>
        <td><span class="procedure-name">${esc(i.name || 'Sem descrição cadastrada')}</span><span class="procedure-code">${esc(i.code)}</span></td>
        <td>${fmt(i.qty)}</td>
        <td>${compare ? fmt(i.prev_qty) : '—'}</td>
        <td class="delta-cell ${compare ? deltaClass(i.diff) : 'neutral'}">${compare ? `${signed(i.diff)} (${pctText(i.pct)})` : '—'}</td>
        <td>${money(i.value_cents)}</td>
      </tr>`).join('')
    : '<tr><td colspan="5" class="table-empty">Nenhum item encontrado.</td></tr>';
  $('detailFoot').textContent = `${fmt(rows.length)} ${detailTab === 'exams' ? 'exames' : 'procedimentos'}`;
  $('pageIndicator').textContent = `Página ${page} de ${pages}`;
  $('prevPage').disabled = page <= 1;
  $('nextPage').disabled = page >= pages;
}

function chartSvg(rows, compare) {
  const W = 760, H = 230, L = 52, R = 16, T = 16, B = 30;
  const iw = W - L - R, ih = H - T - B;
  const max = Math.max(1, ...rows.map(r => r.total_qty), ...(compare ? rows.map(r => r.prev_total_qty) : []));
  const x = i => rows.length === 1 ? L + iw / 2 : L + (i * iw) / (rows.length - 1);
  const y = v => T + ih - (v / max) * ih;
  const path = key => rows.map((r, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)} ${y(r[key]).toFixed(1)}`).join(' ');
  const grid = [0, 1, 2, 3, 4].map(k => {
    const v = (max * k) / 4;
    const yy = y(v).toFixed(1);
    return `<line class="chart-grid" x1="${L}" x2="${W - R}" y1="${yy}" y2="${yy}"/><text class="chart-axis" x="${L - 8}" y="${yy}" text-anchor="end" dominant-baseline="middle">${fmt(Math.round(v))}</text>`;
  }).join('');
  const step = Math.ceil(rows.length / 12);
  const xLabels = rows.map((r, i) => i % step === 0 ? `<text class="chart-axis" x="${x(i).toFixed(1)}" y="${H - 8}" text-anchor="middle">${esc(r.label)}</text>` : '').join('');
  const points = rows.map((r, i) => `<circle class="chart-point" cx="${x(i).toFixed(1)}" cy="${y(r.total_qty).toFixed(1)}" r="3.5"/>`).join('');
  const values = rows.length <= 12
    ? rows.map((r, i) => `<text class="chart-label" x="${x(i).toFixed(1)}" y="${(y(r.total_qty) - 9).toFixed(1)}">${fmt(r.total_qty)}</text>`).join('')
    : '';
  const previous = compare
    ? `<path class="chart-previous-line" d="${path('prev_total_qty')}"/>` +
      rows.map((r, i) => `<circle class="chart-point-previous" cx="${x(i).toFixed(1)}" cy="${y(r.prev_total_qty).toFixed(1)}" r="3"/>`).join('')
    : '';
  const area = `${path('total_qty')} L${x(rows.length - 1).toFixed(1)} ${T + ih} L${x(0).toFixed(1)} ${T + ih} Z`;
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Evolução mensal">
    <defs><linearGradient id="currentFill" x1="0" x2="0" y1="0" y2="1">
      <stop offset="0" stop-color="#15966a" stop-opacity=".22"/><stop offset="1" stop-color="#15966a" stop-opacity="0"/>
    </linearGradient></defs>
    ${grid}${previous}
    <path class="chart-current-area" d="${area}"/>
    <path class="chart-current-line" d="${path('total_qty')}"/>
    ${points}${values}${xLabels}
  </svg>`;
}

function watchImport() {
  const drawer = $('importDrawer');
  drawer.hidden = false;
  drawer.classList.remove('done');
  clearInterval(importTimer);
  const tick = async () => {
    const res = await fetch('/api/import/status');
    if (!res.ok) return;
    const s = await res.json();
    const pct = s.total ? Math.round((s.current * 100) / s.total) : 0;
    if (s.running) {
      $('importTitle').textContent = 'Importando DBCs…';
      $('importText').textContent = `${s.current} de ${s.total}${s.file ? ' · ' + s.file : ''}`;
      $('importBar').style.width = pct + '%';
      return;
    }
    clearInterval(importTimer);
    drawer.classList.add('done');
    $('importBar').style.width = '100%';
    if (s.status === 'error') {
      $('importTitle').textContent = 'Falha na importação';
      $('importText').textContent = s.message || 'Veja o terminal do servidor.';
    } else {
      const r = s.result || {};
      const errors = (r.errors || []).length;
      $('importTitle').textContent = errors ? 'Importação concluída com erros' : 'Importação concluída';
      $('importText').textContent = `${fmt(r.imported)} importados · ${fmt(r.skipped)} já atualizados · ${fmt(errors)} com erro`;
      await loadStatus();
      if (current) applyFilters();
    }
  };
  tick();
  importTimer = setInterval(tick, 1000);
}

async function uploadDbcs(fileList) {
  const files = [...fileList].filter(f => /^PASP\d{4}[a-d]\.dbc$/i.test(f.name));
  if (!files.length) return toast('Selecione arquivos no padrão PASPaamm[a-d].dbc exportados do TabWin.');
  const form = new FormData();
  files.forEach(f => form.append('files', f));
  $('dbcInput').value = '';
  try {
    const res = await fetch('/api/import', { method: 'POST', body: form });
    const data = await res.json();
    if (!res.ok) throw new Error(errorText(data));
    watchImport();
  } catch (err) {
    toast(err.message);
  }
}

async function exportReport() {
  if (!current) return toast('Aplique os filtros antes de exportar.');
  $('repUnit').value = $('unitSearch').value;
  $('repStart').value = $('startMonth').value;
  $('repEnd').value = $('endMonth').value;
  $('repCompare').checked = $('compare').checked;
  $('repExams').checked = true;
  $('repProcs').checked = true;
  showView('reports');
  await generateReport();
}

async function generateReport() {
  const cnes = unitCode($('repUnit').value);
  const start = $('repStart').value;
  const end = $('repEnd').value;
  if (!cnes) return setMessage('Informe o CNES da unidade (7 números).');
  if (!start || !end) return setMessage('Escolha o mês inicial e o mês final.');
  if (start > end) return setMessage('O mês inicial deve ser igual ou anterior ao mês final.');
  if (!$('repExams').checked && !$('repProcs').checked) return setMessage('Marque exames, procedimentos ou ambos.');
  setMessage('Gerando relatório…');
  try {
    const data = await fetchReport({
      cnes,
      start,
      end,
      compare: $('repCompare').checked,
      exams: $('repExams').checked,
      procedures: $('repProcs').checked,
    });
    renderReport(data);
    setMessage('');
  } catch (err) {
    $('reportView').hidden = true;
    $('reportToolbar').hidden = true;
    setMessage(err.message);
  }
}

function itemTable(title, items, compare) {
  if (!items.length) return '';
  const rows = items.map(i => `<tr>
    <td><span class="procedure-name">${esc(i.name || 'Sem descrição cadastrada')}</span><span class="procedure-code">${esc(i.code)}</span></td>
    <td>${fmt(i.qty)}</td>
    ${compare ? `<td>${fmt(i.prev_qty)}</td><td class="${tone(i.diff)}">${signed(i.diff)} (${pctText(i.pct)})</td>` : ''}
    <td>${money(i.value_cents)}</td>
  </tr>`).join('');
  return `<h3>${esc(title)}</h3>
    <div class="table-scroll"><table class="rep-table">
      <thead><tr><th>Código e descrição</th><th>Quantidade aprovada</th>${compare ? '<th>Ano anterior</th><th>Variação</th>' : ''}<th>Valor aprovado</th></tr></thead>
      <tbody>${rows}</tbody>
    </table></div>`;
}

function renderReport(d) {
  const compare = d.compare;
  const s = d.summary;
  const unitName = d.facility.name || 'Unidade sem nome cadastrado';
  const monthRows = d.monthly.map(r => `<tr>
    <td>${esc(r.label)}</td><td>${fmt(r.total_qty)}</td>
    ${compare ? `<td>${fmt(r.prev_total_qty)}</td><td class="${tone(r.diff)}">${signed(r.diff)} (${pctText(r.pct)})</td>` : ''}
  </tr>`).join('');
  const totalRow = `<tr>
    <th>Total</th><th>${fmt(s.quantity)}</th>
    ${compare ? `<th>${fmt(s.previous_quantity)}</th><th class="${tone(s.quantity - s.previous_quantity)}">${signed(s.quantity - s.previous_quantity)} (${pctText(s.pct)})</th>` : ''}
  </tr>`;
  const examCount = d.exam_items.length;
  const examQty = d.exam_items.reduce((acc, i) => acc + i.qty, 0);
  const empty = s.quantity === 0 && d.exam_items.length === 0 && d.procedure_items.length === 0
    ? '<p>Não há produção aprovada para esta unidade no período selecionado.</p>'
    : '';

  $('reportContent').innerHTML = `
    <header class="rep-header">
      <img src="/img/brasao.png" alt="Brasão">
      <div class="rep-org">
        <div class="rep-org-main">PREFEITURA MUNICIPAL DE TAUBATÉ</div>
        <div class="rep-org-sub">SECRETARIA DE SAÚDE</div>
      </div>
    </header>

    <div class="rep-title-block">
      <div class="rep-title">Relatório de Produção Ambulatorial</div>
      <div class="rep-sub">${esc(unitName)} · CNES ${esc(d.facility.cnes)}</div>
    </div>

    <section class="rep-section">
      <h3>Apresentação e Escopo do Relatório</h3>
      <p>Este relatório apresenta a produção ambulatorial aprovada da unidade <b>${esc(unitName)}</b>, no período de <b>${esc(d.period.label)}</b>, a partir dos arquivos de produção (PA) do SIA/SUS importados pelo painel.${compare ? ' A comparação considera o mesmo período do ano anterior.' : ''}</p>
      ${empty}
    </section>

    <section class="rep-section">
      <h3>Análise Temporal e Evolução Mensal da Produção</h3>
      <div class="table-scroll"><table class="rep-table">
        <thead><tr><th>Mês</th><th>Quantidade aprovada</th>${compare ? '<th>Ano anterior</th><th>Variação</th>' : ''}</tr></thead>
        <tbody>${monthRows}${totalRow}</tbody>
      </table></div>
    </section>

    <section class="rep-section">
      <h3>Gráfico de Evolução</h3>
      <div class="chart-legend">
        <span><i class="legend-dot current-dot"></i>Período selecionado</span>
        ${compare ? '<span><i class="legend-dot previous-dot"></i>Ano anterior</span>' : ''}
      </div>
      <div class="chart-area rep-chart">${chartSvg(d.monthly, compare)}</div>
    </section>

    ${d.exams ? `<section class="rep-section">
      <h3>Detalhamento Exaustivo dos Exames</h3>
      <p>No período foram encontrados <b>${fmt(examCount)}</b> exames diferentes, somando <b>${fmt(examQty)}</b> procedimentos aprovados.</p>
    </section>` : ''}

    <section class="rep-section">
      <h3>Tabela de Procedimentos Ambulatoriais</h3>
      ${d.exams ? itemTable('Exames', d.exam_items, compare) : ''}
      ${d.procedures ? itemTable('Procedimentos', d.procedure_items, compare) : ''}
    </section>
  `;
  $('reportView').hidden = false;
  $('reportToolbar').hidden = false;
}

document.addEventListener('DOMContentLoaded', async () => {
  const toolbar = document.createElement('div');
  toolbar.id = 'reportToolbar';
  toolbar.className = 'report-toolbar';
  toolbar.hidden = true;
  toolbar.innerHTML = '<button id="pdfBtn" class="button button-primary" type="button">Exportar PDF</button>';
  $('reportView').before(toolbar);
  $('pdfBtn').addEventListener('click', () => window.print());

  const now = new Date();
  const ym = (y, m) => `${y}-${String(m).padStart(2, '0')}`;
  const startValue = ym(now.getFullYear(), 1);
  const endValue = ym(now.getFullYear(), now.getMonth() + 1);
  $('startMonth').value = startValue;
  $('endMonth').value = endValue;
  $('repStart').value = startValue;
  $('repEnd').value = endValue;

  $('applyFilters').addEventListener('click', applyFilters);
  $('refreshBtn').addEventListener('click', () => { loadStatus(); applyFilters(); });
  $('importBtn').addEventListener('click', () => $('dbcInput').click());
  $('dbcInput').addEventListener('change', e => uploadDbcs(e.target.files));
  $('importClose').addEventListener('click', () => { $('importDrawer').hidden = true; });
  $('exportBtn').addEventListener('click', exportReport);

  document.querySelectorAll('.tab').forEach(tab => tab.addEventListener('click', () => {
    detailTab = tab.dataset.tab;
    page = 1;
    renderDetail();
  }));
  $('detailSearch').addEventListener('input', () => { page = 1; renderDetail(); });
  $('detailSort').addEventListener('change', () => { page = 1; renderDetail(); });
  $('prevPage').addEventListener('click', () => { page -= 1; renderDetail(); });
  $('nextPage').addEventListener('click', () => { page += 1; renderDetail(); });

  $('generateReport').addEventListener('click', generateReport);
  ['repCompare', 'repExams', 'repProcs'].forEach(id => {
    $(id).addEventListener('change', () => { if (!$('reportView').hidden) generateReport(); });
  });

  ['repUnit', 'unitSearch'].forEach(id => {
    $(id).addEventListener('input', e => {
      clearTimeout(unitTimer);
      unitTimer = setTimeout(() => searchUnits(e.target.value), 250);
    });
  });

  searchUnits('');
  const s = await loadStatus().catch(() => null);
  if (s && s.import && s.import.running) watchImport();
  renderOverview();
});