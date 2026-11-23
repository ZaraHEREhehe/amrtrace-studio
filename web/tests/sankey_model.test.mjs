import test from 'node:test';
import assert from 'node:assert/strict';
import { sankeyModel, countChanged } from '../sankey_model.mjs';
import { STATE_ORDER } from '../view_meta.mjs';
const [CR,CS,GP,PR,U] = STATE_ORDER;

const response = {
  comparable_cases: 41858,
  flows: [
    {before_state:CR, after_state:CR, count:5470},
    {before_state:CR, after_state:CS, count:30},
    {before_state:CS, after_state:CS, count:28753},
    {before_state:CS, after_state:GP, count:30},
    {before_state:GP, after_state:GP, count:1255},
    {before_state:GP, after_state:CR, count:19},
    {before_state:GP, after_state:CS, count:11},
    {before_state:PR, after_state:PR, count:451},
    {before_state:U, after_state:U, count:5839},
  ]
};
// Total of above needs to sum to 41,858; the model rejects any mismatch.
const sum = response.flows.reduce((acc,r) => acc+r.count,0);
response.comparable_cases = sum;

test('all flow widths and source/target node totals conserve case counts',() => {
  const model = sankeyModel(response);
  assert.equal(model.total, response.comparable_cases);
  assert.equal(model.left.reduce((sum,n)=>sum+n.count,0),model.total);
  assert.equal(model.right.reduce((sum,n)=>sum+n.count,0),model.total);
  assert.equal(model.ribbons.reduce((sum,n)=>sum+n.count,0),model.total);
  assert.ok(model.ribbons.every(r=>r.thickness>=0 && r.path.endsWith(' Z')));
});

test('changed count excludes same-state flows',() => {
  assert.equal(countChanged(sankeyModel(response)),90);
});

test('unknown state cannot render as legitimate scientific category',() => {
  assert.throws(()=>sankeyModel({ comparable_cases:1, flows:[{
    before_state:'INTERMEDIATE',after_state:CR,count:1}]}),TypeError);
});

test('broken API aggregate is detected instead of silently displayed',() => {
  assert.throws(()=>sankeyModel({...response,comparable_cases:999999}),TypeError);
});

test('zero cases render a valid empty model',() => {
  const model=sankeyModel({comparable_cases:0, flows:[]});
  assert.equal(model.total,0);
  assert.equal(model.ribbons.length,0);
});

test('ribbon thickness proportional to count for positive flows',() => {
  const model = sankeyModel(response);
  const a=model.ribbons.find(r=>r.count===30);
  const b=model.ribbons.find(r=>r.count===451);
  assert.ok(Math.abs(a.thickness / b.thickness - (30/451)) < 1e-8);
});
