import test from 'node:test';
import assert from 'node:assert/strict';
import { restoreFocus } from '../ui.mjs';

const element=(attrs={},text='查看',disabled=false)=>({
  tagName:'BUTTON',textContent:text,disabled,
  attributes:Object.entries(attrs).map(([name,value])=>({name,value})),
  getAttribute(name){return attrs[name]??null;},
  focus(){this.focused=true;},
});
const root=elements=>({contains:el=>elements.includes(el),querySelectorAll:()=>elements});

test('FINDING-004: dialog focus survives a replaced row without jumping to another record',()=>{
  const old=element({'data-action':'evidence','data-attempt':'a2'});
  const first=element({'data-action':'evidence','data-attempt':'a1'});
  const replacement=element({'data-action':'evidence','data-attempt':'a2'});
  assert.equal(restoreFocus(root([first,replacement]),old),true);
  assert.equal(replacement.focused,true);
  assert.equal(first.focused,undefined);
  assert.equal(restoreFocus(root([first]),old),false);
  assert.equal(restoreFocus(root([]),null),false);
  assert.equal(restoreFocus(root([old]),old),true);
  const disabled=element({'data-action':'evidence','data-attempt':'a2'},'查看',true);
  assert.equal(restoreFocus(root([disabled]),old),false);
  const plain=element({},'取消');
  const sameLabel=element({},'取消');
  assert.equal(restoreFocus(root([element({},'保存'),sameLabel]),plain),true);
  assert.equal(sameLabel.focused,true);
});
