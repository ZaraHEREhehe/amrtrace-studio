// G-09: additive read-only Dashboard panel. Never edits stored case states.
import {
  getReleaseTransitions, getReleaseTransitionCases, listPublishedReleases,
} from './api.mjs';
import { routeHash } from './ids.mjs';
import { STATE_ORDER, stateMeta, formatCount, formatShare } from './view_meta.mjs';
import { sankeyModel, countChanged } from './sankey_model.mjs';

const NS = 'http://www.w3.org/2000/svg';
let currentLoad = 0;
let currentDrill = 0;

function el(tag, className, text) {
  const x = document.createElement(tag);
  if (className) x.className = className;
  if (text !== undefined) x.textContent = text;
  return x;
}
function svg(tag, attributes = {}) {
  const node = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attributes)) node.setAttribute(k, String(v));
  return node;
}
function label(code) { return stateMeta(code).label; }
function selectControl(name, items, selected, callback) {
  const wrapper = el('label', 'sankey-field');
  wrapper.append(el('span', null, name));
  const input = el('select');
  input.setAttribute('aria-label', name);
  for (const item of items) {
    const option = el('option', null, item.label);
    option.value = item.value;
    input.append(option);
  }
  input.value = selected;
  input.addEventListener('change', () => callback(input.value));
  wrapper.append(input);
  return wrapper;
}

