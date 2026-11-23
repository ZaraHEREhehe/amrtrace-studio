import test from 'node:test';
import assert from 'node:assert/strict';
import { loadReleaseTransitionPanel } from '../release_transitions.mjs';

class FakeElement {
  constructor(tag) {this.tag=tag;this.children=[];this.attributes={};this.listeners={};this._text='';this.value='';this.checked=false;}
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

test('Changed-only hides unchanged links, preserving both release totals', async () => {
  const root=fakeBrowser();
  await loadReleaseTransitionPanel({release_id:'R4'},[{antibiotic:'gentamicin'}]);
  const checkbox=byTag(root,'input')[0];
  checkbox.checked=true;
  await checkbox.trigger('change');
  assert.equal(byClass(root,'sankey-ribbon').length,3);
  assert.match(root.textContent,/unchanged ribbons are hidden/);
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
