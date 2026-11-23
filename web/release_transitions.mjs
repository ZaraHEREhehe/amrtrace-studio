// G-09: additive read-only Dashboard panel. Never edits stored case states.
import {
  getReleaseTransitions, getReleaseTransitionCases, listPublishedReleases,
} from './api.mjs';
import { routeHash } from './ids.mjs';
import { STATE_ORDER, stateMeta, formatCount, formatShare } from './view_meta.mjs';
import { sankeyModel, countChanged } from './sankey_model.mjs';

const NS = 'http://www.w3.org/2000/svg';
// Darker shades of the existing five state colors, used only for 1.8 px
// emphasis strokes. The actual count-encoded ribbon geometry is unchanged.
const TRANSITION_TRACE_COLOR = Object.freeze({
  CONCORDANT_RESISTANT: '#16865d',
  CONCORDANT_SUSCEPTIBLE: '#32856b',
  DISCORDANT_GENOTYPE_POSITIVE_PHENOTYPE_S: '#ac7c14',
  DISCORDANT_PHENOTYPE_R_NO_MAPPED_GENOTYPE: '#bd565b',
  UNRESOLVED: '#586bc0',
});
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
function preciseShare(count, total) {
  if (!total) return '—';
  return count > 0 && count / total < 0.001 ? '<0.1%' : formatShare(count, total);
}
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

