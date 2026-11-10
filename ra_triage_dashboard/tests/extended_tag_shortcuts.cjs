const assert=require('node:assert/strict'), fs=require('node:fs'), vm=require('node:vm'), path=require('node:path');
const s={console,Map,Set,CSS:{escape:String},Event:class{constructor(type,options){this.type=type;this.bubbles=options.bubbles;}}};
vm.createContext(s);
for(const name of ['text-input.js','review-tags.js']) vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/js',name),'utf8'),s);
const keys=['1','2','3','4','5','6','7','8','9','0','-','='];
const symbols='!@#$%^&*()_+';
for(let index=0;index<keys.length;index++) {
  const key=keys[index],code=index<10?'Digit'+key:index===10?'Minus':'Equal';
  assert.equal(s.reviewDropdownOptionShortcut({key,code}),key);
  assert.equal(s.reviewDropdownOptionShortcut({key:symbols[index],code,shiftKey:true}),'Shift+'+key);
  assert.equal(s.reviewDropdownOptionShortcut({key:symbols[index],shiftKey:true}),'Shift+'+key);
}
assert.equal(s.reviewDropdownOptionShortcut({key:'é',code:'Digit2'}),'2','physical number row is layout independent');
for(const guard of [{ctrlKey:true},{metaKey:true},{altKey:true},{repeat:true},{isComposing:true},{keyCode:229}]) {
  assert.equal(s.reviewDropdownOptionShortcut({key:'!',code:'Digit1',shiftKey:true,...guard}),'');
}
for(const key of ['','v','c',' ','ArrowLeft','ArrowRight','[',']','Escape','Enter']) assert.equal(s.reviewDropdownOptionShortcut({key,shiftKey:true}),'');
const input={checked:false,disabled:false,closest:()=>null,dispatchEvent(){this.changes=(this.changes||0)+1;}};
const selectors=[];
let open=true;
s.activeReviewChromeRoot=()=>({querySelector:()=>open?{querySelector:selector=>{selectors.push(selector);return selector.includes('Shift+1')?input:null;}}:null});
assert(s.toggleOpenReviewDropdownOption('Shift+1'));assert(input.checked);assert.equal(input.changes,1);
assert(!s.toggleOpenReviewDropdownOption('1'));assert.equal(input.changes,1);
input.closest=()=>({hidden:true});assert(!s.toggleOpenReviewDropdownOption('Shift+1'));input.closest=()=>null;
input.disabled=true;assert(!s.toggleOpenReviewDropdownOption('Shift+1'));input.disabled=false;
open=false;assert(!s.toggleOpenReviewDropdownOption('Shift+1'));assert.equal(input.changes,1);
console.log('Extended tag shortcuts: 24 number-row combinations, layouts/IME/modifiers, exact option, hidden/disabled and closed scope passed');
