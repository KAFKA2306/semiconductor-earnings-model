(() => {
  'use strict';

  const configElement = document.querySelector('#research-context-config');
  if (!configElement) return;

  const config = JSON.parse(configElement.textContent || '{}');
  const companies = Array.isArray(config.companies) ? config.companies : [];
  const periods = Array.isArray(config.periods) ? config.periods : [];
  const peers = Array.isArray(config.peers) ? config.peers : [];
  const page = config.page || 'earnings';
  const base = config.base || '../';
  const maxCompare = 5;
  let lastDialogTrigger = null;

  const valueTypes = {
    actual: { label: '実績', description: '規制開示または会社一次資料で報告された値。' },
    guidance: { label: '会社予想', description: '会社が示した将来レンジまたは見通し。実績ではありません。' },
    consensus: { label: 'コンセンサス', description: '外部予想の集計値。会社予想・独自推計とは別系列です。' },
    market: { label: '市場観測', description: '株価、時価総額、金利など観測時点を持つ市場値。' },
    estimate: { label: '独自推計', description: '入力・式・版を持つモデル値。報告実績ではありません。' },
    scenario: { label: 'シナリオ', description: '明示した仮定に基づく条件付きの試算。' },
  };
  const pageLabels = {
    earnings: '一次事実台帳',
    resilience: '財務耐久力比較',
    model: '計算モデル',
  };
  const pagePaths = {
    earnings: `${base}earnings/`,
    resilience: `${base}resilience/`,
    model: `${base}model/`,
  };
  const pageEvidence = config.evidence || {};

  const escapeHtml = (value = '') => String(value).replace(/[&<>'"]/g, character => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
  })[character]);
  const companyById = id => companies.find(company => company.id === id || company.ticker === id);
  const unique = values => [...new Set(values.filter(Boolean))];

  function readState() {
    const params = new URLSearchParams(location.search);
    const company = params.get('company') || '';
    const compare = unique((params.get('compare') || '').split(',')).filter(id => companyById(id)).slice(0, maxCompare);
    return {
      company: companyById(company)?.id || '',
      peer: peers.some(item => item.id === params.get('peer')) ? params.get('peer') : 'all',
      period: periods.includes(params.get('period')) ? params.get('period') : '',
      valueType: valueTypes[params.get('valueType')] ? params.get('valueType') : 'actual',
      compare,
      focus: params.get('focus') === '1',
      evidence: params.get('evidence') === '1',
    };
  }

  let state = readState();

  function writeState({ push = false } = {}) {
    const params = new URLSearchParams();
    if (state.company) params.set('company', state.company);
    if (state.peer !== 'all') params.set('peer', state.peer);
    if (state.period) params.set('period', state.period);
    if (state.valueType !== 'actual') params.set('valueType', state.valueType);
    if (state.compare.length) params.set('compare', state.compare.join(','));
    if (state.focus) params.set('focus', '1');
    if (state.evidence) params.set('evidence', '1');
    const target = `${location.pathname}${params.size ? `?${params}` : ''}${location.hash}`;
    history[push ? 'pushState' : 'replaceState'](state, '', target);
    updateCrossLinks(params);
  }

  function optionMarkup(items, selected, emptyLabel, value = item => item.id, label = item => item.label) {
    return `<option value="">${escapeHtml(emptyLabel)}</option>${items.map(item => {
      const itemValue = value(item);
      return `<option value="${escapeHtml(itemValue)}" ${itemValue === selected ? 'selected' : ''}>${escapeHtml(label(item))}</option>`;
    }).join('')}`;
  }

  function contextShell() {
    const shell = document.createElement('section');
    shell.className = 'research-context-shell';
    shell.id = 'research-context';
    shell.dataset.expanded = 'false';
    shell.setAttribute('aria-label', '研究コンテキスト');
    shell.innerHTML = `
      <div class="research-context-inner">
        <div class="research-context-topline">
          <div><span class="research-context-brand">Research Context</span> <span class="research-context-page">${escapeHtml(pageLabels[page] || page)}</span></div>
          <button type="button" class="research-mobile-toggle" aria-expanded="false" aria-controls="research-context-controls">対象と期間</button>
          <nav class="research-context-links" aria-label="研究画面">
            ${Object.entries(pagePaths).map(([id, href]) => `<a data-context-link="${id}" href="${escapeHtml(href)}" ${id === page ? 'aria-current="page"' : ''}>${escapeHtml(pageLabels[id])}</a>`).join('')}
          </nav>
        </div>
        <div class="research-context-controls" id="research-context-controls">
          <label class="research-context-field"><span>企業</span><select data-context-company>${optionMarkup(companies, state.company, '全企業', item => item.id, item => `${item.ticker} · ${item.name}`)}</select></label>
          <label class="research-context-field"><span>同業グループ</span><select data-context-peer><option value="all">すべて</option>${peers.map(item => `<option value="${escapeHtml(item.id)}" ${item.id === state.peer ? 'selected' : ''}>${escapeHtml(item.label)}</option>`).join('')}</select></label>
          <label class="research-context-field"><span>期間</span><select data-context-period>${optionMarkup(periods, state.period, '最新・全期間', item => item, item => item)}</select></label>
          <label class="research-context-field"><span>値種別</span><select data-context-value>${Object.entries(valueTypes).map(([id, item]) => `<option value="${id}" ${id === state.valueType ? 'selected' : ''}>${escapeHtml(item.label)}</option>`).join('')}</select></label>
          <label class="research-context-field"><span>比較へ追加</span><select data-context-compare>${optionMarkup(companies.filter(item => !state.compare.includes(item.id)), '', '企業を選ぶ', item => item.id, item => `${item.ticker} · ${item.name}`)}</select></label>
        </div>
        <div class="research-context-selection">
          <span data-context-summary></span>
          <span class="research-value-badge research-value-${escapeHtml(state.valueType)}" data-value-badge>${escapeHtml(valueTypes[state.valueType].label)}</span>
          <div class="research-context-chips" data-context-chips></div>
          <div class="research-context-actions">
            <button type="button" data-context-focus aria-pressed="${state.focus}">${state.focus ? '全表示へ戻す' : '選択企業を強調'}</button>
            <button type="button" data-context-evidence>証拠と定義</button>
            <button type="button" data-context-reset>条件を解除</button>
          </div>
        </div>
      </div>`;
    return shell;
  }

  function evidenceDialog() {
    const dialog = document.createElement('dialog');
    dialog.className = 'research-evidence-dialog';
    dialog.id = 'research-evidence-dialog';
    dialog.innerHTML = `
      <div class="research-evidence-head">
        <div><h2>証拠と値種別</h2><p>現在の企業・期間・値種別から、一次資料、計算、品質状態へ移動します。</p></div>
        <button type="button" class="research-evidence-close" data-evidence-close aria-label="閉じる">×</button>
      </div>
      <div class="research-evidence-body">
        <section class="research-evidence-section"><h3>現在のコンテキスト</h3><p data-evidence-context></p><div class="research-context-chips" data-evidence-companies></div></section>
        <section class="research-evidence-section"><h3>この画面の証拠入口</h3><ul class="research-evidence-list" data-evidence-links></ul></section>
        <section class="research-evidence-section"><h3>値種別の定義</h3><div class="research-evidence-grid">${Object.entries(valueTypes).map(([id, item]) => `<div class="research-evidence-definition"><strong><span class="research-value-badge research-value-${id}">${escapeHtml(item.label)}</span></strong><span>${escapeHtml(item.description)}</span></div>`).join('')}</div></section>
        <section class="research-evidence-section"><h3>品質状態</h3><p>欠損・競合・比較不能・古さは空欄にせず、各画面の品質、注意点、UNKNOWN表示を確認してください。</p></section>
      </div>`;
    return dialog;
  }

  function injectShell() {
    const skip = document.createElement('a');
    skip.className = 'research-skip-link';
    skip.href = '#research-context';
    skip.textContent = '企業・期間の選択へ移動';
    document.body.prepend(skip);

    const shell = contextShell();
    const main = document.querySelector('main');
    document.body.insertBefore(shell, main || document.body.firstChild);
    const dialog = evidenceDialog();
    document.body.append(dialog);
    bindShell(shell, dialog);
    updateAll();
    if (state.evidence) openEvidence(shell.querySelector('[data-context-evidence]'), dialog);
  }

  function bindShell(shell, dialog) {
    const company = shell.querySelector('[data-context-company]');
    const peer = shell.querySelector('[data-context-peer]');
    const period = shell.querySelector('[data-context-period]');
    const value = shell.querySelector('[data-context-value]');
    const compare = shell.querySelector('[data-context-compare]');
    const focus = shell.querySelector('[data-context-focus]');
    const evidence = shell.querySelector('[data-context-evidence]');
    const reset = shell.querySelector('[data-context-reset]');
    const mobile = shell.querySelector('.research-mobile-toggle');

    company.addEventListener('change', event => { state.company = event.target.value; writeState(); updateAll(); });
    peer.addEventListener('change', event => { state.peer = event.target.value; writeState(); updateAll(); });
    period.addEventListener('change', event => { state.period = event.target.value; writeState(); updateAll(); });
    value.addEventListener('change', event => { state.valueType = event.target.value; writeState(); updateAll(); });
    compare.addEventListener('change', event => {
      const id = event.target.value;
      if (id && !state.compare.includes(id)) {
        if (state.compare.length >= maxCompare) {
          event.target.value = '';
          shell.querySelector('[data-context-summary]').textContent = `比較できるのは最大${maxCompare}社です。`;
          return;
        }
        state.compare.push(id);
      }
      event.target.value = '';
      writeState();
      rebuildCompareSelect();
      updateAll();
    });
    focus.addEventListener('click', () => { state.focus = !state.focus; writeState(); updateAll(); });
    evidence.addEventListener('click', () => openEvidence(evidence, dialog));
    reset.addEventListener('click', () => {
      state = { company: '', peer: 'all', period: '', valueType: 'actual', compare: [], focus: false, evidence: false };
      writeState();
      syncControls();
      updateAll();
      company.focus();
    });
    mobile.addEventListener('click', () => {
      const expanded = shell.dataset.expanded !== 'true';
      shell.dataset.expanded = String(expanded);
      mobile.setAttribute('aria-expanded', String(expanded));
    });
    dialog.querySelector('[data-evidence-close]').addEventListener('click', () => closeEvidence(dialog));
    dialog.addEventListener('cancel', event => { event.preventDefault(); closeEvidence(dialog); });
    dialog.addEventListener('click', event => { if (event.target === dialog) closeEvidence(dialog); });
    window.addEventListener('popstate', () => {
      state = readState();
      syncControls();
      updateAll();
      if (state.evidence) openEvidence(evidence, dialog); else if (dialog.open) dialog.close();
    });
  }

  function syncControls() {
    const shell = document.querySelector('.research-context-shell');
    if (!shell) return;
    shell.querySelector('[data-context-company]').value = state.company;
    shell.querySelector('[data-context-peer]').value = state.peer;
    shell.querySelector('[data-context-period]').value = state.period;
    shell.querySelector('[data-context-value]').value = state.valueType;
    rebuildCompareSelect();
  }

  function rebuildCompareSelect() {
    const select = document.querySelector('[data-context-compare]');
    if (!select) return;
    select.innerHTML = optionMarkup(companies.filter(item => !state.compare.includes(item.id)), '', '企業を選ぶ', item => item.id, item => `${item.ticker} · ${item.name}`);
  }

  function selectedCompanies() {
    return unique([state.company, ...state.compare]).map(companyById).filter(Boolean);
  }

  function updateSummary() {
    const shell = document.querySelector('.research-context-shell');
    const selected = selectedCompanies();
    const company = companyById(state.company);
    const peer = peers.find(item => item.id === state.peer);
    const parts = [
      company ? `${company.ticker} ${company.name}` : '全企業',
      peer && peer.id !== 'all' ? peer.label : null,
      state.period || '最新・全期間',
    ].filter(Boolean);
    shell.querySelector('[data-context-summary]').innerHTML = `<strong>${escapeHtml(parts.join(' / '))}</strong>`;
    const badge = shell.querySelector('[data-value-badge]');
    badge.className = `research-value-badge research-value-${state.valueType}`;
    badge.textContent = valueTypes[state.valueType].label;
    const chips = shell.querySelector('[data-context-chips]');
    chips.innerHTML = selected.map(item => `<span class="research-context-chip">${escapeHtml(item.ticker)}<button type="button" data-remove-company="${escapeHtml(item.id)}" aria-label="${escapeHtml(item.name)}を選択から外す">×</button></span>`).join('');
    chips.querySelectorAll('[data-remove-company]').forEach(button => button.addEventListener('click', () => {
      const id = button.dataset.removeCompany;
      if (state.company === id) state.company = '';
      state.compare = state.compare.filter(item => item !== id);
      writeState();
      syncControls();
      updateAll();
    }));
    const focus = shell.querySelector('[data-context-focus]');
    focus.setAttribute('aria-pressed', String(state.focus));
    focus.textContent = state.focus ? '全表示へ戻す' : '選択企業を強調';
  }

  function updateCrossLinks(params = new URLSearchParams(location.search)) {
    document.querySelectorAll('[data-context-link]').forEach(link => {
      const target = pagePaths[link.dataset.contextLink];
      const clean = new URLSearchParams(params);
      clean.delete('evidence');
      link.href = `${target}${clean.size ? `?${clean}` : ''}`;
    });
  }

  function candidateElements() {
    const main = document.querySelector('main');
    if (!main) return [];
    return [...main.querySelectorAll('article, tr')].filter(element => {
      const text = element.textContent || '';
      return companies.some(company => text.includes(company.ticker) || text.includes(company.name));
    });
  }

  function applyContextHighlight() {
    const selected = selectedCompanies();
    const candidates = candidateElements();
    candidates.forEach(element => {
      element.classList.remove('research-context-match', 'research-context-dim');
      if (!selected.length) return;
      const text = element.textContent || '';
      const matches = selected.some(company => text.includes(company.ticker) || text.includes(company.name));
      if (matches) element.classList.add('research-context-match');
      else if (state.focus) element.classList.add('research-context-dim');
    });
    if (state.focus && selected.length) {
      const first = candidates.find(element => element.classList.contains('research-context-match'));
      first?.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'center' });
    }
  }

  function evidenceLinks() {
    return (pageEvidence[page] || []).map(item => {
      const href = item.href.startsWith('#') ? item.href : `${base}${item.href.replace(/^\//, '')}`;
      return `<li><a href="${escapeHtml(href)}">${escapeHtml(item.label)} <span aria-hidden="true">→</span></a></li>`;
    }).join('');
  }

  function openEvidence(trigger, dialog) {
    lastDialogTrigger = trigger;
    state.evidence = true;
    writeState();
    const selected = selectedCompanies();
    const context = [selected.map(item => `${item.ticker} ${item.name}`).join('・') || '全企業', state.period || '最新・全期間', valueTypes[state.valueType].label].join(' / ');
    dialog.querySelector('[data-evidence-context]').textContent = context;
    dialog.querySelector('[data-evidence-companies]').innerHTML = selected.map(item => `<span class="research-context-chip">${escapeHtml(item.ticker)} · ${escapeHtml(item.name)}</span>`).join('');
    dialog.querySelector('[data-evidence-links]').innerHTML = evidenceLinks();
    if (!dialog.open) dialog.showModal();
    dialog.querySelector('[data-evidence-close]').focus();
  }

  function closeEvidence(dialog) {
    state.evidence = false;
    writeState();
    dialog.close();
    lastDialogTrigger?.focus();
  }

  function updateAll() {
    updateSummary();
    updateCrossLinks();
    applyContextHighlight();
  }

  injectShell();
})();
