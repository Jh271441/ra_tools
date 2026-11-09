"""Actual Review save/queue modules with synthetic HTTP APIs; no live writes."""
import base64
import copy
from email import policy
from email.parser import BytesParser
import json
import os
from pathlib import Path
import re
import runpy
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path(os.environ.get('REVIEW_SAVE_QA_OUTPUT', '/tmp/review-save-queue-744'))
fixture = runpy.run_path(str(ROOT / 'tests/combined_review_hydration_browser.py'))
PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j3ioAAAAASUVORK5CYII=')
setup = fixture['SETUP']
setup, replacements = re.subn(r'  api = async path => \{[\s\S]+?\n  \};', '  api = fixtureApi;', setup)
assert replacements == 1


def run():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    results, errors = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, **({'executable_path':os.environ['CHROMIUM_EXECUTABLE_PATH']} if os.environ.get('CHROMIUM_EXECUTABLE_PATH') else {}))

        def scenario(width=1440, lang='zh', theme='dark', selected='cn12', count=25, page_number=1, progress='pending'):
            page = browser.new_page(viewport={'width':width, 'height':1000})
            page.set_default_timeout(7000)
            page.on('pageerror', lambda error: errors.append(str(error)))
            backend = {'ids':[f'cn{i}' for i in range(1,count+1)], 'completed':set(), 'writes':0,
                       'hold_post':False, 'posts':[], 'hold_list':False, 'lists':[], 'context_failure':False,
                       'hold_saved_context':False, 'contexts':[],
                       'hold_next_context':False, 'saved_contexts':{},
                       'write_failure':False, 'requests':[]}

            def case(issue):
                model = {'id':101, 'model_run_id':'run', 'work_split_id':'task', 'campaign_id':'task', 'author':'alice',
                         'model_review_status':'completed', 'note':'Saved reason', 'created_at':'2026-01-01T00:00:00+08:00'}
                revision = {'id':201, 'author':'alice', 'expected_output':'误触发', 'tags':['u_turn'],
                            'is_excluded':False, 'rationale':'Saved rationale', 'created_at':model['created_at']}
                return {'issue_id':issue, 'gt_label':'无需协助', 'media_status':'unavailable', 'annotations':[model],
                        'predictions':[{'model_run_id':'run','model_label':'误触发'}],
                        'label_state':{'state':'resolved','expected_output':'误触发','sources':[{'revision_summaries':[revision]}]},
                        'review_assignment':{'assigned':True,'split_id':'task','purpose':'model_review',
                            'workflow_mode':'model_review_and_case_label','model_run_id':'run','mode':'single'}}

            def context(issue):
                if issue in backend['saved_contexts']:
                    return copy.deepcopy(backend['saved_contexts'][issue])
                data = case(issue)
                return {'assigned':True, 'issue':{'issue_id':issue}, 'campaign':{'id':'task','evaluation_run_id':'run'},
                        'case_revision':data['label_state']['sources'][0]['revision_summaries'][0],
                        'model_review':data['annotations'][0], 'case_revision_id':201, 'model_review_storage_id':101,
                        'label_state':data['label_state']}

            def commit(route):
                if backend['write_failure']:
                    route.fulfill(status=409,json={'detail':'Synthetic conflict'})
                    return
                request = route.request
                if 'multipart/form-data' in request.headers.get('content-type',''):
                    message = BytesParser(policy=policy.default).parsebytes(
                        ('Content-Type: '+request.headers['content-type']+'\r\n\r\n').encode()+request.post_data_buffer)
                    payload = json.loads(next(part.get_payload(decode=True) for part in message.iter_parts()
                                              if part.get_param('name',header='content-disposition') == 'payload'))
                else:
                    payload = request.post_data_json
                issue = urlsplit(request.url).path.split('/')[3]
                backend['writes'] += 1
                backend['completed'].add(issue)
                result = context(issue)
                result['model_review']['note'] = payload.get('reason','')
                result['model_review']['created_at'] = '2026-01-01T00:01:00+08:00'
                result['case_revision']['rationale'] = payload.get('rationale','')
                result['case_revision_id'] += backend['writes']
                result['case_revision']['id'] = result['case_revision_id']
                backend['saved_contexts'][issue] = copy.deepcopy(result)
                route.fulfill(json={'combined_review':result,'change_revision':backend['writes']})

            def route_api(route):
                request = route.request
                parsed = urlsplit(request.url)
                path, query = parsed.path, parse_qs(parsed.query)
                if '/api/' not in path:
                    route.fulfill(content_type='text/html',body=fixture['html'])
                    return
                backend['requests'].append({'method':request.method,'path':path,'query':query})
                if request.method == 'POST':
                    if backend['hold_post']:
                        backend['posts'].append(route)
                    else:
                        commit(route)
                    return
                if path.endswith('/combined-review-context'):
                    issue = path.split('/')[3]
                    if backend['hold_next_context']:
                        backend['hold_next_context']=False
                        backend['contexts'].append((route,context(issue)))
                    elif backend['hold_saved_context'] and issue in backend['completed']:
                        backend['contexts'].append(route)
                    elif backend['context_failure'] and issue in backend['completed']:
                        route.fulfill(status=500,json={'detail':'Synthetic context read failure'})
                    else:
                        route.fulfill(json={'context':context(issue)})
                    return
                if path in ['/api/cases','/api/cases/issue-ids']:
                    selected_progress = query.get('task_progress',[''])[0].split(',')
                    ids = [issue for issue in backend['ids'] if selected_progress != ['pending'] or issue not in backend['completed']]
                    if query.get('issue_ids'):
                        requested = set(query['issue_ids'][0].split(','))
                        ids = [issue for issue in ids if issue in requested]
                    if path.endswith('/issue-ids'):
                        route.fulfill(json={'issue_ids':ids})
                        return
                    number, size = int(query.get('page',['1'])[0]), int(query.get('page_size',['10'])[0])
                    data = {'total':len(ids),'items':[case(issue) for issue in ids[(number-1)*size:number*size]]}
                    if backend['hold_list']:
                        backend['hold_list'] = False
                        backend['lists'].append((route,copy.deepcopy(data)))
                    else:
                        route.fulfill(json=data)
                    return
                match = re.fullmatch('/api/cases/(cn[0-9]+)',path)
                if match:
                    route.fulfill(json=case(match[1]))
                elif '/media' in path:
                    route.fulfill(json={'assets':{},'camera':{},'media_status':'unavailable'})
                else:
                    route.fulfill(json={})

            page.route('http://review-save.test/**',route_api)
            page.goto(f'http://review-save.test/manual/review?issue={selected}&run=run&comparison=all&work_split=task&work_assignee=alice&task_progress={progress}&baselines=fixture&page={page_number}&page_size=10')
            for name in fixture['styles']:
                page.add_style_tag(content=(ROOT/'static'/name).read_text())
            for name in fixture['modules']:
                page.add_script_tag(content=(ROOT/'static/js'/name).read_text())
            page.evaluate('()=>{window.fixtureApi=api;}')
            configured = setup.replace("'cn1'",repr(selected)).replace('  state.selectedCase = fixtureData;', '''
                state.reviewTaskContext={id:'task',workflow_mode:'model_review_and_case_label',baseline_ids:['fixture']};
                state.reviewTaskProgress=PROGRESS;
                state.casePage=PAGE;state.casePageSize=10;state.caseTotal=COUNT;
                state.cases=Array.from({length:COUNT},(_,i)=>({issue_id:`cn${i+1}`})).slice((PAGE-1)*10,PAGE*10);
                state.reviewFormDirty=false;state.pendingReviewImages=[];
                state.backgroundCaseUploads=new Map();state.caseRationaleImages=new Map();
                refreshReviewDerivedData=()=>{};
                renderReviewProgressFilter();
                state.selectedCase = fixtureData;
            '''.replace('PROGRESS',json.dumps(progress.split(','))).replace('PAGE',str(page_number)).replace('COUNT',str(count)))
            page.evaluate(configured,{'catalog':fixture['catalog']})
            page.evaluate('([lang,theme])=>{applyUiLanguage(lang,{persist:false});applyColorTheme(theme,{persist:false});}',[lang,theme])
            page.wait_for_function("state.combinedReviewLoad?.status==='ready'")
            page.locator('#combinedCaseRationale').fill('Submitted rationale / 已提交说明')
            return page, backend, commit

        def saved(page, issue):
            try:
                page.wait_for_function('issue=>state.selectedId===issue&&state.selectedCase?.issue_id===issue&&!state.savingAnnotation&&state.combinedReviewLoad?.status===\'ready\'',arg=issue)
            except Exception:
                print('navigation failure',page.evaluate('''()=>({selected:state.selectedId,saving:state.savingAnnotation,
                    dirty:state.reviewFormDirty,context:state.combinedReviewLoad,cases:state.cases.map(item=>item.issue_id),
                    toast:document.querySelector('#toast').textContent,focus:document.activeElement?.id})'''),flush=True)
                raise
            assert page.locator('#detailPane').inner_text().find(issue)>=0
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')

        for width in ([] if os.environ.get('REVIEW_SAVE_ONLY_EXTRAS') else [320,390,1440]):
            for lang in ['zh','en']:
                for theme in ['dark','light']:
                    print('checking',width,lang,theme,flush=True)
                    page, backend, commit = scenario(width,lang,theme)
                    backend['hold_post']=True
                    backend['hold_saved_context']=True
                    page.locator('#caseRationaleImageInput').set_input_files({'name':'slow.png','mimeType':'image/png','buffer':PNG})
                    if width == 1440:
                        page.locator('#combinedCaseRationale').press('Enter')
                    else:
                        page.locator('#reviewSaveButton').click()
                    page.wait_for_function("state.backgroundCaseUploads.size===1&&!state.savingAnnotation")
                    assert len(backend['posts'])==1 and backend['writes']==0
                    assert page.locator('.case-upload-progress').is_visible()
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    if (width,lang,theme) in [(320,'en','light'),(1440,'zh','dark')]:
                        page.screenshot(path=str(OUTPUT/f'upload-{width}-{lang}-{theme}.png'),full_page=True)
                    commit(backend['posts'].pop())
                    saved(page,'cn13')
                    assert page.evaluate("readReviewDraft('cn12','run','task','alice')") is None
                    assert backend['writes']==1
                    assert page.evaluate('state.caseTotal')==24
                    assert page.evaluate('state.casePage')==2
                    assert page.evaluate("state.cases.every(item=>item.issue_id!=='cn12')")
                    query = parse_qs(urlsplit(page.url).query)
                    for key,value in [('task_progress','pending'),('work_split','task'),('work_assignee','alice'),('baselines','fixture'),('run','run'),('page_size','10')]:
                        assert query.get(key)==[value],(key,query)
                    assert query['issue']==['cn13'] and query['page']==['2']
                    if (width,lang,theme) in [(320,'en','light'),(1440,'zh','dark')]:
                        page.screenshot(path=str(OUTPUT/f'queue-{width}-{lang}-{theme}.png'),full_page=True)
                    results.append({'width':width,'language':lang,'theme':theme,'deep_link_next':'cn13','passed':True})
                    page.close()

        extras=[]
        for config, expected, name in [
            ({'selected':'cn21','count':21,'page_number':3},'cn20','last-page fallback'),
            ({'progress':'pending,completed'},'cn12','all progress retains current'),
        ]:
            page,backend,_=scenario(**config);page.locator('#reviewSaveButton').click();saved(page,expected)
            assert backend['writes']==1
            extras.append(name);page.close()

        page,backend,_=scenario(selected='cn1',count=1)
        page.locator('#reviewSaveButton').click()
        page.wait_for_function("!state.selectedId&&!state.savingAnnotation")
        assert page.locator('#reviewGalleryView').is_visible();assert page.evaluate('state.caseTotal')==0
        extras.append('empty filter returns to gallery');page.close()

        page,backend,_=scenario(selected='cn2');backend['context_failure']=True
        page.locator('#combinedCaseRationale').press('Enter');saved(page,'cn3')
        assert backend['writes']==1;extras.append('post-commit context failure still advances');page.close()

        page,backend,_=scenario(selected='cn2');backend['write_failure']=True
        page.locator('#reviewSaveButton').click();page.wait_for_function('!state.savingAnnotation')
        assert page.evaluate('state.selectedId')=='cn2' and backend['writes']==0
        assert 'Submitted rationale' in page.locator('#combinedCaseRationale').input_value()
        extras.append('conflict preserves draft and selection');page.close()

        page,backend,commit=scenario(selected='cn2');backend['hold_post']=True
        page.locator('#reviewSaveButton').click();page.wait_for_timeout(80)
        assert len(backend['posts'])==1
        page.locator('#combinedCaseRationale').fill('Typed during save / 新草稿')
        commit(backend['posts'].pop());page.wait_for_function('!state.savingAnnotation')
        assert page.evaluate('state.selectedId')=='cn2'
        assert page.locator('#combinedCaseRationale').input_value()=='Typed during save / 新草稿'
        assert page.evaluate('state.reviewFormDirty');extras.append('new draft during save prevents navigation');page.close()

        page,backend,_=scenario(selected='cn2');backend['hold_list']=True
        page.evaluate('window.oldQueueRead=loadCases({keepSelection:true})');page.wait_for_timeout(80)
        assert len(backend['lists'])==1
        page.locator('#reviewSaveButton').click();saved(page,'cn3')
        old_route,old_data=backend['lists'].pop();old_route.fulfill(json=old_data)
        page.evaluate('oldQueueRead')
        assert page.evaluate("state.cases.every(item=>item.issue_id!=='cn2')")
        extras.append('older in-flight list cannot supply or overwrite saved queue');page.close()

        page,backend,_=scenario(selected='cn2')
        png=PNG
        page.locator('#caseRationaleImageInput').set_input_files({'name':'fixture.png','mimeType':'image/png','buffer':png})
        page.locator('#reviewSaveButton').click();saved(page,'cn3')
        assert backend['writes']==1
        assert page.evaluate('state.backgroundCaseUploads.size')==0
        extras.append('background image submission reconciles same Issue');page.close()

        # A slow image POST allows other collaboration reads while Enter keeps
        # focus in the rationale. A committed response must still retire that
        # submitted draft and advance after the textarea's native change event.
        page,backend,commit=scenario(selected='cn2');backend['hold_post']=True
        backend['hold_saved_context']=True
        page.locator('#caseRationaleImageInput').set_input_files({'name':'slow.png','mimeType':'image/png','buffer':png})
        page.locator('#combinedCaseRationale').press('Enter')
        page.wait_for_function("state.backgroundCaseUploads.size===1&&!state.savingAnnotation")
        assert len(backend['posts'])==1
        page.wait_for_timeout(800)
        assert backend['writes']==0
        commit(backend['posts'].pop())
        saved(page,'cn3')
        assert backend['writes']==1
        assert page.evaluate("readReviewDraft('cn2','run','task','alice')") is None, 'native blur must not restore the committed draft'
        extras.append('slow image Enter submit retires draft and advances');page.close()

        # A confirmed plain-text save also must not await the old Issue's context.
        page,backend,_=scenario(selected='cn2');backend['hold_saved_context']=True
        page.locator('#combinedCaseRationale').press('Enter');saved(page,'cn3')
        assert backend['writes']==1
        extras.append('plain-text save advances before old context read');page.close()

        # Returning to an uploading Issue may leave an older context GET in
        # flight. A retained Issue must obtain new head IDs independently.
        page,backend,commit=scenario(selected='cn2',progress='pending,completed');backend['hold_post']=True
        page.locator('#caseRationaleImageInput').set_input_files({'name':'slow.png','mimeType':'image/png','buffer':png})
        page.locator('#reviewSaveButton').click()
        page.wait_for_function("state.backgroundCaseUploads.size===1&&!state.savingAnnotation")
        backend['hold_next_context']=True
        page.evaluate('()=>{window.oldContextRead=loadCombinedReviewContext(state.selectedCase);}')
        page.wait_for_timeout(80);assert len(backend['contexts'])==1
        commit(backend['posts'].pop())
        page.wait_for_function("state.backgroundCaseUploads.size===0&&state.combinedReviewLoad?.status==='ready'&&state.combinedReviewContext?.case_revision_id===202")
        old_route,old_context=backend['contexts'].pop();old_route.fulfill(json={'context':old_context})
        page.evaluate('oldContextRead')
        assert page.evaluate('state.selectedId')=='cn2' and page.evaluate('state.combinedReviewContext.case_revision_id')==202
        extras.append('retained Issue gets fresh head IDs without joining pre-commit context');page.close()

        page,backend,_=scenario(320,'en','light',selected='cn2');backend['write_failure']=True
        page.locator('#caseRationaleImageInput').set_input_files({'name':'retained.png','mimeType':'image/png','buffer':png})
        page.locator('#reviewSaveButton').click()
        page.wait_for_function("[...state.backgroundCaseUploads.values()][0]?.status==='failed'")
        assert backend['writes']==0 and page.evaluate('state.selectedId')=='cn2'
        assert page.locator('[data-refresh-case-upload]').is_visible()
        assert page.evaluate('caseRationalePendingImages().length')==1
        assert 'Submitted rationale' in page.locator('#combinedCaseRationale').input_value()
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.screenshot(path=str(OUTPUT/'upload-conflict-320-en-light.png'),full_page=True)
        page.evaluate("applyUiLanguage('zh',{persist:false})")
        assert page.evaluate('state.selectedId')=='cn2' and page.evaluate('caseRationalePendingImages().length')==1
        assert 'Submitted rationale' in page.locator('#combinedCaseRationale').input_value()
        extras.append('mobile image conflict and locale switch preserve images and draft');page.close()

        page,backend,commit=scenario(selected='cn2');backend['hold_post']=True
        page.locator('#caseRationaleImageInput').set_input_files({'name':'slow.png','mimeType':'image/png','buffer':png})
        page.locator('#combinedCaseRationale').press('Enter')
        page.wait_for_function("state.backgroundCaseUploads.size===1&&!state.savingAnnotation")
        page.locator('#combinedCaseRationale').dispatch_event('compositionstart')
        commit(backend['posts'].pop())
        page.wait_for_function("state.backgroundCaseUploads.size===0&&state.combinedReviewLoad?.status==='ready'")
        assert page.evaluate('state.selectedId')=='cn2'
        assert page.evaluate('state.reviewFormDirty')
        assert page.locator('#combinedCaseRationale').evaluate("el=>document.activeElement===el&&el.dataset.imeComposing==='1'")
        extras.append('IME preedit during upload retains focus and prevents navigation');page.close()

        assert not errors,errors
        report={'browser':browser.version,'fixture':'actual shell/modules and API client, synthetic HTTP only',
                'combinations':results,'additional':extras,'page_errors':errors}
        (OUTPUT/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
        print(json.dumps(report,ensure_ascii=False))
        browser.close()


if __name__ == '__main__':
    run()