function renderFlowChart(parent, response, changedOnly, onSelect, message, expanded = false) {
  parent.replaceChildren();
  // A compact overview by default; expanding restores the original full-height
  // geometry. Only presentation dimensions change: case counts and ribbons do not.
  const geometry = expanded
    ? {top: 44, height: 356, gap: 13}
    : {top: 23, height: 90, gap: 3};
  const fullModel = sankeyModel(response, geometry);
  const changed = countChanged(fullModel);
  // Only the focused view is re-scaled. It displays real counts and preserves
  // relative widths *among changed transitions*; the overview still uses the
  // full-cohort denominator, including all unchanged cases.
  const focusedResponse = {
    ...response,
    flows: response.flows.filter(flow => flow.before_state !== flow.after_state),
    comparable_cases: changed,
  };
  const model = changedOnly && changed ? sankeyModel(focusedResponse, geometry) : fullModel;
  const summary = el('p', 'sankey-summary');
  summary.textContent = `${formatCount(fullModel.total)} comparable cases · ${formatCount(changed)} changed state · ${formatCount(fullModel.total - changed)} unchanged`;
  parent.append(summary);
  if (changedOnly && changed) {
    const focusNote = el('p', 'sankey-focus-note',
      `Focused scale: ribbon widths represent the ${formatCount(changed)} changed cases, not all ${formatCount(fullModel.total)} comparable cases. Counts are unchanged.`);
    focusNote.setAttribute('role', 'note');
    parent.append(focusNote);
  }
  if (response.missing_before || response.missing_after) {
    const note = el('p', 'sankey-warning',
      `${formatCount(response.missing_before)} cases missing a prior state; ${formatCount(response.missing_after)} missing a later state. These are excluded from ribbons.`);
    parent.append(note);
  }
  if (response.before_snapshot !== response.after_snapshot) {
    parent.append(el('p', 'sankey-warning',
      'Different source snapshots: flows compare only matching case IDs, not biological events inferred from those differences.'));
  }
  if (!fullModel.total || (changedOnly && !changed)) {
    parent.append(el('p', 'sankey-empty', changedOnly ? 'No cases changed state in this comparison.' : 'No comparable published case states.'));
    return;
  }

  const scroller = el('div', 'sankey-scroll');
  const chart = svg('svg', { viewBox: expanded ? '0 0 1100 465' : '0 0 1100 132', role: 'group',
    'data-scale-denominator': model.total,
    'data-cohort-total': fullModel.total,
    'aria-label': `${changedOnly ? 'Changed-only, rescaled' : 'Full-cohort'} case state transitions from ${response.before_release} to ${response.after_release}` });
  const leftTitle = svg('text', {x:228, y: expanded ? 22 : 16, 'text-anchor':'middle',class:'sankey-axis-label'});
  leftTitle.textContent = `${response.before_release} (before)`;
  const rightTitle = svg('text', {x:859, y: expanded ? 22 : 16, 'text-anchor':'middle',class:'sankey-axis-label'});
  rightTitle.textContent = `${response.after_release} (after)`;
  chart.append(leftTitle, rightTitle);

  // Accurate ribbons and separate, non-data-encoded visibility aids:
  // 1) every ribbon's *fill area* remains proportional to its case count;
  // 2) changed routes receive a contrasting thin centreline, regardless of
  //    whether their correct area is subpixel in the full-cohort view;
  // 3) a transparent 16px hit target makes rare routes selectable by mouse.
  const fills = svg('g', {class: 'sankey-flow-layer'});
  const traces = svg('g', {class: 'sankey-trace-layer'});
  const hitTargets = svg('g', {class: 'sankey-hit-layer'});
  const entries = [];
  let selected = null;
  function emphasize(active = null) {
    for (const entry of entries) {
      const dimmed = Boolean(active && entry.ribbon !== active);
      const focused = Boolean(active && entry.ribbon === active);
      entry.fill.classList.toggle('sankey-flow-dimmed', dimmed);
      entry.fill.classList.toggle('sankey-flow-focused', focused);
      if (entry.trace) {
        entry.trace.classList.toggle('sankey-flow-dimmed', dimmed);
        entry.trace.classList.toggle('sankey-flow-focused', focused);
      }
    }
  }
  for (const ribbon of [...model.ribbons].sort((a,b) => b.count - a.count)) {
    const code = ribbon.before_state;
    const percent = preciseShare(ribbon.count, fullModel.total);
    const detail = `${label(code)} → ${label(ribbon.after_state)}: ${formatCount(ribbon.count)} cases (${percent} of all comparable cases${changedOnly ? `; ${formatShare(ribbon.count, changed)} of changed cases` : ''})`;
    const path = svg('path', {
      d: ribbon.path, class: 'sankey-ribbon', fill: stateMeta(code).line,
      'data-count': ribbon.count, 'data-thickness': ribbon.thickness,
      'fill-opacity': ribbon.changed ? '.53' : '.28', tabindex: 0, role: 'button',
      'aria-label': detail,
    });
    const tip = svg('title'); tip.textContent = detail;
    path.append(tip);
    const activate = () => { selected = ribbon; emphasize(ribbon); onSelect(ribbon); };
    const onHover = () => { message.textContent = detail; emphasize(ribbon); };
    const onLeave = () => emphasize(selected);
    path.addEventListener('focus', onHover);
    path.addEventListener('blur', onLeave);
    path.addEventListener('mouseenter', onHover);
    path.addEventListener('mouseleave', onLeave);
    path.addEventListener('click', activate);
    path.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); activate(); }
    });
    fills.append(path);
    let trace = null;
    if (ribbon.changed) {
      const x1 = model.left[0].x + 17;
      const x2 = model.right[0].x;
      const mid1 = x1 + (x2 - x1) * .43;
      const mid2 = x1 + (x2 - x1) * .57;
      const fromY = ribbon.y1 + ribbon.thickness / 2;
      const toY = ribbon.y2 + ribbon.thickness / 2;
      const centerline = `M${x1},${fromY} C${mid1},${fromY} ${mid2},${toY} ${x2},${toY}`;
      trace = svg('path', {
        d: centerline, class: 'sankey-change-trace', 'data-count': ribbon.count, fill: 'none',
        stroke: TRANSITION_TRACE_COLOR[code] || '#1c7293',
        'stroke-width': changedOnly ? 1.1 : 2,
        'vector-effect': 'non-scaling-stroke',
        'aria-hidden': 'true', 'pointer-events': 'none',
      });
      traces.append(trace);
      const hit = svg('path', {
        d: centerline, class: 'sankey-change-hit', 'data-count': ribbon.count, fill: 'none', stroke: 'transparent',
        'stroke-width': 16, 'vector-effect': 'non-scaling-stroke',
        'aria-hidden': 'true',
      });
      hit.addEventListener('mouseenter', onHover);
      hit.addEventListener('mouseleave', onLeave);
      hit.addEventListener('click', activate);
      hitTargets.append(hit);
    }
    entries.push({ribbon, fill: path, trace});
  }
  chart.append(fills, traces, hitTargets);
  // Keep tiny (<1%) categories readable without inflating their ribbon widths.
  // Label positions may spread out, but the scientific area encoding stays exact.
  for (const [nodes, side] of [[model.left, 'before'], [model.right, 'after']]) {
    const visibleNodes = nodes.filter(node => node.count);
    const labelYs = [];
    let lastY = expanded ? 34 : 22;
    for (const node of visibleNodes) {
      const targetY = node.y + node.height / 2;
      lastY = Math.max(targetY, lastY + (expanded ? 21 : 19));
      labelYs.push(lastY);
    }
    const excess = Math.max(0, (labelYs.at(-1) ?? 0) - (expanded ? 430 : 124));
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
  const notes = el('p','sankey-usage-hint sankey-hint',expanded
    ? 'Darker fine lines mark changed routes; the filled ribbon widths encode case counts. Hover or select a route. On narrow screens, scroll horizontally.'
    : 'Dark fine lines mark changed routes; ribbon area remains proportional. Use Changed only to magnify rare routes.');
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
  plot.id = 'sankey-plot';
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
      antibiotic: '', changedOnly: false, expanded: false };
    const releaseItems = releases.map(r => ({ value:r.release_id, label:r.release_id }));
    const drugItems = [{value:'',label:'All antibiotics'},
      ...(drugs || []).map(d => ({value:d.antibiotic,label:d.antibiotic}))];

    const selection = el('label','sankey-checkbox');
    const toggle = el('input'); toggle.type = 'checkbox';
    toggle.addEventListener('change', () => { state.changedOnly = toggle.checked; ++currentDrill; details.replaceChildren(); renderCurrent(); });
    selection.append(toggle, el('span',null,'Changed only'));
    selection.title = 'Hide unchanged ribbons to focus on state transitions';
    controls.append(
      selectControl('From release',releaseItems,state.before, v => {state.before = v; void fetchData();}),
      selectControl('To release',releaseItems,state.after, v => {state.after = v; void fetchData();}),
      selectControl('Antibiotic',drugItems,state.antibiotic, v => {state.antibiotic = v; void fetchData();}),
      selection,
    );
    // Expand only the new G-09 chart, never the surrounding Dashboard.
    const expand = el('button', 'button sankey-expand-button', 'Expand chart');
    expand.type = 'button';
    expand.setAttribute('aria-expanded', 'false');
    expand.setAttribute('aria-controls', 'sankey-plot');
    expand.addEventListener('click', () => {
      state.expanded = !state.expanded;
      root.classList.toggle('sankey-expanded', state.expanded);
      expand.textContent = state.expanded ? 'Compact view' : 'Expand chart';
      expand.setAttribute('aria-expanded', String(state.expanded));
      renderCurrent();
    });
    controls.append(expand);

    let response = null;
    let request = 0;
    function renderCurrent() {
      if (response) renderFlowChart(plot,response,state.changedOnly, showCases,feedback,state.expanded);
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
      const panel = el('details', 'sankey-case-details');
      panel.open = true; // Open after selection; researcher can collapse it at any time.
      const heading = el('summary', null,
        `${label(ribbon.before_state)} → ${label(ribbon.after_state)} · ${formatCount(ribbon.count)} cases`);
      panel.append(heading);
      const intro = el('p','sankey-summary',
        `Dossiers show the latest published state; use state history to inspect ${state.before} and ${state.after}.`);
      panel.append(intro);
      const content = el('div');
      const actions = el('div','sankey-pager');
      panel.append(content,actions);
      details.append(panel);
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