function renderFlowChart(parent, response, changedOnly, onSelect, message) {
  parent.replaceChildren();
  const model = sankeyModel(response);
  const changed = countChanged(model);
  const summary = el('p', 'sankey-summary');
  summary.textContent = `${formatCount(model.total)} comparable cases · ${formatCount(changed)} changed state · ${formatCount(model.total - changed)} unchanged`;
  parent.append(summary);
  if (changedOnly) parent.append(el('p','sankey-hint','Changed-only view: unchanged ribbons are hidden but node totals remain based on all comparable cases.'));
  if (response.missing_before || response.missing_after) {
    const note = el('p', 'sankey-warning',
      `${formatCount(response.missing_before)} cases missing a prior state; ${formatCount(response.missing_after)} missing a later state. These are excluded from ribbons.`);
    parent.append(note);
  }
  if (response.before_snapshot !== response.after_snapshot) {
    parent.append(el('p', 'sankey-warning',
      'Different source snapshots: flows compare only matching case IDs, not biological events inferred from those differences.'));
  }
  if (!model.total || (changedOnly && !changed)) {
    parent.append(el('p', 'sankey-empty', changedOnly ? 'No cases changed state in this comparison.' : 'No comparable published case states.'));
    return;
  }

  const scroller = el('div', 'sankey-scroll');
  const chart = svg('svg', { viewBox: '0 0 1100 465', role: 'group',
    'aria-label': `Case state transitions from ${response.before_release} to ${response.after_release}` });
  const leftTitle = svg('text', {x:228, y:22, 'text-anchor':'middle',class:'sankey-axis-label'});
  leftTitle.textContent = `${response.before_release} (before)`;
  const rightTitle = svg('text', {x:859, y:22, 'text-anchor':'middle',class:'sankey-axis-label'});
  rightTitle.textContent = `${response.after_release} (after)`;
  chart.append(leftTitle, rightTitle);

  // Large flows are painted first; small changed ribbons remain visible above them.
  for (const ribbon of [...model.ribbons].sort((a,b) => b.count - a.count)) {
    if (changedOnly && !ribbon.changed) continue;
    const code = ribbon.before_state;
    const path = svg('path', {
      d: ribbon.path, class: 'sankey-ribbon', fill: stateMeta(code).line,
      'fill-opacity': ribbon.changed ? '.48' : '.28', tabindex: 0, role: 'button',
      'aria-label': `${label(code)} to ${label(ribbon.after_state)}: ${ribbon.count} cases`,
    });
    const tip = svg('title');
    tip.textContent = `${label(code)} → ${label(ribbon.after_state)}: ${formatCount(ribbon.count)} cases (${formatShare(ribbon.count, model.total)})`;
    path.append(tip);
    path.addEventListener('focus', () => { message.textContent = tip.textContent; });
    path.addEventListener('mouseenter', () => { message.textContent = tip.textContent; });
    const select = () => onSelect(ribbon);
    path.addEventListener('click', select);
    path.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); select(); }
    });
    chart.append(path);
  }
  // Keep tiny (<1%) categories readable without inflating their ribbon widths.
  // Label positions may spread out, but the scientific area encoding stays exact.
  for (const [nodes, side] of [[model.left, 'before'], [model.right, 'after']]) {
    const visibleNodes = nodes.filter(node => node.count);
    const labelYs = [];
    let lastY = 34;
    for (const node of visibleNodes) {
      const targetY = node.y + node.height / 2;
      lastY = Math.max(targetY, lastY + 21);
      labelYs.push(lastY);
    }
    const excess = Math.max(0, (labelYs.at(-1) ?? 0) - 430);
    for (let i = 0; i < labelYs.length; i++) labelYs[i] -= excess;
    for (const [index, node] of visibleNodes.entries()) {
      if (!node.count) continue;
      const rect = svg('rect', {x:node.x,y:node.y,width:17,height:Math.max(node.height,.25),
        fill:stateMeta(node.code).line, rx:2, class:'sankey-node'});
      const tip = svg('title'); tip.textContent = `${label(node.code)}: ${formatCount(node.count)}`;
      rect.append(tip); chart.append(rect);
      const y = labelYs[index];
      const x = side === 'before' ? 214 : node.x + 26;
      if (Math.abs(y - (node.y + node.height / 2)) > 3) {
        const line = svg('line', {
          x1: side === 'before' ? node.x - 3 : node.x + 20,
          y1: node.y + node.height / 2,
          x2: side === 'before' ? x + 5 : x - 5, y2: y,
          class: 'sankey-label-guide',
        });
        chart.append(line);
      }
      const text = svg('text', {x, y, 'text-anchor':side==='before'?'end':'start',
        'dominant-baseline':'middle',class:'sankey-node-label'});
      text.textContent = label(node.code);
      chart.append(text);
    }
  }
  scroller.append(chart);
  parent.append(scroller);
  const notes = el('p','sankey-hint','Hover or select a ribbon to inspect its transition. Ribbon width represents case count. On narrow screens, scroll horizontally to see both releases.');
  parent.append(notes);
  const tableDetails = el('details', 'sankey-table-details');
  tableDetails.append(el('summary',null,'View accessible transition counts'));
  const table = el('table', 'sankey-count-table');
  const head = el('thead');
  const row = el('tr');
  for (const name of ['Before state', 'After state', 'Cases']) row.append(el('th',null,name));
  head.append(row); table.append(head);
  const body = el('tbody');
  for (const ribbon of model.ribbons) {
    if (changedOnly && !ribbon.changed) continue;
    const tr = el('tr');
    tr.append(el('td',null,label(ribbon.before_state)),el('td',null,label(ribbon.after_state)));
    const cell = el('td');
    const button = el('button','sankey-count-button',formatCount(ribbon.count));
    button.type = 'button';
    button.setAttribute('aria-label',`View ${ribbon.count} cases: ${label(ribbon.before_state)} to ${label(ribbon.after_state)}`);
    button.addEventListener('click',() => onSelect(ribbon));
    cell.append(button); tr.append(cell); body.append(tr);
  }
  table.append(body); tableDetails.append(table); parent.append(tableDetails);
}

