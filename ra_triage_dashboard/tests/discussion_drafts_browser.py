"""Discussion draft lifecycle using real DOM/storage/API client and synthetic HTTP."""
import base64
from email import policy
from email.parser import BytesParser
import json
import os
from pathlib import Path
import runpy
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
fixture=runpy.run_path(str(ROOT/'tests/combined_review_hydration_browser.py'))
OUTPUT=Path(os.environ.get('DISCUSSION_DRAFT_QA_OUTPUT','/tmp/discussion-draft-qa'))
PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j3ioAAAAASUVORK5CYII=')


def run():
    OUTPUT.mkdir(parents=True,exist_ok=True)
    errors,results=[],[]
    with sync_playwright() as p:
        options={'executable_path':os.environ['CHROMIUM_EXECUTABLE_PATH']} if os.environ.get('CHROMIUM_EXECUTABLE_PATH') else {}
        browser=p.chromium.launch(headless=True,**options)

        def initialize(page,actor='alice',issue='cn1',surface='review',language='zh',theme='dark'):
            for name in fixture['styles']:page.add_style_tag(content=(ROOT/'static'/name).read_text())
            for name in fixture['modules']:page.add_script_tag(content=(ROOT/'static/js'/name).read_text())
            page.evaluate('''({actor,issue,surface,language,theme})=>{
              state.activePage=surface;state.selectedId=issue;state.selectedRunId='run';state.reviewWorkSplitId='task';
              state.session={username:actor,verified:true,can_write:true,can_annotate_intent:true,access_role:'writer'};
              state.config={review_attachment_limits:{max_count:4,max_bytes_each:8388608,max_bytes_total:25165824}};
              state.mentionUsers=[{username:'bob',display_name:'Bob',enabled:true}];
              state.caseLabeling={issueId:issue,caseData:{issue_id:issue}};
              state.uiLanguage=language;document.documentElement.dataset.uiLang=language;
              document.documentElement.dataset.colorTheme=theme;document.documentElement.dataset.sessionPending='false';
              document.body.dataset.activePage=surface;
              $('#analysisDiscussionForm').addEventListener('submit',saveAnalysisDiscussion);
              $('#analysisDiscussionDialog').addEventListener('close',closeAnalysisDiscussion);
              document.querySelectorAll('[data-close="analysisDiscussionDialog"]').forEach(b=>b.addEventListener('click',()=>$('#analysisDiscussionDialog').close()));
              bindAnalysisDiscussionEditor();bindAnalysisDiscussionEnterSubmit();applyDomI18n(document);
            }''',dict(actor=actor,issue=issue,surface=surface,language=language,theme=theme))

        def scenario(width=1440,language='zh',theme='dark'):
            page=browser.new_page(viewport={'width':width,'height':1000})
            page.set_default_timeout(7000);page.on('pageerror',lambda error:errors.append(str(error)))
            backend={'posts':[],'records':{},'held':[],'hold':False,'fail':False,'deleted':False}
            def commit(route):
                request=route.request;issue=urlsplit(request.url).path.split('/')[3]
                if 'multipart/form-data' in request.headers.get('content-type',''):
                    parsed=BytesParser(policy=policy.default).parsebytes(('Content-Type: '+request.headers['content-type']+'\r\n\r\n').encode()+request.post_data_buffer)
                    payload=json.loads(next(part.get_payload(decode=True) for part in parsed.iter_parts() if part.get_param('name',header='content-disposition')=='payload'))
                else:payload=request.post_data_json
                key=request.headers.get('idempotency-key','')
                backend['posts'].append({'key':key,'payload':payload,'issue':issue})
                if backend['fail']:route.fulfill(status=503,json={'detail':'Synthetic offline'});return
                comment=backend['records'].setdefault((issue,key),{'id':200+len(backend['records']),'issue_id':issue,'body':payload['body'],'author':'alice','author_verified':True,'discussion_channel':'case','created_at':'2026-11-13T10:00:00+08:00','reply_to_id':payload.get('reply_to_id'),'attachments':[]})
                route.fulfill(json={'comment':comment,'comment_count':len(backend['records'])+1})
            def routes(route):
                request=route.request;path=urlsplit(request.url).path
                if request.method=='POST':
                    if backend['hold']:backend['held'].append(route)
                    else:commit(route)
                elif '/discussion-submissions/' in path:
                    issue=path.split('/')[3];record=backend['records'].get((issue,path.split('/')[-1]))
                    route.fulfill(json={'comment':record}) if record else route.fulfill(status=404,json={'detail':'Not found'})
                elif path.endswith('/discussion'):
                    issue=path.split('/')[3]
                    comments=[{'id':117,'author':'bob','author_verified':True,'body':'Parent comment','discussion_channel':'case','created_at':'2026-11-13T09:00:00+08:00','deleted':backend['deleted']}]
                    comments.extend(v for (i,k),v in backend['records'].items() if i==issue)
                    route.fulfill(json={'comments':comments,'count':len(comments)})
                elif '/api/' in path:route.fulfill(json={})
                else:route.fulfill(content_type='text/html',body=fixture['html'])
            page.route('http://draft.test/**',routes)
            page.goto('http://draft.test/manual/review?issue=cn1&run=run&work_split=task')
            initialize(page,language=language,theme=theme)
            return page,backend,commit

        def open_(page,issue='cn1'):
            page.evaluate('issue=>openAnalysisDiscussion(issue)',issue)
        def close(page):
            page.evaluate('window.closedDraft=state.analysisDiscussion')
            page.locator('[data-close="analysisDiscussionDialog"]').first.click()
            page.wait_for_function('state.analysisDiscussion===null')
            page.evaluate('closedDraft.draftImageWrite')
        def switch(page,issue='cn1',actor='alice',surface='review'):
            page.evaluate('''({issue,actor,surface})=>{
              history.replaceState(null,'',`/manual/${surface==='review'?'review':'case-labeling'}?issue=${issue}&run=run`);
              state.activePage=surface;state.selectedId=issue;state.session.username=actor;
            }''',dict(issue=issue,actor=actor,surface=surface))

        for width in [320,390,1440]:
            for lang in ['zh','en']:
                for theme in ['dark','light']:
                    page,backend,_=scenario(width,lang,theme);open_(page)
                    page.evaluate('beginAnalysisDiscussionReply(117)')
                    body='@bob Half written / 写到一半\nKeep this draft.'
                    page.locator('#analysisDiscussionNote').fill(body)
                    page.locator('#analysisDiscussionImageInput').set_input_files({'name':'draft.png','mimeType':'image/png','buffer':PNG})
                    expected=page.locator('#analysisDiscussionNote').input_value()
                    page.locator('#analysisDiscussionNote').evaluate('el=>el.setSelectionRange(4,12)')
                    close(page);open_(page)
                    assert page.locator('#analysisDiscussionNote').input_value()==expected
                    assert page.evaluate('state.analysisDiscussion.replyTo.id')==117
                    assert page.evaluate('state.analysisDiscussion.pendingImages[0].file.size')==len(PNG)
                    assert page.evaluate("document.querySelector('#analysisDiscussionNote').selectionStart")==4
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    if (width,lang,theme) in [(320,'en','light'),(1440,'zh','dark')]:page.screenshot(path=str(OUTPUT/f'restored-{width}-{lang}-{theme}.png'))
                    close(page)
                    page.reload();initialize(page,language=lang,theme=theme);open_(page)
                    assert page.locator('#analysisDiscussionNote').input_value()==expected
                    assert page.evaluate('state.analysisDiscussion.pendingImages[0].file.size')==len(PNG)
                    assert page.locator('#analysisDiscussionSubmit').is_enabled()
                    results.append({'width':width,'language':lang,'theme':theme,'close_and_reload':True})
                    page.close()

        page,backend,commit=scenario();open_(page)
        page.locator('#analysisDiscussionNote').fill('Issue one draft');close(page)
        switch(page,'cn2');open_(page,'cn2');assert page.locator('#analysisDiscussionNote').input_value()==''
        page.locator('#analysisDiscussionNote').fill('Issue two draft');close(page)
        switch(page,'cn1',surface='labeling');open_(page);assert page.locator('#analysisDiscussionNote').input_value()=='Issue one draft';close(page)
        switch(page,'cn1',actor='bob');open_(page);assert page.locator('#analysisDiscussionNote').input_value()=='';close(page)
        switch(page,'cn1');open_(page);assert page.locator('#analysisDiscussionNote').input_value()=='Issue one draft'
        backend['fail']=True;page.locator('#analysisDiscussionSubmit').click();page.wait_for_function('!state.analysisDiscussion.saving')
        first_key=backend['posts'][0]['key'];close(page)
        page.reload();initialize(page);open_(page);backend['fail']=False
        page.locator('#analysisDiscussionSubmit').click();page.wait_for_function('!state.analysisDiscussion.saving')
        assert len(backend['records'])==1 and all(p['key']==first_key for p in backend['posts'])
        close(page);open_(page);assert page.locator('#analysisDiscussionNote').input_value()==''
        results.append({'scenario':'Issue/account isolation, shared entry, failure/reload stable retry and committed cleanup','passed':True});page.close()

        for newer in [False,True]:
            page,backend,commit=scenario();open_(page);backend['hold']=True
            page.locator('#analysisDiscussionNote').fill('Posted snapshot')
            page.locator('#analysisDiscussionSubmit').click();page.wait_for_timeout(50);assert len(backend['held'])==1
            close(page);open_(page)
            if newer:page.locator('#analysisDiscussionNote').fill('A newer draft')
            commit(backend['held'].pop());page.wait_for_timeout(100)
            assert page.locator('#analysisDiscussionNote').input_value()==('A newer draft' if newer else '')
            close(page);open_(page);assert page.locator('#analysisDiscussionNote').input_value()==('A newer draft' if newer else '')
            results.append({'scenario':'late successful response preserves newer draft' if newer else 'late successful response retires unchanged reopened draft','passed':True});page.close()

        page,backend,_=scenario();open_(page);page.evaluate('beginAnalysisDiscussionReply(117)')
        page.locator('#analysisDiscussionNote').fill('Reply draft');close(page);backend['deleted']=True;open_(page)
        assert page.locator('#analysisDiscussionSubmit').is_disabled()
        assert page.locator('#analysisDiscussionNote').input_value()=='Reply draft'
        page.locator('[data-cancel-comment-reply]').click();assert page.locator('#analysisDiscussionSubmit').is_enabled()
        results.append({'scenario':'deleted reply target blocks posting while keeping text','passed':True});page.close()

        page,backend,_=scenario();open_(page)
        page.locator('#analysisDiscussionNote').fill('Evidence draft')
        page.locator('#analysisDiscussionImageInput').set_input_files({'name':'draft.png','mimeType':'image/png','buffer':PNG})
        page.evaluate('state.analysisDiscussion.draftImageWrite');close(page)
        page.evaluate('discussionDraftImageStore(store=>store.clear())')
        page.reload();initialize(page);open_(page)
        assert page.locator('#analysisDiscussionSubmit').is_disabled()
        assert 'Evidence draft' in page.locator('#analysisDiscussionNote').input_value()
        page.locator('[data-remove-comment-image]').click()
        assert page.locator('#analysisDiscussionSubmit').is_enabled()
        results.append({'scenario':'unavailable image cache keeps text and requires explicit removal','passed':True});page.close()

        page,backend,_=scenario();open_(page)
        page.locator('#analysisDiscussionNote').fill('Slow cached image')
        page.locator('#analysisDiscussionImageInput').set_input_files({'name':'draft.png','mimeType':'image/png','buffer':PNG})
        close(page);page.reload();initialize(page)
        page.evaluate('''()=>{
          const original=discussionDraftImageStore;let first=true;
          discussionDraftImageStore=operation=>{
            const result=original(operation);
            if(!first)return result;
            first=false;return result.then(value=>new Promise(resolve=>{window.resumeDraftImageRead=()=>resolve(value)}));
          };
          void openAnalysisDiscussion('cn1');
        }''')
        page.wait_for_function('state.analysisDiscussion.restoringDraftImages && Boolean(window.resumeDraftImageRead)')
        close(page);open_(page)
        assert page.evaluate('state.analysisDiscussion.pendingImages[0].file.size')==len(PNG)
        assert page.locator('#analysisDiscussionSubmit').is_enabled()
        page.evaluate('resumeDraftImageRead()')
        results.append({'scenario':'close and reopen during slow image-cache restoration still restores the stored file','passed':True});page.close()

        page,backend,_=scenario();open_(page)
        page.locator('#analysisDiscussionNote').fill('Older persistent draft');close(page);open_(page)
        close(page)
        page.evaluate('''()=>{
          const key=closedDraft.draftKey,draft=JSON.parse(localStorage.getItem(key));
          draft.body='Newer draft from another tab';draft.id='newer-tab';draft.savedAt=Date.now()+1;
          localStorage.setItem(key,JSON.stringify(draft));
        }''')
        open_(page)
        assert page.locator('#analysisDiscussionNote').input_value()=='Newer draft from another tab'
        page.evaluate('''()=>{
          Storage.prototype.setItem=function(){throw new DOMException('Synthetic quota','QuotaExceededError')};
          Storage.prototype.removeItem=function(){throw new DOMException('Synthetic read-only storage','SecurityError')};
        }''')
        page.locator('#analysisDiscussionNote').fill('Latest in-memory draft');close(page);open_(page)
        assert page.locator('#analysisDiscussionNote').input_value()=='Latest in-memory draft'
        assert page.evaluate('state.analysisDiscussion.draftStorageError')
        page.locator('#analysisDiscussionSubmit').click();page.wait_for_function('!state.analysisDiscussion.saving')
        assert len(backend['records'])==1
        close(page);open_(page)
        assert page.locator('#analysisDiscussionNote').input_value()==''
        results.append({'scenario':'readable stale storage cannot replace newer memory or resurrect a confirmed post after storage writes fail','passed':True});page.close()

        page,backend,_=scenario()
        def intent(dataset):
            page.evaluate('''ds=>{history.replaceState(null,'',`/manual/intent-labeling?dataset=${ds}&case=i1`);state.activePage='intent';}''',dataset)
            page.evaluate("ds=>openAnalysisDiscussion('cn1',{intentDatasetId:ds,intentCaseId:'i1'})",dataset)
        intent('ds1');page.locator('#analysisDiscussionNote').fill('Intent one draft');close(page)
        intent('ds2');assert page.locator('#analysisDiscussionNote').input_value()=='';close(page)
        intent('ds1');assert page.locator('#analysisDiscussionNote').input_value()=='Intent one draft';close(page)
        switch(page);open_(page);assert page.locator('#analysisDiscussionNote').input_value()==''
        results.append({'scenario':'Intent datasets/cases and Issue drafts stay separate','passed':True});page.close()
        assert not errors,errors
        report={'browser':browser.version,'fixture':'actual modules, localStorage/IndexedDB and synthetic HTTP only','results':results,'page_errors':errors}
        (OUTPUT/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False))
        browser.close()

if __name__=='__main__':run()
