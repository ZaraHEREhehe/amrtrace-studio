import test from 'node:test';
import assert from 'node:assert/strict';
import { loadReleaseTransitionPanel } from '../release_transitions.mjs';
import { sankeyModel, countChanged } from '../sankey_model.mjs';

class FakeElement {
  constructor(tag) {
    this.tag=tag;this.children=[];this.attributes={};this.listeners={};this._text='';this.value='';this.checked=false;
    this.classList={toggle:(key,force)=>{
      const names=new Set(this.className.split(/\s+/).filter(Boolean));
      const add=force===undefined?!names.has(key):Boolean(force);
      if(add)names.add(key);else names.delete(key);
      this.className=[...names].join(' ');
      return add;
    }};
  }
  set className(value) {this.attributes.class=value;}
  get className() {return this.attributes.class || '';}
  set textContent(value) {this._text=String(value);this.children=[];}
  get textContent() {return this._text+this.children.map(x=>x.textContent).join('');}
  append(...nodes) {this.children.push(...nodes);}
  replaceChildren(...nodes) {this.children=[...nodes];this._text='';}
  setAttribute(k,v) {this.attributes[k]=String(v);}
  addEventListener(k,handler) {(this.listeners[k] ||= []).push(handler);}
  async trigger(k,event={}) {for(const fn of this.listeners[k]||[]) await fn(event);}
  find(predicate) {return predicate(this)?[this,...this.children.flatMap(c=>c.find(predicate))]:this.children.flatMap(c=>c.find(predicate));}
}
function byClass(root,needle) {return root.find(el=>el.className.split(/\s+/).includes(needle));}
function byTag(root,needle) {return root.find(el=>el.tag===needle);}

function fakeBrowser() {
  // The checked-in api.mjs uses same-origin fetch, not the local test shim.
  // Mock the protocol here so this test also runs in the real repository.
  const [CR,CS,GP,PR,U] = [
    'CONCORDANT_RESISTANT','CONCORDANT_SUSCEPTIBLE',
    'DISCORDANT_GENOTYPE_POSITIVE_PHENOTYPE_S',
    'DISCORDANT_PHENOTYPE_R_NO_MAPPED_GENOTYPE','UNRESOLVED',
  ];
  globalThis.fetch = async url => {
    const path = new URL(url,'http://localhost').pathname;
    let data;
    if (path === '/api/releases') {
      data=[1,2,3,4].map(n=>({release_id:`R${n}`,release_seq:n}));
    } else if (path === '/api/releases/transitions') {
      const flows=[
        [CR,CR,5400],[CR,CS,20],[CS,CS,28763],[CS,GP,20],
        [GP,GP,1265],[GP,CR,20],[PR,PR,451],[U,U,5919]
      ].map(([before_state,after_state,count])=>({before_state,after_state,count}));
      const query=new URL(url,'http://localhost').searchParams;
      const factor=query.get('antibiotic')?0.19:1;
      const adjusted=flows.map(item=>({...item,count:Math.floor(item.count*factor)}));
      data={before_release:query.get('before'),after_release:query.get('after'),
        before_interpretation:'TEST_ED32',after_interpretation:'TEST_ED33',
        before_verification:'EXHAUSTIVE',after_verification:'SELECTIVE',
        before_snapshot:'COHORT_V1',after_snapshot:'COHORT_V1',
        comparable_cases:adjusted.reduce((n,row)=>n+row.count,0),
        missing_before:0,missing_after:0,flows:adjusted};
    } else if (path === '/api/releases/transitions/cases') {
      data={items:[{case_id:'CASE_TEST_001',target_acc:'ECOLI_TEST',
        antibiotic:'gentamicin'}],limit:25,offset:0,has_more:false};
    } else throw new Error(`Unexpected read-only API request: ${url}`);
    return {ok:true,status:200,async text(){return JSON.stringify(data);}};
  };
  const root = new FakeElement('div');
  globalThis.document = {
    getElementById: id => id==='dashboard-transitions'?root:null,
    createElement: tag => new FakeElement(tag),
    createElementNS: (_,tag) => new FakeElement(tag),
  };
  return root;
}

