const $ = id => document.getElementById(id);
const PER_PAGE = 20;
let unitTimer = null;
let importTimer = null;
let toastTimer = null;
let current = null;
let detailTab = 'procedures';
let page = 1;
let unitResults = [];
let hospitalReport = null;
let hospitalReportDocument = null;
let hospitalPage = 1;
let hospitalImportTimer = null;
let hospitalPeriodInitialized = false;
let hospitalDocumentPeriodInitialized = false;
let documentTitleBeforePrint = null;
let unitSettings = { ambulatory: [], hospital: [] };
let unitSettingsLoaded = false;
let databaseSettingsLoaded = false;
const HOSPITAL_PAGE_SIZE = 20;

const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fmt = n => Number(n || 0).toLocaleString('pt-BR');
const money = cents => (Number(cents || 0) / 100).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
const signed = n => (n > 0 ? '+' : '') + fmt(n);
const pctText = p => (p === null || p === undefined) ? 'novo' : (p > 0 ? '+' : '') + p.toLocaleString('pt-BR', { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + '%';
const rateText = p => p === null || p === undefined ? '—' : `${p.toLocaleString('pt-BR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`;
const rateChangeText = (currentRate, previousRate, compare) => {
  if (!compare) return 'Comparação anual desativada';
  if (currentRate === null || currentRate === undefined) return 'Sem base de cálculo no período';
  if (previousRate === null || previousRate === undefined) return 'Sem base de cálculo no ano anterior';
  const difference = Math.round((currentRate - previousRate) * 10) / 10;
  const formatted = difference.toLocaleString('pt-BR', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  return `${difference > 0 ? '+' : ''}${formatted} p.p. vs. mesmo período do ano anterior`;
};
const oneDecimal = value => Number(value).toLocaleString('pt-BR', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const rateDeltaText = value => value === null || value === undefined
  ? '—' : `${value > 0 ? '+' : ''}${oneDecimal(value)} p.p.`;
const tone = n => n > 0 ? 'rep-blue-text' : n < 0 ? 'rep-red-text' : '';
const deltaClass = n => n > 0 ? 'positive' : n < 0 ? 'negative' : 'neutral';
const unitCode = value => (String(value || '').match(/\d{7}/) || [''])[0];
const errorText = data => typeof data.detail === 'string' ? data.detail : 'Verifique os campos e tente de novo.';
const competenceLabel = c => c ? `${c.slice(4)}/${c.slice(0, 4)}` : '';

function showView(view) {
  $('overview').hidden = view !== 'overview';
  $('reports').hidden = view !== 'reports';
  $('diverse').hidden = view !== 'diverse';
  $('hospital').hidden = view !== 'hospital';
  $('hospitalReports').hidden = view !== 'hospitalReports';
  $('settings').hidden = view !== 'settings';
  document.querySelectorAll('.nav-item').forEach(a => a.classList.toggle('active', a.dataset.view === view));
  if (view === 'hospital') loadHospitalStatus();
  if (view === 'hospitalReports') loadHospitalStatus();
  if (view === 'settings') loadSettings();
}

function toast(text) {
  const t = $('toast');
  t.textContent = text;
  t.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove('show'), 4000);
}

function showImportErrors(errors) {
  const toggle = $('importErrorsToggle');
  const details = $('importErrors');
  details.innerHTML = errors.map(item => `
    <div class="import-error">
      <strong>${esc(item.file)}</strong>
      <span>${esc(item.error)}</span>
    </div>`).join('');
  details.hidden = true;
  toggle.hidden = errors.length === 0;
  toggle.textContent = 'Ver mais';
  toggle.setAttribute('aria-expanded', 'false');
}

function showNote(text) {
  $('filterNote').textContent = text;
}

function setMessage(text) {
  $('reportMessage').textContent = text;
}

function preparePrintFooter(id, productName) {
  const issuedAt = new Intl.DateTimeFormat('pt-BR', {
    dateStyle: 'short', timeStyle: 'short',
  }).format(new Date());
  $(id).innerHTML = `
    <span class="pdf-footer-date">${esc(issuedAt)}</span>
    <span class="pdf-footer-product">${esc(productName)}</span>
    <span class="pdf-footer-url">${esc(window.location.href)}</span>
    <span class="pdf-footer-page" aria-label="Paginação"></span>`;
  $(id).hidden = false;
}

async function searchUnits(term, scope = 'overview') {
  const res = await fetch(`/api/units?q=${encodeURIComponent(term)}&scope=${scope}`);
  if (!res.ok) return;
  const list = await res.json();
  if (scope === 'overview') unitResults = list;
  $('unitList').innerHTML = list.map(u => `<option value="${esc(u.cnes)}">${esc(u.name)}</option>`).join('');
  if (scope === 'overview') updateSelectedUnitBadge($('unitSearch').value);
}

function updateSelectedUnitBadge(value, name = '') {
  const badge = $('selectedUnitBadge');
  const selected = String(value || '').trim();
  const unit = unitResults.find(item => item.cnes === unitCode(selected))
    || unitResults.find(item => item.name && item.name.toLocaleLowerCase('pt-BR') === selected.toLocaleLowerCase('pt-BR'));
  const unitName = name || unit?.name;
  badge.textContent = unitName || '';
  badge.hidden = !unitName;
}

function setSettingsTab(tab) {
  document.querySelectorAll('.settings-tab').forEach(button => {
    const active = button.dataset.settingsTab === tab;
    button.classList.toggle('active', active);
    button.setAttribute('aria-selected', String(active));
  });
  $('settingsUnits').hidden = tab !== 'units';
  $('settingsDatabase').hidden = tab !== 'database';
}

function renderUnitSettings() {
  ['ambulatory', 'hospital'].forEach(scope => {
    const rows = unitSettings[scope];
    const container = $(`${scope}UnitsRows`);
    container.innerHTML = rows.map((unit, index) => `
      <div class="settings-unit-row">
        <label><span class="settings-input-label">CNES</span><input inputmode="numeric" maxlength="7" data-unit-scope="${scope}" data-unit-index="${index}" data-unit-field="cnes" value="${esc(unit.cnes)}" aria-label="CNES da unidade"></label>
        <label><span class="settings-input-label">Nome da unidade</span><input data-unit-scope="${scope}" data-unit-index="${index}" data-unit-field="name" value="${esc(unit.name)}" aria-label="Nome da unidade"></label>
        <button class="unit-remove-button" type="button" data-remove-unit="${scope}" data-unit-index="${index}" aria-label="Excluir unidade">−</button>
      </div>`).join('');
  });
}

async function loadSettings() {
  if (!unitSettingsLoaded) {
    try {
      const response = await fetch('/api/settings/units');
      const data = await response.json();
      if (!response.ok) throw new Error(errorText(data));
      unitSettings = data;
      renderUnitSettings();
      unitSettingsLoaded = true;
    } catch (error) {
      $('unitSettingsMessage').textContent = `Não foi possível carregar as unidades: ${error.message}`;
    }
  }
  if (!databaseSettingsLoaded) {
    try {
      const response = await fetch('/api/settings/database');
      const data = await response.json();
      if (!response.ok) throw new Error(errorText(data));
      $('activeDatabaseName').textContent = data.name;
      databaseSettingsLoaded = true;
    } catch (error) {
      $('databaseSettingsMessage').textContent = `Não foi possível carregar o banco: ${error.message}`;
    }
  }
}

async function saveUnitSettings() {
  const message = $('unitSettingsMessage');
  message.textContent = 'Salvando…';
  try {
    const response = await fetch('/api/settings/units', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(unitSettings),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(errorText(data));
    message.textContent = data.message;
    await searchUnits('', 'overview');
  } catch (error) {
    message.textContent = `Erro ao salvar: ${error.message}`;
  }
}

async function uploadSelectedDatabase(file) {
  if (!file) return;
  const message = $('databaseSettingsMessage');
  const button = $('chooseDatabaseBtn');
  const form = new FormData();
  form.append('file', file);
  button.disabled = true;
  message.textContent = 'Validando e copiando o banco…';
  try {
    const response = await fetch('/api/settings/database', { method: 'POST', body: form });
    const data = await response.json();
    if (!response.ok) throw new Error(errorText(data));
    $('activeDatabaseName').textContent = data.name;
    message.textContent = data.message;
    databaseSettingsLoaded = true;
  } catch (error) {
    message.textContent = `Erro ao selecionar o banco: ${error.message}`;
  } finally {
    button.disabled = false;
    $('databaseFileInput').value = '';
  }
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

async function fetchGeneralReport({ start, end, compare, exams, procedures }) {
  const params = new URLSearchParams({ start, end, compare, exams, procedures });
  const res = await fetch(`/api/report/general?${params}`);
  const data = await res.json();
  if (!res.ok) throw new Error(errorText(data));
  return data;
}

async function fetchDiverseReport({ cnes, start, end }) {
  const params = new URLSearchParams({ start, end });
  if (cnes) params.set('cnes', cnes);
  const res = await fetch(`/api/report/diverse?${params}`);
  const data = await res.json();
  if (!res.ok) throw new Error(errorText(data));
  return data;
}

async function fetchHospitalReport({ cnes, start, end, compare }) {
  const params = new URLSearchParams({ cnes, start, end, compare });
  const res = await fetch(`/api/hospital/report?${params}`);
  const data = await res.json();
  if (!res.ok) throw new Error(errorText(data));
  return data;
}

function setDashboardLoading(view, loading) {
  const metrics = view === 'overview'
    ? ['mQty', 'mValue', 'mDistinct', 'mSubmitted']
    : ['hAdmissions', 'hValue', 'hDeaths', 'hStay'];
  const chartId = view === 'overview' ? 'chart' : 'hospitalChart';
  metrics.forEach(id => {
    const metric = $(id);
    metric.classList.toggle('is-loading', loading);
    metric.setAttribute('aria-busy', String(loading));
  });
  if (loading) {
    $(chartId).innerHTML = `<div class="chart-loading" role="status" aria-label="Carregando gráfico">
      <span class="chart-loading-label">Carregando gráfico…</span>
      <div class="chart-loading-bars">${Array.from({ length: 9 }, () => '<i></i>').join('')}</div>
    </div>`;
    $(chartId).setAttribute('aria-busy', 'true');
  } else {
    $(chartId).removeAttribute('aria-busy');
  }
}

function revealMetrics(ids) {
  ids.forEach(id => {
    const metric = $(id);
    metric.classList.remove('value-arrive');
    void metric.offsetWidth;
    metric.classList.add('value-arrive');
  });
}

function revealChart(id) {
  const chart = $(id).querySelector('svg');
  if (!chart) return;
  chart.classList.remove('chart-reveal');
  void chart.getBoundingClientRect();
  chart.classList.add('chart-reveal');
}

async function loadHospitalStatus() {
  try {
    const res = await fetch('/api/hospital/status');
    if (!res.ok) return;
    const status = await res.json();
    $('hospitalDataStatus').textContent = status.imported_files
      ? `${fmt(status.imported_files)} arquivos RDSP importados · ${fmt(status.source_records)} registros de origem · ${competenceLabel(status.first_competence)} a ${competenceLabel(status.last_competence)}`
      : `${fmt(status.available_files)} arquivos RDSP disponíveis · importe os DBCs para consultar.`;
    if (status.last_competence && !hospitalPeriodInitialized) {
      const year = status.last_competence.slice(0, 4);
      $('hospitalStart').value = `${year}-01`;
      $('hospitalEnd').value = `${year}-${status.last_competence.slice(4)}`;
      hospitalPeriodInitialized = true;
    }
    if (status.last_competence && !hospitalDocumentPeriodInitialized) {
      const year = status.last_competence.slice(0, 4);
      $('hospitalReportStart').value = `${year}-01`;
      $('hospitalReportEnd').value = `${year}-${status.last_competence.slice(4)}`;
      hospitalDocumentPeriodInitialized = true;
    }
    if (status.import?.running) watchHospitalImport();
  } catch (_) {
    $('hospitalDataStatus').textContent = 'Não foi possível consultar o status dos arquivos RDSP.';
  }
}

async function applyHospitalFilters() {
  const cnes = unitCode($('hospitalUnit').value);
  const start = $('hospitalStart').value;
  const end = $('hospitalEnd').value;
  if (!cnes || !start || !end) {
    $('hospitalMessage').textContent = 'Informe a unidade e o período para consultar a produção hospitalar.';
    return;
  }
  if (start > end) {
    $('hospitalMessage').textContent = 'O mês inicial deve ser igual ou anterior ao mês final.';
    return;
  }
  $('hospitalMessage').textContent = 'Carregando produção hospitalar…';
  setDashboardLoading('hospital', true);
  try {
    hospitalReport = await fetchHospitalReport({ cnes, start, end, compare: $('hospitalCompare').checked });
    hospitalPage = 1;
    $('hospitalMessage').textContent = hospitalReport.summary.admissions
      ? '' : 'Não há internações para esta unidade no período selecionado.';
    renderHospitalReport();
  } catch (err) {
    hospitalReport = null;
    renderHospitalReport();
    $('hospitalMessage').textContent = err.message;
  } finally {
    setDashboardLoading('hospital', false);
    if (hospitalReport) revealMetrics(['hAdmissions', 'hValue', 'hDeaths', 'hStay', 'hAvgValue']);
  }
}

function renderHospitalReport() {
  const report = hospitalReport;
  $('hospitalPrevLegend').hidden = !report?.compare;
  if (!report) {
    $('hAdmissions').textContent = $('hValue').textContent = $('hDeaths').textContent = $('hStay').textContent = $('hAvgValue').textContent = '—';
    $('hAvgValueFoot').textContent = 'Valor total ÷ internações';
    $('hospitalChart').innerHTML = '<div class="empty-state">Selecione uma unidade e um período.</div>';
    $('hospitalSummary').innerHTML = '<div class="empty-state">Os indicadores aparecerão após consultar.</div>';
    $('hospitalBody').innerHTML = '<tr><td colspan="8" class="table-empty">Aguardando consulta.</td></tr>';
    $('hospitalFoot').textContent = 'Aguardando filtros';
    $('hospitalPage').textContent = 'Página 1 de 1';
    $('hospitalPrev').disabled = $('hospitalNext').disabled = true;
    return;
  }
  const summary = report.summary;
  $('hAdmissions').textContent = fmt(summary.admissions);
  $('hAdmissionsFoot').textContent = report.compare
    ? `${signed(summary.difference)} vs. mesmo período do ano anterior`
    : 'AIHs processadas no período';
  $('hValue').textContent = money(summary.value_cents);
  $('hDeaths').textContent = fmt(summary.deaths);
  $('hStay').textContent = `${oneDecimal(summary.average_stay)} dias`;
  $('hAvgValue').textContent = summary.average_value_cents === null ? '—' : money(summary.average_value_cents);
  $('hAvgValueFoot').textContent = report.compare
    ? summary.average_value_percentage === null
      ? 'Sem base comparável no ano anterior'
      : `${pctText(summary.average_value_percentage)} vs. ano anterior`
    : 'Valor total ÷ internações';
  $('hospitalPrevLegend').hidden = !report.compare;
  const chartRows = report.monthly.map(row => ({
    label: row.label, total_qty: row.admissions, prev_total_qty: row.previous_admissions,
  }));
  $('hospitalChart').innerHTML = chartSvg(chartRows, report.compare);
  revealChart('hospitalChart');
  $('hospitalSummary').innerHTML = [
    ['Período', report.period.label],
    ['AIHs no ano anterior', report.compare ? fmt(summary.previous_admissions) : 'Comparação desativada'],
    ['Dias de permanência', fmt(summary.stay_days)],
    ['Mortalidade hospitalar', summary.admissions ? `${(summary.deaths * 100 / summary.admissions).toLocaleString('pt-BR', { maximumFractionDigits: 1 })}%` : '0%'],
    ['Valor médio por AIH', summary.average_value_cents === null ? 'Sem internações no período' : money(summary.average_value_cents)],
    ['Valor médio por AIH no ano anterior', report.compare && summary.previous_average_value_cents !== null ? money(summary.previous_average_value_cents) : report.compare ? 'Sem internações no período anterior' : 'Comparação desativada'],
  ].map(([label, value]) => `<div class="hospital-summary-row"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`).join('');

  const term = $('hospitalSearch').value.trim().toLocaleLowerCase('pt-BR');
  const rows = report.procedure_items.filter(row => !term
    || row.code.toLocaleLowerCase('pt-BR').includes(term)
    || row.name.toLocaleLowerCase('pt-BR').includes(term));
  const pages = Math.max(1, Math.ceil(rows.length / HOSPITAL_PAGE_SIZE));
  hospitalPage = Math.min(hospitalPage, pages);
  const visibleRows = rows.slice((hospitalPage - 1) * HOSPITAL_PAGE_SIZE, hospitalPage * HOSPITAL_PAGE_SIZE);
  $('hospitalBody').innerHTML = visibleRows.length ? visibleRows.map(row => `<tr>
    <td><span class="procedure-name">${esc(row.name || 'Sem descrição cadastrada')}</span><span class="procedure-code">${esc(row.code)}</span></td>
    <td>${fmt(row.admissions)}</td>
    <td>${report.compare ? fmt(row.previous_admissions) : '—'}</td>
    <td>${fmt(row.deaths)}</td>
    <td>${rateText(row.mortality_rate)}</td>
    <td>${fmt(row.stay_days)}</td>
    <td>${row.average_stay === null ? '—' : `${oneDecimal(row.average_stay)} dias`}</td>
    <td>${money(row.value_cents)}</td>
  </tr>`).join('') : '<tr><td colspan="8" class="table-empty">Nenhum procedimento encontrado.</td></tr>';
  $('hospitalFoot').textContent = `${fmt(rows.length)} procedimentos realizados`;
  $('hospitalPage').textContent = `Página ${hospitalPage} de ${pages}`;
  $('hospitalPrev').disabled = hospitalPage <= 1;
  $('hospitalNext').disabled = hospitalPage >= pages;
}

async function startHospitalImport(files) {
  try {
    const body = new FormData();
    [...files].forEach(file => body.append('files', file));
    const res = await fetch('/api/hospital/import', { method: 'POST', body });
    const data = await res.json();
    if (!res.ok) throw new Error(errorText(data));
    watchHospitalImport();
  } catch (err) {
    toast(err.message);
  }
}

function watchHospitalImport() {
  const drawer = $('importDrawer');
  drawer.hidden = false;
  drawer.classList.remove('done');
  showImportErrors([]);
  clearInterval(hospitalImportTimer);
  const tick = async () => {
    const res = await fetch('/api/hospital/import/status');
    if (!res.ok) return;
    const status = await res.json();
    const progress = status.total ? Math.round(status.current * 100 / status.total) : 0;
    if (status.running) {
      $('importTitle').textContent = 'Importando produção hospitalar…';
      $('importText').textContent = `${status.current} de ${status.total}${status.file ? ` · ${status.file}` : ''}`;
      $('importBar').style.width = `${progress}%`;
      return;
    }
    clearInterval(hospitalImportTimer);
    drawer.classList.add('done');
    $('importBar').style.width = '100%';
    if (status.status === 'error') {
      $('importTitle').textContent = 'Falha na importação hospitalar';
      $('importText').textContent = status.message || 'Verifique os arquivos RDSP.';
    } else {
      const result = status.result || {};
      const errors = (result.errors || []).length;
      $('importTitle').textContent = errors ? 'Importação concluída com erros' : 'Importação hospitalar concluída';
      $('importText').textContent = `${fmt(result.imported)} importados · ${fmt(result.skipped)} sem alteração · ${fmt(errors)} com erro`;
      showImportErrors(result.errors || []);
      await loadHospitalStatus();
      if (hospitalReport) await applyHospitalFilters();
      else $('hospitalMessage').textContent = 'Importação concluída. Selecione o período e consulte a produção.';
    }
  };
  tick();
  hospitalImportTimer = setInterval(tick, 1000);
}

async function applyFilters() {
  const cnes = unitCode($('unitSearch').value);
  const start = $('startMonth').value;
  const end = $('endMonth').value;
  if (!cnes || !start || !end) return showNote('Selecione um estabelecimento e um período para visualizar a produção.');
  if (start > end) return showNote('A competência inicial deve ser igual ou anterior à final.');
  showNote('Carregando produção…');
  try {
    setDashboardLoading('overview', true);
    current = await fetchReport({ cnes, start, end, compare: $('compare').checked, exams: true, procedures: true });
    updateSelectedUnitBadge(cnes, current.facility.name);
    page = 1;
    const empty = !current.summary.quantity && !current.exam_items.length && !current.procedure_items.length;
    showNote(empty ? 'Não há produção aprovada para esta unidade no período selecionado.' : '');
    renderOverview();
  } catch (err) {
    current = null;
    updateSelectedUnitBadge('');
    renderOverview();
    showNote(err.message);
  } finally {
    setDashboardLoading('overview', false);
    if (current) revealMetrics(['mQty', 'mValue', 'mDistinct', 'mSubmitted', 'mQtyApproval', 'mValueApproval']);
  }
}

function renderOverview() {
  const d = current;
  if (!d) {
    ['mQty', 'mValue', 'mDistinct', 'mSubmitted'].forEach(id => { $(id).textContent = '—'; });
    $('mQtyApproval').textContent = $('mValueApproval').textContent = '—';
    $('mQtyFoot').textContent = 'vs. mesmo período anterior';
    $('mQtyApprovalFoot').textContent = 'Quantidade aprovada ÷ apresentada';
    $('mValueApprovalFoot').textContent = 'Valor aprovado ÷ apresentado';
    $('prevLegend').hidden = true;
    $('qtyApprovalPrevLegend').hidden = $('valueApprovalPrevLegend').hidden = true;
    $('chart').innerHTML = '<div class="empty-state">Selecione uma unidade para carregar o gráfico.</div>';
    $('qtyApprovalChart').innerHTML = $('valueApprovalChart').innerHTML = '<div class="empty-state">Selecione uma unidade para ver a evolução.</div>';
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
  $('mQtyApproval').textContent = rateText(s.quantity_approval_rate);
  $('mQtyApprovalFoot').textContent = rateChangeText(
    s.quantity_approval_rate, s.previous_quantity_approval_rate, d.compare,
  );
  $('mValueApproval').textContent = rateText(s.value_approval_rate);
  $('mValueApprovalFoot').textContent = rateChangeText(
    s.value_approval_rate, s.previous_value_approval_rate, d.compare,
  );
  $('prevLegend').hidden = !d.compare;
  $('qtyApprovalPrevLegend').hidden = $('valueApprovalPrevLegend').hidden = !d.compare;
  $('chart').innerHTML = chartSvg(d.monthly, d.compare);
  $('qtyApprovalChart').innerHTML = approvalChartSvg(
    d.monthly, 'quantity_approval_rate', 'previous_quantity_approval_rate', d.compare,
  );
  $('valueApprovalChart').innerHTML = approvalChartSvg(
    d.monthly, 'value_approval_rate', 'previous_value_approval_rate', d.compare,
  );
  revealChart('chart');
  revealChart('qtyApprovalChart');
  revealChart('valueApprovalChart');
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
    return `<line class="chart-grid" x1="${L}" x2="${W - R}" y1="${yy}" y2="${yy}"/><text class="chart-axis chart-axis-value" x="${L - 8}" y="${yy}" text-anchor="end" dominant-baseline="middle">${fmt(Math.round(v))}</text>`;
  }).join('');
  const step = Math.ceil(rows.length / 12);
  const xLabels = rows.map((r, i) => i % step === 0 ? `<text class="chart-axis" x="${x(i).toFixed(1)}" y="${H - 8}" text-anchor="middle">${esc(r.label)}</text>` : '').join('');
  const points = rows.map((r, i) => `<circle class="chart-point" cx="${x(i).toFixed(1)}" cy="${y(r.total_qty).toFixed(1)}" r="3.5"/>`).join('');
  const valueStep = Math.max(1, Math.ceil((rows.length - 1) / 11));
  const values = rows.map((r, i) => i % valueStep === 0 || i === rows.length - 1
    ? `<text class="chart-label" x="${x(i).toFixed(1)}" y="${(y(r.total_qty) - 12).toFixed(1)}">${fmt(r.total_qty)}</text>`
    : '').join('');
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

function approvalChartSvg(rows, currentKey, previousKey, compare) {
  const W = 760, H = 230, L = 52, R = 16, T = 16, B = 30;
  const iw = W - L - R, ih = H - T - B;
  const values = rows.flatMap(row => [row[currentKey], ...(compare ? [row[previousKey]] : [])])
    .filter(value => value !== null && value !== undefined);
  if (!values.length) return '<div class="empty-state">Sem dados apresentados para calcular a taxa.</div>';
  const max = Math.max(100, Math.ceil(Math.max(0, ...values) / 25) * 25);
  const x = i => rows.length === 1 ? L + iw / 2 : L + i * iw / (rows.length - 1);
  const y = value => T + ih - (value / max) * ih;
  const path = key => rows
    .map((row, i) => row[key] === null || row[key] === undefined
      ? null : `${i ? 'L' : 'M'}${x(i).toFixed(1)} ${y(row[key]).toFixed(1)}`)
    .filter(Boolean).join(' ');
  const grid = [0, 1, 2, 3, 4].map(step => {
    const value = max * step / 4;
    const yy = y(value).toFixed(1);
    return `<line class="chart-grid" x1="${L}" x2="${W - R}" y1="${yy}" y2="${yy}"/><text class="chart-axis chart-axis-value" x="${L - 8}" y="${yy}" text-anchor="end" dominant-baseline="middle">${Math.round(value)}%</text>`;
  }).join('');
  const step = Math.ceil(rows.length / 12);
  const labels = rows.map((row, i) => i % step === 0
    ? `<text class="chart-axis" x="${x(i).toFixed(1)}" y="${H - 8}" text-anchor="middle">${esc(row.label)}</text>` : '').join('');
  const points = key => rows.map((row, i) => row[key] === null || row[key] === undefined ? ''
    : `<circle class="${key === currentKey ? 'chart-point' : 'chart-point-previous'}" cx="${x(i).toFixed(1)}" cy="${y(row[key]).toFixed(1)}" r="3.5"/>`).join('');
  const pointLabels = (key, isCurrent) => rows.map((row, i) => {
    const value = row[key];
    if (value === null || value === undefined) return '';
    const pointY = y(value);
    const labelY = isCurrent
      ? pointY > T + 14 ? pointY - 8 : pointY + 18
      : pointY < H - B - 16 ? pointY + 15 : pointY - 8;
    const label = Number(value).toLocaleString('pt-BR', {
      minimumFractionDigits: 1, maximumFractionDigits: 1,
    });
    return `<text class="chart-axis-value chart-rate-label ${isCurrent ? 'chart-rate-current' : 'chart-rate-previous'}" x="${x(i).toFixed(1)}" y="${labelY.toFixed(1)}" text-anchor="middle">${label}%</text>`;
  }).join('');
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Evolução mensal da taxa de aprovação">
    ${grid}${compare ? `<path class="chart-previous-line" d="${path(previousKey)}"/>${points(previousKey)}${pointLabels(previousKey, false)}` : ''}
    <path class="chart-current-line" d="${path(currentKey)}"/>${points(currentKey)}${pointLabels(currentKey, true)}${labels}
  </svg>`;
}

function watchImport() {
  const drawer = $('importDrawer');
  drawer.hidden = false;
  drawer.classList.remove('done');
  showImportErrors([]);
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
      showImportErrors(r.errors || []);
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

async function generateGeneralReport() {
  const start = $('generalStart').value;
  const end = $('generalEnd').value;
  const exams = $('generalExams').checked;
  const procedures = $('generalProcedures').checked;
  if (!start || !end) return setMessage('Escolha o mês inicial e o mês final do relatório geral.');
  if (start > end) return setMessage('O mês inicial deve ser igual ou anterior ao mês final.');
  if (!exams && !procedures) {
    $('reportView').hidden = true;
    $('reportToolbar').hidden = true;
    return setMessage('Marque exames, procedimentos ou ambos.');
  }
  setMessage('Gerando relatório geral…');
  try {
    const data = await fetchGeneralReport({
      start,
      end,
      compare: $('generalCompare').checked,
      exams,
      procedures,
    });
    renderGeneralReport(data);
    setMessage('');
  } catch (err) {
    $('reportView').hidden = true;
    $('reportToolbar').hidden = true;
    setMessage(err.message);
  }
}

async function generateDiverseReport() {
  const selectedUnit = $('diverseUnit').value.trim();
  const matchedUnit = unitResults.find(item =>
    item.name.toLocaleLowerCase('pt-BR') === selectedUnit.toLocaleLowerCase('pt-BR'),
  );
  const cnes = unitCode(selectedUnit) || matchedUnit?.cnes || '';
  const start = $('diverseStart').value;
  const end = $('diverseEnd').value;
  if (selectedUnit && !cnes) return setDiverseMessage('Informe um CNES de 7 dígitos ou escolha uma unidade na lista.');
  if (!start || !end) return setDiverseMessage('Escolha o mês inicial e o mês final.');
  if (start > end) return setDiverseMessage('O mês inicial deve ser igual ou anterior ao mês final.');

  setDiverseMessage('Gerando relatório…');
  try {
    const data = await fetchDiverseReport({ cnes, start, end });
    renderDiverseReport(data);
    setDiverseMessage('');
  } catch (error) {
    $('diverseReportView').hidden = true;
    $('diverseReportToolbar').hidden = true;
    setDiverseMessage(error.message);
  }
}

function setDiverseMessage(text) {
  $('diverseMessage').textContent = text;
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
  $('reportView').dataset.reportType = 'unit';
  const monthRows = d.monthly.map(r => `<tr>
    <td>${esc(r.label)}</td><td>${fmt(r.total_qty)}</td><td>${rateText(r.quantity_approval_rate)}</td>
    <td>${money(r.value_cents)}</td><td>${rateText(r.value_approval_rate)}</td>
    ${compare ? `<td>${rateText(r.previous_quantity_approval_rate)}</td><td>${rateDeltaText(r.quantity_approval_rate_change)}</td>
      <td>${rateText(r.previous_value_approval_rate)}</td><td>${rateDeltaText(r.value_approval_rate_change)}</td>` : ''}
  </tr>`).join('');
  const totalRow = `<tr class="rep-total-row">
    <th>Total / período</th><th>${fmt(s.quantity)}</th><th>${rateText(s.quantity_approval_rate)}</th>
    <th>${money(s.value_cents)}</th><th>${rateText(s.value_approval_rate)}</th>
    ${compare ? `<th>${rateText(s.previous_quantity_approval_rate)}</th><th>${rateDeltaText(s.quantity_approval_rate_change)}</th>
      <th>${rateText(s.previous_value_approval_rate)}</th><th>${rateDeltaText(s.value_approval_rate_change)}</th>` : ''}
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
      <p>As taxas são calculadas como quantidade aprovada ÷ apresentada e valor aprovado ÷ apresentado. A comparação anual mostra a diferença entre as taxas em pontos percentuais.</p>
      <div class="table-scroll"><table class="rep-table hospital-report-summary-table">
        <thead><tr><th>Mês</th><th>Quantidade aprovada</th><th>Taxa de aprovação da quantidade</th><th>Valor aprovado</th><th>Taxa de aprovação do valor</th>
          ${compare ? '<th>Taxa quantidade · ano anterior</th><th>Variação (p.p.)</th><th>Taxa valor · ano anterior</th><th>Variação (p.p.)</th>' : ''}</tr></thead>
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

function generalValueCell(currentValue, previousValue, difference, percentage, compare) {
  if (!compare) return `<td>${fmt(currentValue)}</td>`;
  return `<td class="general-report-value">
    <strong>${fmt(currentValue)}</strong>
    <small>Ano anterior: ${fmt(previousValue)}</small>
    <small class="${tone(difference)}">Variação: ${signed(difference)} (${pctText(percentage)})</small>
  </td>`;
}

function renderGeneralReport(data) {
  const { compare, period, rows, summary, exams, procedures } = data;
  $('reportView').dataset.reportType = 'general';
  const examHeader = exams ? '<th>Exames</th>' : '';
  const procedureHeader = procedures ? '<th>Procedimentos</th>' : '';
  const reportRows = rows.map(row => `<tr>
    <td>${esc(row.cnes)}</td>
    <td>${esc(row.name || 'Unidade sem nome cadastrado')}</td>
    ${exams ? generalValueCell(row.exams, row.previous_exams, row.exams_difference, row.exams_percentage, compare) : ''}
    ${procedures ? generalValueCell(row.procedures, row.previous_procedures, row.procedures_difference, row.procedures_percentage, compare) : ''}
    ${generalValueCell(row.total, row.previous_total, row.total_difference, row.total_percentage, compare)}
  </tr>`).join('');
  const columnCount = 3 + Number(exams) + Number(procedures);
  const emptyRow = `<tr><td colspan="${columnCount}">Não há produção aprovada para o período selecionado.</td></tr>`;
  const totalRow = `<tr class="rep-total-row">
    <th colspan="2">Total geral</th>
    ${exams ? generalValueCell(summary.exams, summary.previous_exams, summary.exams_difference, summary.exams_percentage, compare) : ''}
    ${procedures ? generalValueCell(summary.procedures, summary.previous_procedures, summary.procedures_difference, summary.procedures_percentage, compare) : ''}
    ${generalValueCell(summary.total, summary.previous_total, summary.total_difference, summary.total_percentage, compare)}
  </tr>`;
  const categories = [exams && 'exames', procedures && 'procedimentos'].filter(Boolean).join(' e ');
  $('reportContent').innerHTML = `
    <header class="rep-header">
      <img src="/img/brasao.png" alt="Brasão">
      <div class="rep-org">
        <div class="rep-org-main">PREFEITURA MUNICIPAL DE TAUBATÉ</div>
        <div class="rep-org-sub">SECRETARIA DE SAÚDE</div>
      </div>
    </header>
    <div class="rep-title-block">
      <div class="rep-title">Relatório Geral de Produção Ambulatorial</div>
      <div class="rep-sub">Todas as unidades · ${esc(period.label)}</div>
    </div>
    <section class="rep-section general-report-section">
      <h3>Produção por unidade</h3>
      <p>Quantidades aprovadas de ${categories} no período.${compare ? ' A comparação considera o mesmo período do ano anterior.' : ''}</p>
      ${compare ? '<p class="general-report-legend">Cada célula mostra: período selecionado, ano anterior e variação percentual.</p>' : ''}
      <div class="table-scroll"><table class="rep-table general-report-table">
        <thead><tr><th>CNES</th><th>Unidade</th>${examHeader}${procedureHeader}<th>Total</th></tr></thead>
        <tbody>${reportRows || emptyRow}${reportRows ? totalRow : ''}</tbody>
      </table></div>
    </section>
  `;
  $('reportView').hidden = false;
  $('reportToolbar').hidden = false;
}

function diverseDimensionTable(title, dimension) {
  const rows = dimension.items.map(item => `<tr>
    <td>${esc(item.label)}</td>
    <td>${fmt(item.quantity)}</td>
    <td>${rateText(item.percentage)}</td>
  </tr>`).join('');
  const emptyRow = '<tr><td colspan="3" class="table-empty">Sem produção aprovada para esta categoria no período.</td></tr>';
  const limitNote = dimension.truncated
    ? '<p>Exibidos os 100 códigos mais frequentes.</p>' : '';
  return `<section class="rep-section diverse-report-section">
    <h3>${esc(title)}</h3>
    <div class="table-scroll"><table class="rep-table">
      <thead><tr><th>Categoria</th><th>Quantidade aprovada</th><th>Participação</th></tr></thead>
      <tbody>${rows || emptyRow}</tbody>
    </table></div>
    ${limitNote}
  </section>`;
}

function renderDiverseReport(data) {
  const unitLabel = data.unit.cnes
    ? `${esc(data.unit.name || 'Unidade sem nome cadastrado')} · CNES ${esc(data.unit.cnes)}`
    : 'Todas as unidades';
  const reimportWarning = data.pending_reimport_files
    ? `<p><b>Atenção:</b> ${fmt(data.pending_reimport_files)} arquivo(s) importado(s) precisam ser reprocessados. Use “Importar DBCs” na tela de produção ambulatorial para completar este relatório.</p>`
    : '';
  const noData = data.total_approved_quantity === 0
    ? '<p>Não há produção aprovada no período selecionado.</p>'
    : '';
  $('diverseReportContent').innerHTML = `
    <header class="rep-header">
      <img src="/img/brasao.png" alt="Brasão">
      <div class="rep-org">
        <div class="rep-org-main">PREFEITURA MUNICIPAL DE TAUBATÉ</div>
        <div class="rep-org-sub">SECRETARIA DE SAÚDE</div>
      </div>
    </header>
    <div class="rep-title-block">
      <div class="rep-title">Relatório de Perfil da Produção Ambulatorial</div>
      <div class="rep-sub">${unitLabel} · ${esc(data.period.label)}</div>
    </div>
    <section class="rep-section">
      <h3>Apresentação e escopo</h3>
      <p>Distribuição da quantidade aprovada de procedimentos no período, agrupada pelos campos disponíveis nos arquivos PA do SIA/SUS. As quantidades não representam pessoas únicas.</p>
      <p>Total aprovado: <b>${fmt(data.total_approved_quantity)}</b> · Unidades: <b>${fmt(data.units)}</b></p>
      ${reimportWarning}
      ${noData}
    </section>
    ${diverseDimensionTable('Idade informada (PA_IDADE)', data.dimensions.age)}
    ${diverseDimensionTable('Sexo (PA_SEXO)', data.dimensions.sex)}
    ${diverseDimensionTable('Raça/cor (PA_RACACOR)', data.dimensions.race)}
    ${diverseDimensionTable('CID principal (PA_CIDPRI)', data.dimensions.cid_primary)}
    ${diverseDimensionTable('CID secundário (PA_CIDSEC)', data.dimensions.cid_secondary)}
    ${diverseDimensionTable('CID associado (PA_CIDCAS)', data.dimensions.cid_associated)}
    <section class="rep-section">
      <p>Idade e códigos CID são exibidos conforme registrados; consulte o dicionário do SIA/SUS para interpretar códigos e unidades. Percentuais usam a quantidade aprovada de cada dimensão como base.</p>
    </section>
  `;
  $('diverseReportView').hidden = false;
  $('diverseReportToolbar').hidden = false;
}

async function generateHospitalReport() {
  const cnes = unitCode($('hospitalReportUnit').value);
  const start = $('hospitalReportStart').value;
  const end = $('hospitalReportEnd').value;
  if (!cnes) return setHospitalReportMessage('Informe o CNES da unidade (7 números).');
  if (!start || !end) return setHospitalReportMessage('Escolha o mês inicial e o mês final.');
  if (start > end) return setHospitalReportMessage('O mês inicial deve ser igual ou anterior ao mês final.');
  setHospitalReportMessage('Gerando relatório hospitalar…');
  $('hospitalReportToolbar').hidden = true;
  try {
    hospitalReportDocument = await fetchHospitalReport({
      cnes, start, end, compare: $('hospitalReportCompare').checked,
    });
    renderHospitalDocument(hospitalReportDocument);
    setHospitalReportMessage('');
  } catch (err) {
    hospitalReportDocument = null;
    $('hospitalReportView').hidden = true;
    setHospitalReportMessage(err.message);
  }
}

function setHospitalReportMessage(message) {
  $('hospitalReportMessage').textContent = message;
}

function renderHospitalDocument(data) {
  const compare = data.compare;
  const summary = data.summary;
  const unitName = data.facility.name || 'Unidade sem nome cadastrado';
  const monthlyRows = data.monthly.map(row => `<tr>
    <td>${esc(row.label)}</td><td>${fmt(row.admissions)}</td>
    ${compare ? `<td>${fmt(row.previous_admissions)}</td><td class="${tone(row.difference)}">${signed(row.difference)} (${pctText(row.percentage)})</td>` : ''}
  </tr>`).join('');
  const monthlyTotal = `<tr class="rep-total-row">
    <th>Total</th><th>${fmt(summary.admissions)}</th>
    ${compare ? `<th>${fmt(summary.previous_admissions)}</th><th class="${tone(summary.difference)}">${signed(summary.difference)} (${pctText(summary.percentage)})</th>` : ''}
  </tr>`;
  const procedureRows = data.procedure_items.map(row => `<tr>
    <td><span class="procedure-name">${esc(row.name || 'Sem descrição cadastrada')}</span><span class="procedure-code">${esc(row.code)}</span></td>
    <td>${fmt(row.admissions)}</td>
    ${compare ? `<td>${fmt(row.previous_admissions)}</td><td class="${tone(row.difference)}">${signed(row.difference)} (${pctText(row.percentage)})</td>` : ''}
    <td>${fmt(row.deaths)}</td><td>${rateText(row.mortality_rate)}</td>
    <td>${fmt(row.stay_days)}</td><td>${row.average_stay === null ? '—' : `${oneDecimal(row.average_stay)} dias`}</td>
    <td>${money(row.value_cents)}</td>
  </tr>`).join('');
  const chartRows = data.monthly.map(row => ({
    label: row.label, total_qty: row.admissions, prev_total_qty: row.previous_admissions,
  }));
  const empty = summary.admissions === 0
    ? '<p>Não há internações para esta unidade no período selecionado.</p>' : '';

  $('hospitalReportContent').innerHTML = `
    <header class="rep-header">
      <img src="/img/brasao.png" alt="Brasão">
      <div class="rep-org">
        <div class="rep-org-main">PREFEITURA MUNICIPAL DE TAUBATÉ</div>
        <div class="rep-org-sub">SECRETARIA DE SAÚDE</div>
      </div>
    </header>
    <div class="rep-title-block">
      <div class="rep-title">Relatório de Produção Hospitalar</div>
      <div class="rep-sub">${esc(unitName)} · CNES ${esc(data.facility.cnes)}</div>
      <div class="rep-sub">SIH/SUS · ${esc(data.period.label)}</div>
    </div>
    <section class="rep-section">
      <h3>Apresentação e Escopo do Relatório</h3>
      <p>Este relatório apresenta dados agregados da produção hospitalar da unidade <b>${esc(unitName)}</b>, no período de <b>${esc(data.period.label)}</b>, a partir dos arquivos reduzidos do SIH/SUS importados pelo painel.${compare ? ' A comparação considera o mesmo período do ano anterior.' : ''}</p>
      ${empty}
    </section>
    <section class="rep-section">
      <h3>Resumo da Produção Hospitalar</h3>
      <div class="table-scroll"><table class="rep-table">
        <tbody>
          <tr><th>Internações</th><td>${fmt(summary.admissions)}</td>${compare ? `<th>Internações no ano anterior</th><td>${fmt(summary.previous_admissions)}</td>` : ''}</tr>
          <tr><th>Valor total</th><td>${money(summary.value_cents)}</td>${compare ? `<th>Variação de internações</th><td class="${tone(summary.difference)}">${signed(summary.difference)} (${pctText(summary.percentage)})</td>` : ''}</tr>
          <tr><th>Valor médio por AIH</th><td>${summary.average_value_cents === null ? '—' : money(summary.average_value_cents)}</td>${compare ? `<th>Valor médio no ano anterior</th><td>${summary.previous_average_value_cents === null ? '—' : `${money(summary.previous_average_value_cents)}${summary.average_value_percentage === null ? '' : ` · ${pctText(summary.average_value_percentage)}`}`}</td>` : ''}</tr>
          <tr><th>Óbitos</th><td>${fmt(summary.deaths)}</td><th>Permanência média</th><td>${summary.average_stay.toLocaleString('pt-BR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })} dias</td></tr>
          <tr><th>Dias de permanência</th><td>${fmt(summary.stay_days)}</td><th>Mortalidade hospitalar</th><td>${summary.admissions ? `${(summary.deaths * 100 / summary.admissions).toLocaleString('pt-BR', { maximumFractionDigits: 1 })}%` : '0%'}</td></tr>
        </tbody>
      </table></div>
    </section>
    <section class="rep-section">
      <h3>Evolução Mensal das Internações</h3>
      <div class="table-scroll"><table class="rep-table hospital-report-month-table">
        <thead><tr><th>Mês</th><th>Internações</th>${compare ? '<th>Ano anterior</th><th>Variação</th>' : ''}</tr></thead>
        <tbody>${monthlyRows}${monthlyTotal}</tbody>
      </table></div>
    </section>
    <section class="rep-section">
      <h3>Gráfico de Evolução</h3>
      <div class="chart-legend">
        <span><i class="legend-dot current-dot"></i>Período selecionado</span>
        ${compare ? '<span><i class="legend-dot previous-dot"></i>Ano anterior</span>' : ''}
      </div>
      <div class="chart-area rep-chart">${chartSvg(chartRows, compare)}</div>
    </section>
    <section class="rep-section hospital-procedure-report">
      <h3>Detalhamento dos Procedimentos Hospitalares</h3>
      <p>Foram identificados <b>${fmt(data.procedure_items.length)}</b> procedimentos realizados no período. Mortalidade é calculada como óbitos ÷ internações; permanência média, como dias de permanência ÷ internações. Os valores correspondem à soma de VAL_TOT nos arquivos RDSP.</p>
      <div class="table-scroll"><table class="rep-table hospital-report-proc-table">
        <thead><tr><th>Procedimento</th><th>Internações</th>${compare ? '<th>Ano anterior</th><th>Variação</th>' : ''}<th>Óbitos</th><th>Mortalidade</th><th>Dias de permanência</th><th>Permanência média</th><th>Valor total</th></tr></thead>
        <tbody>${procedureRows || `<tr><td colspan="${compare ? 9 : 7}" class="table-empty">Nenhum procedimento encontrado.</td></tr>`}</tbody>
      </table></div>
    </section>
  `;
  $('hospitalReportView').hidden = false;
  $('hospitalReportToolbar').hidden = false;
}

document.addEventListener('DOMContentLoaded', async () => {
  const toolbar = document.createElement('div');
  toolbar.id = 'reportToolbar';
  toolbar.className = 'report-toolbar';
  toolbar.hidden = true;
  toolbar.innerHTML = '<button id="pdfBtn" class="button button-primary" type="button">Exportar PDF</button>';
  $('reportView').before(toolbar);
  $('pdfBtn').addEventListener('click', () => {
    documentTitleBeforePrint = document.title;
    const reportTitle = $('reportView').dataset.reportType === 'general'
      ? 'Relatório Geral Ambulatorial · PainelSUS'
      : 'Produção PA · PainelSUS';
    document.title = reportTitle;
    preparePrintFooter('reportPrintFooter', reportTitle);
    window.print();
  });
  $('hospitalReportPdf').addEventListener('click', () => {
    documentTitleBeforePrint = document.title;
    document.title = 'Produção Hospitalar : PainelSUS';
    preparePrintFooter('hospitalReportPrintFooter', 'Produção Hospitalar : PainelSUS');
    document.body.classList.add('print-hospital-report');
    window.print();
  });
  $('diversePdfBtn').addEventListener('click', () => {
    documentTitleBeforePrint = document.title;
    document.title = 'Relatório Diversos · PainelSUS';
    preparePrintFooter('diverseReportPrintFooter', 'Relatório Diversos · PainelSUS');
    document.body.classList.add('print-diverse-report');
    window.print();
  });
  window.addEventListener('afterprint', () => {
    document.body.classList.remove('print-hospital-report');
    document.body.classList.remove('print-diverse-report');
    if (documentTitleBeforePrint !== null) {
      document.title = documentTitleBeforePrint;
      documentTitleBeforePrint = null;
    }
    $('reportPrintFooter').hidden = true;
    $('hospitalReportPrintFooter').hidden = true;
    $('diverseReportPrintFooter').hidden = true;
  });

  const now = new Date();
  const ym = (y, m) => `${y}-${String(m).padStart(2, '0')}`;
  const startValue = ym(now.getFullYear(), 1);
  const endValue = ym(now.getFullYear(), now.getMonth() + 1);
  $('startMonth').value = startValue;
  $('endMonth').value = endValue;
  $('repStart').value = startValue;
  $('repEnd').value = endValue;
  $('generalStart').value = startValue;
  $('generalEnd').value = endValue;
  $('diverseStart').value = startValue;
  $('diverseEnd').value = endValue;
  $('hospitalUnit').value = '2749319';
  $('hospitalStart').value = startValue;
  $('hospitalEnd').value = endValue;
  $('hospitalReportUnit').value = '2749319';
  $('hospitalReportStart').value = startValue;
  $('hospitalReportEnd').value = endValue;

  document.querySelectorAll('.settings-tab').forEach(button => {
    button.addEventListener('click', () => setSettingsTab(button.dataset.settingsTab));
  });
  document.querySelectorAll('[data-add-unit]').forEach(button => {
    button.addEventListener('click', () => {
      unitSettings[button.dataset.addUnit].push({ cnes: '', name: '' });
      renderUnitSettings();
      const inputs = document.querySelectorAll(
        `[data-unit-scope="${button.dataset.addUnit}"][data-unit-field="cnes"]`,
      );
      inputs[inputs.length - 1]?.focus();
    });
  });
  $('settingsUnits').addEventListener('input', event => {
    const input = event.target;
    if (!input.matches('[data-unit-field]')) return;
    const scope = input.dataset.unitScope;
    const index = Number(input.dataset.unitIndex);
    unitSettings[scope][index][input.dataset.unitField] = input.value;
  });
  $('settingsUnits').addEventListener('click', event => {
    const button = event.target.closest('[data-remove-unit]');
    if (!button) return;
    unitSettings[button.dataset.removeUnit].splice(Number(button.dataset.unitIndex), 1);
    renderUnitSettings();
  });
  $('saveUnitSettings').addEventListener('click', saveUnitSettings);
  $('chooseDatabaseBtn').addEventListener('click', () => $('databaseFileInput').click());
  $('databaseFileInput').addEventListener('change', event => {
    uploadSelectedDatabase(event.target.files[0]);
  });

  $('applyFilters').addEventListener('click', applyFilters);
  $('refreshBtn').addEventListener('click', () => { loadStatus(); applyFilters(); });
  $('importBtn').addEventListener('click', () => $('dbcInput').click());
  $('dbcInput').addEventListener('change', e => uploadDbcs(e.target.files));
  $('importClose').addEventListener('click', () => { $('importDrawer').hidden = true; });
  $('importErrorsToggle').addEventListener('click', () => {
    const details = $('importErrors');
    details.hidden = !details.hidden;
    $('importErrorsToggle').textContent = details.hidden ? 'Ver mais' : 'Ver menos';
    $('importErrorsToggle').setAttribute('aria-expanded', String(!details.hidden));
  });
  $('exportBtn').addEventListener('click', exportReport);
  $('generateDiverseReport').addEventListener('click', generateDiverseReport);
  $('generateHospitalReport').addEventListener('click', generateHospitalReport);
  $('hospitalReportCompare').addEventListener('change', () => {
    if (hospitalReportDocument) generateHospitalReport();
  });
  $('hospitalApply').addEventListener('click', applyHospitalFilters);
  $('hospitalImportBtn').addEventListener('click', () => $('hospitalFileInput').click());
  $('hospitalFileInput').addEventListener('change', event => {
    const files = event.target.files;
    if (files.length) startHospitalImport(files);
    event.target.value = '';
  });
  $('hospitalRefresh').addEventListener('click', loadHospitalStatus);
  $('hospitalSearch').addEventListener('input', () => { hospitalPage = 1; renderHospitalReport(); });
  $('hospitalPrev').addEventListener('click', () => { hospitalPage -= 1; renderHospitalReport(); });
  $('hospitalNext').addEventListener('click', () => { hospitalPage += 1; renderHospitalReport(); });

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
  $('generateGeneralReport').addEventListener('click', generateGeneralReport);
  $('generalCompare').addEventListener('change', () => {
    if (!$('reportView').hidden && $('reportView').dataset.reportType === 'general') {
      generateGeneralReport();
    }
  });
  ['generalExams', 'generalProcedures'].forEach(id => {
    $(id).addEventListener('change', () => {
      if (!$('reportView').hidden && $('reportView').dataset.reportType === 'general') {
        generateGeneralReport();
      }
    });
  });
  ['repCompare', 'repExams', 'repProcs'].forEach(id => {
    $(id).addEventListener('change', () => { if (!$('reportView').hidden) generateReport(); });
  });

  ['repUnit', 'unitSearch', 'diverseUnit', 'hospitalUnit', 'hospitalReportUnit'].forEach(id => {
    $(id).addEventListener('input', e => {
      clearTimeout(unitTimer);
      const scope = id === 'hospitalUnit' || id === 'hospitalReportUnit' ? 'hospital' : 'overview';
      unitTimer = setTimeout(() => searchUnits(e.target.value, scope), 250);
    });
  });
  $('unitSearch').addEventListener('input', () => updateSelectedUnitBadge(''));

  searchUnits('');
  const s = await loadStatus().catch(() => null);
  if (s && s.import && s.import.running) watchImport();
  renderOverview();
  renderHospitalReport();
});
