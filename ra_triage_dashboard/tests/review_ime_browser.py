import re,json,pathlib
from playwright.sync_api import sync_playwright
root=pathlib.Path(__file__).resolve().parents[1]/'static'
original=(root/'index.html').read_text()
styles=json.loads('['+re.search(r'const stylesheetPaths = \[([\s\S]*?)\];',original)[1].rstrip().rstrip(',')+']')
html=re.sub(r'<script\b[^>]*>[\s\S]*?</script>','',original).replace('{{RA_TRIAGE_BASE_PATH}}','')
modules=[s.strip() for s in (root/'js/MANIFEST').read_text().splitlines() if s.strip() and not s.startswith('#') and s!='bind-bootstrap.js']
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True)
 page=browser.new_page(viewport={'width':1440,'height':1000})
 errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
 page.route('http://ime.test/**',lambda route:route.fulfill(status=200,content_type='text/html',body=html))
 page.goto('http://ime.test/manual/review')
 for f in styles: page.add_style_tag(content=(root/f).read_text())
 for f in modules: page.add_script_tag(content=(root/'js'/f).read_text())
 page.evaluate('''() => {
  state.session={username:'alice',verified:true,access_role:'writer',identity_pending:false};
  state.activePage='review';state.selectedId='cn1';state.selectedRunId='run';state.reviewWorkSplitId='task';
  state.config={missing_evidence_catalog:[],review_tag_catalog:[],review_notifications:{enabled:true}};
  state.mentionUsers=[{username:'alice',display_name:'Alice',enabled:true}];
  const data={issue_id:'cn1',media_status:'ready',annotations:[],review_assignment:{assigned:true,split_id:'task',purpose:'model_review',workflow_mode:'model_review_and_case_label',model_run_id:'run'}};
  state.selectedCase=data;
  api=async path=>({context:{assigned:true,issue:{issue_id:'cn1'},campaign:{id:'task',evaluation_run_id:'run'},case_revision:{rationale:''}}});
  setReviewView('cn1');renderReview(data);bindMobileWorkbench();
  window.submits=0;document.querySelector('#annotationForm').removeEventListener('submit',saveAnnotation);document.querySelector('#annotationForm').addEventListener('submit',e=>{e.preventDefault();window.submits++},true);
  saveAnnotation=()=>{};
 }''')
 page.wait_for_function("state.combinedReviewLoad?.status === 'ready'")
 results=[]
 cdp=page.context.new_cdp_session(page)
 for width in [320,390,1440]:
  page.set_viewport_size({'width':width,'height':1000})
  for lang in ['zh','en']:
   for theme in ['dark','light']:
    page.evaluate("([lang,theme])=>{applyUiLanguage(lang);document.documentElement.dataset.colorTheme=theme}",[lang,theme])
    for field,rootid in [('annotationNote','reviewMentionComposer'),('combinedCaseRationale','combinedCaseMentionComposer')]:
     box=page.locator('#'+field);box.scroll_into_view_if_needed();box.fill('@a')
     page.wait_for_function("id=>!document.getElementById(id).hidden",arg=rootid)
     before=page.evaluate("id=>{window.entryNode=document.getElementById(id);return submits}",field)
     cdp.send('Input.imeSetComposition',{'text':'ni','selectionStart':2,'selectionEnd':2})
     assert box.get_attribute('data-ime-composing')=='1',(width,lang,theme,field,'compositionstart')
     assert page.locator('#'+rootid+' .review-mention-popover').is_hidden(),(width,field,'mention popup must yield')
     check=page.evaluate("""async () => {
      const node=entryNode, value=node.value;
      for(const key of ['Enter','ArrowDown','ArrowUp','Escape','Tab']){
       const e=new KeyboardEvent('keydown',{key,bubbles:true,cancelable:true,keyCode:229});
       node.dispatchEvent(e);
       if(e.defaultPrevented||document.activeElement!==node||node.value!==value)return false;
      }
      state.reviewFormDirty=false;
      await refreshReviewCorePreservingMedia();
      return node===document.activeElement && node===document.getElementById(node.id);
     }""")
     assert check,(width,lang,theme,field,'IME key/focus protection')
     cdp.send('Input.insertText',{'text':'你'})
     assert box.input_value()=='@a你',(width,lang,theme,field,box.input_value())
     assert box.get_attribute('data-ime-composing') is None
     assert page.evaluate('submits')==before
     # A fresh normal Enter selects a mention; a separate Enter preserves existing save/newline behavior.
     box.fill('@a');page.keyboard.press('Enter')
     assert box.input_value()=='@alice ',(width,field,'ordinary mention selection')
     assert page.evaluate('submits')==before
     box.fill('中文输入正常 / English rationale with a deliberately long sentence')
     page.keyboard.press('Shift+Enter')
     assert '\n' in box.input_value()
     page.keyboard.press('Enter')
     assert page.evaluate('submits')==before+(1 if width==1440 else 0),(width,field,'Enter semantics')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'),(width,lang,theme,'horizontal overflow')
    results.append({'width':width,'language':lang,'theme':theme,'fields':2,'passed':True})
    if (width,lang,theme) in [(320,'en','light'),(1440,'zh','dark')]:
     page.evaluate('scrollTo(0,0)');page.screenshot(path=f'/tmp/ra-review-ime-{width}-{lang}-{theme}.png',full_page=True)
 assert not errors,errors
 print(json.dumps({'browser':browser.version,'combinations':results,'errors':errors},ensure_ascii=False))
 pathlib.Path('/tmp/ra-review-ime-browser-results.json').write_text(json.dumps({'browser':browser.version,'combinations':results,'errors':errors},ensure_ascii=False,indent=2))
 browser.close()

