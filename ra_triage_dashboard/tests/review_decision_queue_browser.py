"""Actual Review decision UI with synthetic APIs; never writes live labels."""
import json
import os
from pathlib import Path
import re
import runpy

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path(os.environ.get('REVIEW_DECISION_QA_OUTPUT', '/tmp/review-decision-queue-780'))
fixture = runpy.run_path(str(ROOT / 'tests/combined_review_hydration_browser.py'))
setup, replacements = re.subn(r'  api = async path => \{[\s\S]+?\n  \};', '  api = fixtureApi;', fixture['SETUP'])
assert replacements == 1
setup = setup.replace('  state.selectedCase = fixtureData;', r'''
  const peer={...revision,id:202,author:'bob',expected_output:'需协助',tags:[]};
  fixtureData.label_state={state:'conflict',expected_output:'',source_fingerprint:'synthetic-sources',
    sources:[{label_case_id:'labels',source_revision_ids:[201,202],revision_summaries:[revision,peer]}]};
  fixtureData.label_cases=[{id:'labels',revisions:[revision,peer]}];
  fixtureData.exclusion_summary={is_excluded:false};
  fixtureContext.label_state=fixtureData.label_state;
  state.casePage=1;state.casePageSize=10;state.caseTotal=qa.ids.length;
  state.cases=qa.ids.slice(0,10).map(issue_id=>({...structuredClone(fixtureData),issue_id}));
  state.reviewTaskProgress=[];state.reviewFormDirty=false;state.pendingReviewImages=[];
  state.reviewComparisonStatus='all';state.reviewTaskContext={id:'task',workflow_mode:'model_review_and_case_label'};
  refreshReviewDerivedData=()=>{};
  renderMultiFilter($('#sharedLabelStateFilter'),{groups:labelGtFilterGroups(),selected:qa.conflict?['conflict']:[]});
  state.selectedCase = fixtureData;
''')

API = r'''({count, conflict})=>{
  window.qa={ids:Array.from({length:count},(_,i)=>`cn${i+1}`),resolved:new Set(),posts:[],calls:[],conflict,holdContext:false};
  function data(issue){
    const value={...structuredClone(fixtureData),issue_id:issue};
    if(qa.resolved.has(issue))value.label_state={...value.label_state,state:'resolved',expected_output:'误触发'};
    return value;
  }
  window.fixtureApi=async(url,options={})=>{
    const u=new URL(url,location.origin),p=u.pathname;
    qa.calls.push({path:p,query:u.search,method:options.method||'GET'});
    if(options.method==='POST'){
      if(!/^\/api\/labeling\/issues\/cn\d+\/decisions$/.test(p))throw Error('Unexpected synthetic write');
      const payload=JSON.parse(options.body);
      if(!payload.full_result || payload.model_run_id || payload.campaign_id)throw Error('Invalid decision binding');
      qa.posts.push(payload);
      if(qa.failPost)throw Object.assign(new Error('Synthetic decision conflict'),{status:409});
      qa.resolved.add(p.split('/')[4]);return {decision:{id:900}};
    }
    if(p==='/api/cases'||p==='/api/cases/issue-ids'){
      if(qa.failQueue&&qa.posts.length)throw Error('Synthetic queue failure');
      const ids=qa.ids.filter(id=>u.searchParams.get('label_state')!=='conflict'||!qa.resolved.has(id));
      if(p.endsWith('/issue-ids'))return {issue_ids:ids};
      const page=Number(u.searchParams.get('page')||1),size=Number(u.searchParams.get('page_size')||10);
      return {total:ids.length,items:ids.slice((page-1)*size,page*size).map(data)};
    }
    if(p.endsWith('/combined-review-context')){
      const issue=p.split('/')[3];
      if(qa.holdContext&&qa.resolved.has(issue))return new Promise(()=>{});
      return {context:{...structuredClone(fixtureContext),issue:{issue_id:issue},label_state:data(issue).label_state}};
    }
    if(/^\/api\/(labeling\/)?cases\/cn\d+$/.test(p))return data(p.split('/').at(-1));
    if(p.includes('/media'))return {assets:{},camera:{},media_status:'unavailable'};
    return {};
  };
}'''