export async function loadReleaseTransitionPanel(latest, drugs) {
  const root = document.getElementById('dashboard-transitions');
  if (!root) return;
  const generation = ++currentLoad;
  root.replaceChildren();
  const status = el('div','sankey-status','Loading published releases…');
  status.setAttribute('role','status');
  const controls = el('div','sankey-controls');
  const plot = el('div','sankey-plot');
  const feedback = el('p','sankey-feedback');
  feedback.setAttribute('aria-live','polite');
  const details = el('div','sankey-details');
  root.append(status, controls, plot, feedback, details);
  if (!latest) { status.textContent = 'No published release is available for comparison.'; return; }

  try {
    const releases = (await listPublishedReleases()).sort((a,b) => a.release_seq - b.release_seq);
    if (generation !== currentLoad) return;
    const ix = releases.findIndex(r => r.release_id === latest.release_id);
    const index = ix >= 0 ? ix : releases.length - 1;
    if (index < 1) { status.textContent = 'At least two published releases are needed for a transition chart.'; return; }
    const state = { before: releases[index - 1].release_id, after: releases[index].release_id,
      antibiotic: '', changedOnly: false };
    const releaseItems = releases.map(r => ({ value:r.release_id, label:r.release_id }));
    const drugItems = [{value:'',label:'All antibiotics'},
      ...(drugs || []).map(d => ({value:d.antibiotic,label:d.antibiotic}))];

    const selection = el('label','sankey-checkbox');
    const toggle = el('input'); toggle.type = 'checkbox';
    toggle.addEventListener('change', () => { state.changedOnly = toggle.checked; ++currentDrill; details.replaceChildren(); renderCurrent(); });
    selection.append(toggle, el('span',null,'Show changed transitions only'));
    controls.append(
      selectControl('From release',releaseItems,state.before, v => {state.before = v; void fetchData();}),
      selectControl('To release',releaseItems,state.after, v => {state.after = v; void fetchData();}),
      selectControl('Antibiotic',drugItems,state.antibiotic, v => {state.antibiotic = v; void fetchData();}),
      selection,
    );

    let response = null;
    let request = 0;
    function renderCurrent() {
      if (response) renderFlowChart(plot,response,state.changedOnly, showCases,feedback);
    }
    async function fetchData() {
      const token = ++request;
      ++currentDrill;
      response = null;
      details.replaceChildren();
      plot.replaceChildren();
      feedback.textContent = '';
      const before = releases.find(r => r.release_id === state.before);
      const after = releases.find(r => r.release_id === state.after);
      if (!before || !after || before.release_seq >= after.release_seq) {
        status.textContent = 'Choose an earlier “From” release and a later “To” release.';
        return;
      }
      status.textContent = 'Calculating transitions across effective published states…';
      try {
        const result = await getReleaseTransitions(state.before,state.after,state.antibiotic || null);
        if (generation !== currentLoad || token !== request) return;
        response = result;
        const descriptions = [
          `From: ${result.before_release} (${result.before_interpretation || 'as reported'}; ${result.before_verification || 'not recorded'})`,
          `To: ${result.after_release} (${result.after_interpretation || 'as reported'}; ${result.after_verification || 'not recorded'})`,
        ];
        status.textContent = descriptions.join('  ·  ');
        renderCurrent();
      } catch (error) {
        if (generation === currentLoad && token === request) status.textContent = `Could not load transition chart: ${error.message}`;
      }
    }
    async function showCases(ribbon) {
      const token = ++currentDrill;
      details.replaceChildren();
      details.append(el('h4',null,`${label(ribbon.before_state)} → ${label(ribbon.after_state)}`));
      const intro = el('p','sankey-summary',`${formatCount(ribbon.count)} matching case(s) · Dossiers show the latest published state; use their state histories to inspect ${state.before} and ${state.after}.`);
      details.append(intro);
      const content = el('div');
      const actions = el('div','sankey-pager');
      details.append(content,actions);
      let offset = 0;
      async function page() {
        if (generation !== currentLoad || token !== currentDrill) return;
        content.replaceChildren(el('p','sankey-hint','Loading case list…'));
        actions.replaceChildren();
        try {
          const data = await getReleaseTransitionCases(
            state.before,state.after,ribbon.before_state,ribbon.after_state,
            state.antibiotic || null,25,offset);
          if (generation !== currentLoad || token !== currentDrill) return;
          content.replaceChildren();
          if (!data.items.length) { content.append(el('p',null,'No cases on this page.')); return; }
          const list = el('ul','sankey-case-list');
          for (const item of data.items) {
            const li = el('li');
            const link = el('a',null,`${item.target_acc} · ${item.antibiotic} · ${item.case_id}`);
            link.href = routeHash('dossier',item.case_id);
            li.append(link); list.append(li);
          }
          content.append(list);
          const prev = el('button','button','Previous'); prev.type='button';prev.disabled=offset===0;
          prev.addEventListener('click',() => {offset=Math.max(0,offset-25);void page();});
          const next = el('button','button','Next');next.type='button';next.disabled=!data.has_more;
          next.addEventListener('click',() => {offset+=25;void page();});
          actions.append(prev,el('span',null,`Cases ${offset+1}–${offset+data.items.length} of ${formatCount(ribbon.count)}`),next);
        } catch (error) {
          if (generation === currentLoad && token === currentDrill)
            content.replaceChildren(el('p','sankey-warning',`Could not load case list: ${error.message}`));
        }
      }
      await page();
    }
    await fetchData();
  } catch (error) {
    if (generation === currentLoad) status.textContent = `Could not list published releases: ${error.message}`;
  }
}
