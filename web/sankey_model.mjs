// Pure, independently testable layout for the G-09 release-transition Sankey.
// Width encodes the actual number of *case states*, not MIC S/I/R labels.
import { STATE_ORDER } from './view_meta.mjs';

const codes = new Set(STATE_ORDER);

export function sankeyModel(response, { width = 1100, top = 44, height = 356, gap = 13 } = {}) {
  if (!response || !Array.isArray(response.flows)) throw new TypeError('Invalid transition response');
  const rows = response.flows.map(item => ({
    before_state: item.before_state, after_state: item.after_state, count: item.count,
  }));
  if (rows.some(row => !codes.has(row.before_state) || !codes.has(row.after_state)
    || !Number.isSafeInteger(row.count) || row.count < 0)) {
    throw new TypeError('Unknown case state or invalid count in transition response');
  }
  const total = rows.reduce((n, row) => n + row.count, 0);
  if (total !== response.comparable_cases) throw new TypeError('Transition counts disagree with comparable case total');
  if (!Number.isSafeInteger(total) || total < 0) throw new TypeError('Invalid comparable case total');

  const before = new Map(STATE_ORDER.map(code => [code, 0]));
  const after = new Map(STATE_ORDER.map(code => [code, 0]));
  for (const row of rows) {
    before.set(row.before_state, before.get(row.before_state) + row.count);
    after.set(row.after_state, after.get(row.after_state) + row.count);
  }
  const chartHeight = height - (STATE_ORDER.length - 1) * gap;
  const scale = total ? chartHeight / total : 0;
  const nodes = (counts, x) => {
    let y = top;
    return STATE_ORDER.map(code => {
      const size = counts.get(code) * scale;
      const node = { code, x, y, height: size, count: counts.get(code) };
      y += size + gap;
      return node;
    });
  };
  const left = nodes(before, 228);
  const right = nodes(after, width - 243);
  const leftPositions = new Map(left.map(node => [node.code, node.y]));
  const rightPositions = new Map(right.map(node => [node.code, node.y]));
  // Fixed category ordering means the same source and destination always agree
  // about the stacking of their incoming/outgoing ribbons.
  const sorted = [...rows].filter(row => row.count).sort((a, b) =>
    STATE_ORDER.indexOf(a.before_state) - STATE_ORDER.indexOf(b.before_state)
    || STATE_ORDER.indexOf(a.after_state) - STATE_ORDER.indexOf(b.after_state));
  const ribbons = sorted.map(row => {
    const y1 = leftPositions.get(row.before_state);
    const y2 = rightPositions.get(row.after_state);
    const thickness = row.count * scale;
    leftPositions.set(row.before_state, y1 + thickness);
    rightPositions.set(row.after_state, y2 + thickness);
    const x1 = left[0].x + 17;
    const x2 = right[0].x;
    const mid1 = x1 + (x2 - x1) * 0.43;
    const mid2 = x1 + (x2 - x1) * 0.57;
    const path = `M${x1},${y1} C${mid1},${y1} ${mid2},${y2} ${x2},${y2}`
      + ` L${x2},${y2 + thickness} C${mid2},${y2 + thickness}`
      + ` ${mid1},${y1 + thickness} ${x1},${y1 + thickness} Z`;
    return { ...row, y1, y2, thickness, path, changed: row.before_state !== row.after_state };
  });
  return { total, left, right, ribbons };
}

export function countChanged(model) {
  return model.ribbons.filter(r => r.changed).reduce((sum, r) => sum + r.count, 0);
}