def run():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    results, errors = [], []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)

        def scenario(width=1440, language='zh', theme='dark', count=25, selected='cn12', conflict=True, dirty=False, failure=''):
            page = browser.new_page(viewport={'width': width, 'height': 1000})
            page.set_default_timeout(7000)
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.route('http://review-decision.test/**', lambda route: route.fulfill(content_type='text/html', body=fixture['html']))
            page.goto('http://review-decision.test/manual/review?issue='+selected+'&run=run&comparison=all&baselines=fixture'
                      + ('&label_state=conflict' if conflict else ''))
            for name in fixture['styles']:
                page.add_style_tag(content=(ROOT/'static'/name).read_text())
            for name in fixture['modules']:
                page.add_script_tag(content=(ROOT/'static/js'/name).read_text())
            page.evaluate(API, {'count':count,'conflict':conflict})
            page.evaluate(setup.replace("'cn1'", repr(selected)), {'catalog':fixture['catalog']})
            page.evaluate('([language,theme])=>{applyUiLanguage(language,{persist:false});applyColorTheme(theme,{persist:false});}', [language,theme])
            page.wait_for_function("state.combinedReviewLoad?.status==='ready'")
            if dirty:
                page.locator('#annotationNote').fill('Unsaved model draft / 未保存草稿')
                page.evaluate('qa.holdContext=true;window.originalForm=document.querySelector("#annotationForm");window.originalMedia=document.querySelector("#detailHeroMedia")')
            page.locator('#reviewSharedLabelState [data-open-shared-label-state]').click()
            page.locator('#caseLabelDecisionDialog [data-adopt-decision="201"]').click()
            page.locator('#caseDecisionConfirmExclusion').check()
            if (width,language,theme)==(320,'en','light'):
                page.evaluate("applyUiLanguage('zh',{persist:false});applyUiLanguage('en',{persist:false})")
                assert page.locator('#caseDecisionConfirmExclusion').is_checked()
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            if (width,language,theme)==(320,'en','light'):
                page.screenshot(path=str(OUTPUT/'decision-320-en-light.png'),full_page=True)
            page.evaluate("failure=>{qa.failPost=failure==='post';qa.failQueue=failure==='queue';}",failure)
            page.locator('#caseLabelingForm button[type="submit"]').click()
            return page

        for width in [320,390,1440]:
            for language in ['zh','en']:
                for theme in ['dark','light']:
                    page=scenario(width,language,theme)
                    page.wait_for_function("state.selectedId==='cn13'&&state.selectedCase?.issue_id==='cn13'")
                    assert page.evaluate('state.caseTotal')==24
                    assert not page.evaluate("state.cases.some(item=>item.issue_id==='cn12')")
                    assert page.evaluate('state.casePage')==2
                    assert page.evaluate('state.casePageSize')==10
                    assert len(page.evaluate('qa.posts'))==1
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    assert 'label_state=conflict' in page.url and 'run=run' in page.url and 'page=2' in page.url
                    results.append({'width':width,'language':language,'theme':theme,'passed':True})
                    page.close()

        for name, options, expected in [
            ('last Issue', {'count':3,'selected':'cn3'}, 'cn2'),
            ('empty queue', {'count':1,'selected':'cn1'}, ''),
            ('all-state filter', {'selected':'cn2','conflict':False}, 'cn2'),
            ('ordinary draft and slow context', {'selected':'cn2','dirty':True}, 'cn2'),
        ]:
            page=scenario(**options)
            page.wait_for_function('expected=>qa.posts.length===1&&state.selectedId===expected&&!caseLabelDecisionUi.saving',arg=expected)
            if options.get('dirty'):
                page.wait_for_function("state.caseTotal===24&&!state.cases.some(item=>item.issue_id==='cn2')")
                assert page.locator('#annotationNote').input_value()=='Unsaved model draft / 未保存草稿'
                assert page.evaluate('document.querySelector("#annotationForm")===originalForm&&document.querySelector("#detailHeroMedia")===originalMedia')
            if not options.get('conflict',True):
                page.wait_for_function("state.selectedCase.label_state.state==='resolved'")
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            results.append({'scenario':name,'passed':True})
            page.close()
        for failure in ['post','queue']:
            page=scenario(width=320,language='en',theme='light',selected='cn2',failure=failure)
            if failure=='post':
                page.wait_for_function("Boolean(caseLabelDecisionUi.editor)&&document.querySelector('#caseDecisionEditorError').textContent.length>0&&!caseLabelDecisionUi.saving")
                assert page.locator('#caseLabelingForm button[type="submit"]').is_enabled()
                assert page.evaluate('state.caseTotal')==25
            else:
                page.wait_for_function('state.reviewQueueStale&&!caseLabelDecisionUi.editor')
                assert 'Decision saved, but the filtered queue could not refresh' in page.locator('#toast').inner_text()
            assert page.evaluate('state.selectedId')=='cn2'
            assert len(page.evaluate('qa.posts'))==1
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            results.append({'scenario':failure+' failure','passed':True})
            page.close()
        assert not errors, errors
        report={'browser':browser.version,'fixture':'actual shell/modules/styles and synthetic APIs',
                'results':results,'page_errors':errors}
        (OUTPUT/'browser-results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
        print(json.dumps(report,ensure_ascii=False))
        browser.close()


if __name__=='__main__':
    run()
