"""Real Review/player keyboard integration; local fixture media and synthetic APIs."""
import json
import os
from pathlib import Path
import re
import runpy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path(os.environ.get('REVIEW_MEDIA_QA_OUTPUT', '/tmp/review-media-shortcuts-qa'))
CLIP = Path(os.environ['REVIEW_MEDIA_TEST_CLIP'])
POSTER = Path(os.environ['REVIEW_MEDIA_TEST_POSTER'])
fixture = runpy.run_path(str(ROOT / 'tests/combined_review_hydration_browser.py'))
bootstrap = (ROOT / 'static/js/bind-bootstrap.js').read_text()
start = bootstrap.index('  document.addEventListener("keydown", (event) => {\n    if (!$("#mediaDialog").open)')
keyboard = bootstrap[start:bootstrap.index('  window.addEventListener("popstate"', start)]
SETUP = fixture['SETUP'].replace('  state.selectedCase = fixtureData;', r'''
  fixtureData.assets={frames:[-1000,0,1000].map(offset_ms=>({url:'/api/fixture.jpg',offset_ms})),
    video:{url:'/api/original.mp4',duration_ms:40000,tracks:[
      {url:'/api/original.mp4',label:'BEV 视频'},
      {url:'/api/camera-video',label:'Camera102 视频'},
      {url:'/api/closeup.mp4',source_id:'bev_closeup',label:'局部 BEV 视频',poster_url:'/api/fixture.jpg'}]}};
  fixtureData.camera={frames:[-1000,0,1000].map(offset_ms=>({url:'/api/fixture.jpg',offset_ms}))};
  state.detailMedia={issueId:'cn1',kind:'video',indexes:{bev:1,camera:1},loadSeq:0};
  state.selectedCase = fixtureData;
''')


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        if 'planning-constraints' in self.path:
            body=json.dumps({'status':'unavailable','frames':[]}).encode()
            self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(body)
            return
        if self.path.endswith('.jpg'):
            file, kind = POSTER, 'image/jpeg'
        elif '.mp4' in self.path or '/camera-video' in self.path:
            file, kind = CLIP, 'video/mp4'
        else:
            body=fixture['html'].encode()
            self.send_response(200);self.send_header('Content-Type','text/html');self.end_headers();self.wfile.write(body)
            return
        size=file.stat().st_size
        match=re.match(r'bytes=(\d+)-(\d*)',self.headers.get('Range',''))
        begin=int(match[1]) if match else 0
        end=min(size-1,int(match[2]) if match and match[2] else size-1)
        self.send_response(206 if match else 200)
        self.send_header('Content-Type',kind);self.send_header('Accept-Ranges','bytes')
        self.send_header('Content-Length',str(end-begin+1))
        if match:self.send_header('Content-Range',f'bytes {begin}-{end}/{size}')
        self.end_headers()
        try:
            with file.open('rb') as stream:
                stream.seek(begin);self.wfile.write(stream.read(end-begin+1))
        except (BrokenPipeError,ConnectionResetError):
            pass