test('Dashboard chart uses default published pair; every existing component is isolated', async () => {
  const root=fakeBrowser();
  await loadReleaseTransitionPanel({release_id:'R4'},[{antibiotic:'gentamicin'}]);
  assert.match(byClass(root,'sankey-status')[0].textContent,/R3.*R4/);
  assert.equal(byClass(root,'sankey-ribbon').length,8);
  assert.equal(byClass(root,'sankey-node-label').length,10);
  assert.ok(byClass(root,'sankey-count-table').length===1);
  assert.ok(root.textContent.includes('changed state'));
});

test('Changed-only rescales real changed flows and keeps cohort counts', async () => {
  const root=fakeBrowser();
  await loadReleaseTransitionPanel({release_id:'R4'},[{antibiotic:'gentamicin'}]);
  const checkbox=byTag(root,'input')[0];
  checkbox.checked=true;
  await checkbox.trigger('change');
  assert.equal(byClass(root,'sankey-ribbon').length,3);
  assert.match(root.textContent,/Focused scale: ribbon widths represent the 60 changed cases, not all 41,858/);
  const chart = byTag(root,'svg')[0];
  assert.equal(chart.attributes['data-scale-denominator'],'60');
  assert.equal(chart.attributes['data-cohort-total'],'41858');
  for(const path of byClass(root,'sankey-ribbon')) {
    assert.equal(path.attributes['data-count'],'20');
    assert.ok(Number(path.attributes['data-thickness'])>20,'changed flows must be visibly rescaled');
  }
  assert.equal(byClass(root,'sankey-change-trace').length,3);
  assert.equal(byClass(root,'sankey-change-hit').length,3);
});