def run():
    OUTPUT.mkdir(parents=True,exist_ok=True)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    Thread(target=server.serve_forever,daemon=True).start()
    results=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1000})
        page.set_default_timeout(7000)
        errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto(f'http://127.0.0.1:{server.server_port}/review')
        for name in fixture['styles']:page.add_style_tag(content=(ROOT/'static'/name).read_text())
        for name in fixture['modules']:page.add_script_tag(content=(ROOT/'static/js'/name).read_text())
        page.add_script_tag(content=keyboard)
        page.evaluate('''() => {
            document.querySelector('#mediaDialog').addEventListener('close',cleanupMediaDialog);
            document.querySelectorAll('[data-close]').forEach(b=>b.addEventListener('click',()=>closeDialog(b.dataset.close)));
            window.mediaClicks=[];
            window.lastCloses=[];
            const closeDropdowns=closeAllReviewDropdowns;
            closeAllReviewDropdowns=(...args)=>{
                lastCloses.push({stack:new Error().stack,active:document.activeElement?.outerHTML.slice(0,150)});
                lastCloses=lastCloses.slice(-5);return closeDropdowns(...args);
            };
            document.addEventListener('click',event=>{
                const button=event.target.closest('[data-video-play],[data-video-jump],[data-video-t0]');
                if(button)mediaClicks.push(button.hasAttribute('data-video-play')?'play':button.dataset.videoJump||'t0');
            },true);
        }''')

        def ready():
            page.wait_for_function("(()=>{const v=document.querySelector('#detailPane video');return v&&v.readyState>=2&&!v.seeking})()")

        def open_tags(origin='checkbox'):
            page.evaluate('''origin=>{
                closeAllReviewDropdowns();
                const input=document.querySelector('#reviewPane input[name=reviewTags][value=u_turn]');
                const dropdown=input.closest('.review-dropdown');
                dropdown.open=true;positionReviewDropdownPanel(dropdown);
                (origin==='checkbox'?input:dropdown.querySelector('summary')).focus({preventScroll:true});
            }''',origin)
            panel=page.locator('#reviewPane .review-dropdown[open] .review-tag-options')
            bounds=panel.bounding_box()
            viewport=page.viewport_size
            assert bounds and bounds['width']>0 and bounds['height']>0,'dropdown is not visible'
            assert bounds['x']>=-1 and bounds['x']+bounds['width']<=viewport['width']+1,bounds
            assert bounds['y']>=-1 and bounds['y']+bounds['height']<=viewport['height']+1,bounds

        def tags():
            return page.evaluate("[...document.querySelectorAll('#reviewPane input[name=reviewTags]:checked')].map(n=>n.value)")

        def still_open():
            assert page.locator('#reviewPane .review-dropdown[open]').count()==1,('media shortcut dismissed tags',page.evaluate('lastCloses'))

        for width in [1440,320,390]:
            for lang in ['zh','en']:
                for theme in ['dark','light']:
                    if os.environ.get('REVIEW_MEDIA_QA_ONLY') and os.environ['REVIEW_MEDIA_QA_ONLY']!=f'{width},{lang},{theme}':continue
                    print('checking',width,lang,theme,flush=True)
                    page.set_viewport_size({'width':width,'height':1000})
                    page.evaluate(SETUP,{'catalog':fixture['catalog']})
                    page.evaluate('''([lang,theme])=>{
                        resolveContext({context:fixtureContext});api=async()=>({context:fixtureContext});
                        refreshReviewAfterSave=async()=>{};
                        applyUiLanguage(lang,{persist:false});applyColorTheme(theme,{persist:false});
                    }''',[lang,theme])
                    page.wait_for_function("state.combinedReviewLoad?.status==='ready'")
                    ready()
                    for origin in ['summary','checkbox']:
                        open_tags(origin);before=tags()
                        page.evaluate('mediaClicks=[]')
                        page.keyboard.press('Space')
                        page.wait_for_function("!document.querySelector('#detailPane video').paused")
                        page.keyboard.press('Space')
                        page.wait_for_function("document.querySelector('#detailPane video').paused")
                        assert page.evaluate('mediaClicks')==['play','play'],'Space must trigger exactly once'
                        assert tags()==before,'Space changed a label'
                        still_open()
                        assert page.evaluate("Boolean(document.activeElement.closest('.review-dropdown'))"),'play lost dropdown focus'
                        page.evaluate("document.querySelector('#detailPane video').currentTime=20")
                        ready()
                        page.keyboard.press('ArrowRight')
                        page.wait_for_function("Math.abs(document.querySelector('#detailPane video').currentTime-21)<.1")
                        page.keyboard.press('ArrowLeft')
                        page.wait_for_function("Math.abs(document.querySelector('#detailPane video').currentTime-20)<.1")
                        assert page.evaluate('mediaClicks')==['play','play','1','-1'],'arrows duplicated'
                        still_open();assert tags()==before
                        page.evaluate("document.querySelector('#detailPane video').currentTime=23")
                        ready();page.keyboard.press('0')
                        page.wait_for_function("Math.abs(document.querySelector('#detailPane video').currentTime-20)<.1")
                        still_open();assert tags()==before
                        for key, expected in [('Shift+V','/api/closeup.mp4'),('o','/api/original.mp4')]:
                            page.keyboard.press(key);ready()
                            assert expected in page.locator('#detailPane video').get_attribute('src')
                            still_open();assert tags()==before
                        for key,kind in [('b','bev'),('c','camera'),('v','video')]:
                            page.keyboard.press(key)
                            page.wait_for_function('kind=>state.detailMedia.kind===kind',arg=kind)
                            still_open();assert tags()==before
                        ready()
                        assert page.evaluate("Boolean(document.activeElement.closest('.review-dropdown'))"),'media switching lost dropdown focus'
                        page.keyboard.press('g')
                        assert page.locator('.planning-constraint-panel:not([hidden])').count()==1
                        page.keyboard.press('Escape')
                        assert page.locator('.planning-constraint-panel:not([hidden])').count()==0
                        still_open()
                        page.keyboard.press('f')
                        assert page.locator('#mediaDialog').evaluate('(n)=>n.open')
                        page.keyboard.press('Escape')
                        page.wait_for_function("!document.querySelector('#mediaDialog').open")
                        still_open()
                        page.keyboard.press('Escape')
                        assert page.locator('#reviewPane .review-dropdown[open]').count()==0

                    # A number remains a label action; a held Space and IME do not act.
                    open_tags();old=tags();page.keyboard.press('1');assert tags()!=old
                    current=tags();page.evaluate('mediaClicks=[]')
                    for extra in [{'isComposing':True},{'keyCode':229},{'ctrlKey':True},{'metaKey':True},{'altKey':True},{'repeat':True}]:
                        page.evaluate('''extra=>document.activeElement.dispatchEvent(new KeyboardEvent('keydown',{key:' ',code:'Space',bubbles:true,cancelable:true,...extra}))''',extra)
                    assert page.evaluate('mediaClicks')==[];assert tags()==current
                    page.keyboard.press('Escape')

                    # Browser-restored history focus and ordinary action buttons can exit.
                    history=page.locator('#reviewHistoryLaunchButton')
                    history.click();assert page.locator('#historyDialog').evaluate('(n)=>n.open')
                    page.keyboard.press('Escape');page.wait_for_function("!document.querySelector('#historyDialog').open")
                    assert history.evaluate('(n)=>document.activeElement===n'),'native dialog did not restore history focus'
                    page.keyboard.press('Escape')
                    assert not history.evaluate('(n)=>document.activeElement===n')
                    page.keyboard.press('e')
                    assert page.locator('#combinedCaseRationale').evaluate('(n)=>document.activeElement===n')
                    page.keyboard.press('Escape')
                    for selector in ['#modelHistoryLaunchButton','#issueLabelCommentsButton','#detailMediaExpandButton','#backToGalleryButton']:
                        button=page.locator(selector)
                        if button.count() and button.is_visible() and button.is_enabled():
                            button.focus();page.keyboard.press('Escape')
                            assert not button.evaluate('(n)=>document.activeElement===n'),selector
                    picker=page.locator('#detailMediaKindTrigger')
                    picker.focus();page.keyboard.press('Escape')
                    assert not picker.evaluate('(n)=>document.activeElement===n'),'closed picker focus trapped'
                    picker.click();page.keyboard.press('ArrowDown');page.keyboard.press('Escape')
                    assert page.locator('#detailMediaKindPicker').get_attribute('class').find('is-open')<0
                    assert not page.evaluate("Boolean(document.activeElement.closest('#detailMediaKindPicker'))"),'open picker focus trapped'

                    # Text typing, including literal spaces and v, must never play/switch.
                    ready();page.evaluate('mediaClicks=[]')
                    note=page.locator('#combinedCaseRationale');note.fill('Draft / 草稿')
                    note.press('Space');note.press('v');note.press('ArrowLeft')
                    assert page.evaluate('mediaClicks')==[]
                    assert note.input_value().endswith(' v')
                    note.press('Escape');assert not note.evaluate('(n)=>document.activeElement===n')
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),(width,lang,theme,'horizontal overflow')
                    if (width,lang,theme) in [(1440,'zh','dark'),(320,'en','light')]:
                        open_tags();page.screenshot(path=str(OUTPUT/f'review-{width}-{lang}-{theme}.png'),full_page=True)
                        page.keyboard.press('Escape')
                    results.append({'width':width,'language':lang,'theme':theme,'origins':2,'passed':True})
        labeling=[]
        for width in [1440,320]:
            page.set_viewport_size({'width':width,'height':1000})
            page.evaluate(SETUP,{'catalog':fixture['catalog']})
            page.evaluate('''() => {
                resolveContext({context:fixtureContext});api=async()=>({context:fixtureContext});
            }''')
            page.wait_for_function("state.combinedReviewLoad?.status==='ready'")
            page.evaluate('''() => {
                releaseBevVideoPlayer(document.querySelector('#detailPane'));
                state.activePage='labeling';
                state.caseLabeling={...state.caseLabeling,issueId:'cn1',caseData:fixtureData,taskId:''};
                document.querySelectorAll('.app-page').forEach(n=>n.classList.toggle('hidden',n.id!=='caseLabelingPage'));
                document.querySelector('#caseLabelingDetail').classList.remove('hidden');
                renderCaseLabelingEditor(fixtureData);
                const pane=document.querySelector('#caseLabelingMedia');
                pane.innerHTML=detailMediaCommandMarkup(fixtureData)+heroMediaSection(fixtureData);
                bindDetailMedia(fixtureData);
                const input=document.querySelector('#caseLabelingEditor input[name=reviewTags][value=u_turn]');
                const dropdown=input.closest('.review-dropdown');dropdown.open=true;positionReviewDropdownPanel(dropdown);input.focus({preventScroll:true});
                mediaClicks=[];
            }''')
            page.wait_for_function("document.querySelector('#caseLabelingMedia video')?.readyState>=2")
            page.keyboard.press('Space')
            page.wait_for_function("!document.querySelector('#caseLabelingMedia video').paused")
            page.keyboard.press('Space')
            page.wait_for_function("document.querySelector('#caseLabelingMedia video').paused")
            assert page.evaluate('mediaClicks')==['play','play']
            assert page.locator('#caseLabelingEditor .review-dropdown[open]').count()==1
            assert page.locator('#caseLabelingEditor input[name=reviewTags][value=u_turn]').is_checked() is False
            page.keyboard.press('Escape')
            assert not page.evaluate("Boolean(document.activeElement.closest('.review-dropdown'))")
            labeling.append({'width':width,'passed':True})
        assert not errors,errors
        report={'browser':browser.version,'combinations':results,'errors':errors,
                'labeling_shared_controls':labeling,
                'coverage':'Actual Review shell/modules/styles/native dialogs and decoded local video; synthetic API data; desktop viewport testing, not a physical mobile device'}
        (OUTPUT/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
        browser.close()
    server.shutdown();server.server_close()
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':
    run()