test('Keyboard-selected ribbon lists exact cases and dossier links', async () => {
  const root=fakeBrowser();
  await loadReleaseTransitionPanel({release_id:'R4'},[{antibiotic:'gentamicin'}]);
  const ribbon=byClass(root,'sankey-ribbon')[1];
  let prevented=false;
  await ribbon.trigger('keydown',{key:'Enter',preventDefault(){prevented=true;}});
  assert.ok(prevented);
  for (let i = 0; i < 12 && !byClass(root,'sankey-case-list').length; i++) {
    await new Promise(resolve => setImmediate(resolve));
  }
  assert.ok(byClass(root,'sankey-case-list').length);
  const link=byTag(root,'a')[0];
  assert.match(link.href,/^#\/dossier\/CASE_TEST_/);
});

test('Release and antibiotic controls exist without altering existing Dashboard elements', async () => {
  const root=fakeBrowser();
  await loadReleaseTransitionPanel({release_id:'R4'},[{antibiotic:'gentamicin'}]);
  assert.equal(byTag(root,'select').length,3);
  assert.equal(byTag(root,'input').length,1);
});


test('compact is the default; expand and collapse preserve cases, state counts and filter controls', async () => {
  const root=fakeBrowser();
  await loadReleaseTransitionPanel({release_id:'R4'},[{antibiotic:'gentamicin'}]);
  let chart=byTag(root,'svg')[0];
  assert.equal(chart.attributes.viewBox,'0 0 1100 132');
  assert.equal(byClass(root,'sankey-ribbon').length,8);
  assert.equal(byTag(root,'select').length,3);
  const button=byClass(root,'sankey-expand-button')[0];
  assert.equal(button.textContent,'Expand chart');
  assert.equal(button.attributes['aria-expanded'],'false');
  assert.equal(button.attributes['aria-controls'],'sankey-plot');
  await button.trigger('click');
  chart=byTag(root,'svg')[0];
  assert.equal(chart.attributes.viewBox,'0 0 1100 465');
  assert.equal(button.textContent,'Compact view');
  assert.equal(button.attributes['aria-expanded'],'true');
  assert.equal(byClass(root,'sankey-ribbon').length,8);
  assert.equal(byTag(root,'select').length,3);
  await button.trigger('click');
  assert.equal(byTag(root,'svg')[0].attributes.viewBox,'0 0 1100 132');
  assert.equal(button.attributes['aria-expanded'],'false');
  assert.equal(byClass(root,'sankey-ribbon').length,8);
});


test('Full-cohort view retains actual widths and adds high-contrast thin-route guides', async () => {
  const root=fakeBrowser();
  await loadReleaseTransitionPanel({release_id:'R4'},[{antibiotic:'gentamicin'}]);
  const chart=byTag(root,'svg')[0];
  assert.equal(chart.attributes['data-scale-denominator'],'41858');
  assert.equal(byClass(root,'sankey-ribbon').length,8);
  const thin=byClass(root,'sankey-ribbon').filter(p=>p.attributes['data-count']==='20');
  assert.equal(thin.length,3);
  assert.ok(thin.every(p=>Number(p.attributes['data-thickness'])<1),'all three changed flows are genuinely subpixel in full cohort');
  const traces=byClass(root,'sankey-change-trace');
  assert.equal(traces.length,3);
  assert.ok(traces.every(p=>p.attributes['stroke-width']==='2'),'visible guide stroke is independent of ribbon area');
  assert.ok(byClass(root,'sankey-change-hit').every(p=>p.attributes['stroke-width']==='16'),'transparent hit path remains pointer-accessible');
  assert.match(thin[0].attributes['aria-label'],/<0.1% of all comparable cases/);
});

test('Mouse hit targets highlight rare transition and open collapsible case list', async () => {
  const root=fakeBrowser();
  await loadReleaseTransitionPanel({release_id:'R4'},[{antibiotic:'gentamicin'}]);
  const hit=byClass(root,'sankey-change-hit')[0];
  await hit.trigger('mouseenter');
  assert.ok(byClass(root,'sankey-flow-focused').length>=1);
  await hit.trigger('click');
  for (let i=0;i<12 && !byClass(root,'sankey-case-list').length;i++) await new Promise(resolve=>setImmediate(resolve));
  const panel=byClass(root,'sankey-case-details')[0];
  assert.ok(panel);
  assert.equal(panel.tag,'details');
  assert.equal(panel.open,true);
  assert.ok(byTag(panel,'summary').length>=1);
  assert.equal(byClass(panel,'sankey-case-list').length,1);
  assert.match(panel.textContent,/Dossiers show the latest published state/);
});

test('Returning from changed-only restores full-cohort area denominator', async () => {
  const root=fakeBrowser();
  await loadReleaseTransitionPanel({release_id:'R4'},[{antibiotic:'gentamicin'}]);
  const toggle=byTag(root,'input')[0];
  toggle.checked=true;
  await toggle.trigger('change');
  assert.equal(byTag(root,'svg')[0].attributes['data-scale-denominator'],'60');
  toggle.checked=false;
  await toggle.trigger('change');
  assert.equal(byTag(root,'svg')[0].attributes['data-scale-denominator'],'41858');
  assert.equal(byClass(root,'sankey-ribbon').length,8);
});


test('Observed R3→R4 counts retain 41,858 total and magnify all four nonzero changed routes', () => {
  // Grounded in the user's R3→R4 transition count table; no data stored or mutated.
  const CR='CONCORDANT_RESISTANT', CS='CONCORDANT_SUSCEPTIBLE';
  const GP='DISCORDANT_GENOTYPE_POSITIVE_PHENOTYPE_S';
  const PR='DISCORDANT_PHENOTYPE_R_NO_MAPPED_GENOTYPE', U='UNRESOLVED';
  const rows=[[CR,CR,5423],[CS,CS,28783],[CS,U,26],[GP,GP,1285],
    [GP,U,9],[PR,PR,442],[U,CR,68],[U,PR,9],[U,U,5813]];
  const response={comparable_cases:41858,flows:rows.map(([before_state,after_state,count])=>({before_state,after_state,count}))};
  const geometry={top:23,height:90,gap:3};
  const full=sankeyModel(response,geometry);
  assert.equal(full.total,41858);
  assert.equal(countChanged(full),112);
  assert.equal(full.ribbons.filter(r=>r.changed).length,4);
  const changedFlows=response.flows.filter(r=>r.before_state!==r.after_state);
  const focused=sankeyModel({...response,comparable_cases:112,flows:changedFlows},geometry);
  assert.equal(focused.total,112);
  assert.deepEqual(focused.ribbons.map(r=>r.count).sort((a,b)=>b-a),[68,26,9,9]);
  const tinyFull=full.ribbons.filter(r=>r.changed && r.count===9);
  const tinyFocused=focused.ribbons.filter(r=>r.count===9);
  assert.equal(tinyFull.length,2);
  assert.equal(tinyFocused.length,2);
  assert.ok(tinyFull.every(r=>r.thickness<0.1));
  assert.ok(tinyFocused.every(r=>r.thickness>5));
});
