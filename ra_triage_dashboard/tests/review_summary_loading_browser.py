"""Real Review summary UI with held HTTP reads; no production writes."""
import copy
import json
import os
from pathlib import Path
import re
import runpy

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path(os.environ.get('REVIEW_SUMMARY_QA_OUTPUT', '/tmp/review-summary-loading'))
fixture = runpy.run_path(str(ROOT / 'tests/combined_review_hydration_browser.py'))
setup, count = re.subn(r'  api = async path => \{[\s\S]+?\n  \};', '  api = originalApi;', fixture['SETUP'])
assert count == 1
setup = setup.replace('  state.selectedCase = fixtureData;', '''
  fixtureData.label_state.sources=[{label_case_id:'labels',source_revision_ids:[201],revision_summaries:[revision]}];
  fixtureData.label_cases=[{id:'labels',revisions:[revision],resolution:{state:'resolved',heads:[revision]}}];
  fixtureData.exclusion_summary={is_excluded:false};
  fixtureData.assets={frames:[{offset_ms:0,url:'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j3ioAAAAASUVORK5CYII='}]};
  state.caseLabeling={issueId:'',pendingImages:[],caseData:null};
  state.selectedCase = fixtureData;
''')


def run():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    results, errors = [], []
    with sync_playwright() as p:
        options = {'executable_path': os.environ['CHROMIUM_EXECUTABLE_PATH']} if os.environ.get('CHROMIUM_EXECUTABLE_PATH') else {}
        browser = p.chromium.launch(headless=True, **options)

        def scenario(width=1440, language='zh', theme='dark'):
            page = browser.new_page(viewport={'width': width, 'height': 1000})
            page.set_default_timeout(6000)
            page.on('pageerror', lambda error: errors.append(str(error)))
            backend = {'held': [], 'reads': 0, 'failure': False, 'posts': 0}

            def routes(route):
                path = route.request.url.split('?', 1)[0]
                if route.request.method != 'GET':
                    backend['posts'] += 1
                    route.fulfill(status=405, json={'detail': 'No test writes'})
                elif '/api/labeling/cases/' in path:
                    backend['reads'] += 1
                    if backend['failure']:
                        route.fulfill(status=400, json={'detail': 'Synthetic source failure'})
                    else:
                        backend['held'].append(route)
                elif path.endswith('/combined-review-context'):
                    route.fulfill(json={'context': page.evaluate('fixtureContext')})
                elif '/api/' in path:
                    route.fulfill(json={})
                else:
                    route.fulfill(content_type='text/html', body=fixture['html'])

            page.route('http://summary-loading.test/**', routes)
            page.goto('http://summary-loading.test/manual/review?issue=cn1&run=run&work_split=task&baselines=fixture')
            for name in fixture['styles']:
                page.add_style_tag(content=(ROOT / 'static' / name).read_text())
            for name in fixture['modules']:
                page.add_script_tag(content=(ROOT / 'static/js' / name).read_text())
            page.evaluate('()=>{window.originalApi=api;}')
            page.evaluate(setup, {'catalog': fixture['catalog']})
            page.wait_for_function("state.combinedReviewLoad?.status==='ready'")
            page.evaluate('([lang,theme])=>{applyUiLanguage(lang,{persist:false});applyColorTheme(theme,{persist:false});}', [language, theme])
            page.locator('#annotationNote').fill('Keep model draft / 保留模型草稿')
            page.locator('#combinedCaseRationale').fill('Keep Case draft / 保留问题草稿')
            page.evaluate('''()=>{
              window.originalForm=document.querySelector('#annotationForm');
              window.originalMedia=detailHeroMediaEl();
              window.mediaPauses=0;window.mediaResumes=0;
              const video=document.createElement('video');
              video._pauseBevPlayback=()=>mediaPauses++;
              video._resumeBevPlayback=()=>mediaResumes++;
              originalMedia.append(video);
              window.visibleFixtureVideo=video;
              const trigger=document.querySelector('#reviewSharedLabelState [data-open-shared-label-state]');
              trigger.addEventListener('click',()=>{window.clickedAt=performance.now();},{capture:true});
              const observer=new MutationObserver(()=>{
                if(document.querySelector('#caseLabelDecisionDialog')?.open){
                  window.openedAt=performance.now();observer.disconnect();
                }
              });observer.observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:['open']});
            }''')
            return page, backend

        def open_held(page, backend):
            page.locator('#reviewSharedLabelState [data-open-shared-label-state]').click()
            # This deliberately fails on the old await-before-showModal path.
            page.wait_for_selector('#caseLabelDecisionDialog[open]', timeout=500)
            page.wait_for_function("document.querySelector('#caseLabelDecisionDialog [role=status]')!==null")
            assert page.locator('#caseDecisionRelabel').is_disabled()
            assert not page.locator('#caseLabelDecisionDialog [data-adopt-decision]').count()
            page.evaluate('startCaseDecisionEditor(fixtureData,201)')
            assert page.evaluate('caseLabelDecisionUi.editor===null')
            page.wait_for_timeout(50)
            assert len(backend['held']) == 1
            assert page.evaluate('mediaPauses') == 1
            assert page.evaluate('openedAt-clickedAt') < 500
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')

        def finish(page, backend):
            data = page.evaluate('fixtureData')
            backend['held'].pop().fulfill(json=copy.deepcopy(data))
            page.locator('#caseLabelDecisionDialog [data-adopt-decision="201"]').wait_for()
            assert page.locator('#caseDecisionRelabel').is_enabled()
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')

        for width in ([1440] if os.environ.get('REVIEW_SUMMARY_SINGLE') else [320, 390, 1440]):
            for language in (['zh'] if os.environ.get('REVIEW_SUMMARY_SINGLE') else ['zh', 'en']):
                for theme in (['dark'] if os.environ.get('REVIEW_SUMMARY_SINGLE') else ['dark', 'light']):
                    page, backend = scenario(width, language, theme)
                    open_held(page, backend)
                    elapsed = page.evaluate('openedAt-clickedAt')
                    initial_focus = page.evaluate('document.activeElement.id')
                    if (width, language, theme) in [(320, 'en', 'light'), (1440, 'zh', 'dark')]:
                        page.screenshot(path=str(OUTPUT / f'loading-{width}-{language}-{theme}.png'))
                    finish(page, backend)
                    assert page.evaluate('document.activeElement.id') == initial_focus
                    page.locator('#caseLabelDecisionDialog [data-close-decision]').first.click()
                    page.wait_for_function('mediaResumes===1')
                    assert page.evaluate('document.querySelector("#annotationForm")===originalForm&&detailHeroMediaEl()===originalMedia')
                    assert 'Keep model draft' in page.locator('#annotationNote').input_value()
                    assert 'Keep Case draft' in page.locator('#combinedCaseRationale').input_value()
                    assert backend['posts'] == 0
                    results.append({'width': width, 'language': language, 'theme': theme, 'open_ms': round(elapsed, 2), 'passed': True})
                    page.close()

        if not os.environ.get('REVIEW_SUMMARY_SINGLE'):
            page, backend = scenario(320, 'en', 'light')
            backend['failure'] = True
            page.locator('#reviewSharedLabelState [data-open-shared-label-state]').click()
            page.locator('#caseLabelDecisionDialog [role=alert]').wait_for()
            assert page.locator('#caseDecisionRelabel').is_disabled()
            page.evaluate("applyUiLanguage('zh',{persist:false})")
            assert '加载' in page.locator('#caseLabelDecisionDialog [role=alert]').inner_text()
            page.screenshot(path=str(OUTPUT / 'error-320-zh-light.png'))
            backend['failure'] = False
            page.locator('#caseDecisionRefresh').click()
            page.wait_for_timeout(50)
            assert len(backend['held']) == 1
            finish(page, backend)
            assert backend['reads'] == 2
            assert page.evaluate("document.activeElement.id==='caseDecisionRefresh'")
            results.append({'scenario': 'inline failure, locale switch and retry', 'passed': True})
            page.close()

            page, backend = scenario()
            open_held(page, backend)
            with page.expect_event('requestfailed', predicate=lambda r: '/api/labeling/cases/' in r.url):
                page.locator('#caseLabelDecisionDialog [data-close-decision]').first.click()
            assert not page.locator('#caseLabelDecisionDialog').is_visible()
            page.locator('#reviewSharedLabelState [data-open-shared-label-state]').click()
            page.wait_for_timeout(80)
            assert backend['reads'] == 2
            backend['held'].pop(0).abort()  # Settle the cancelled interception as well.
            finish(page, backend)
            results.append({'scenario': 'close cancels read; reopening owns a new request', 'passed': True})
            page.close()

            page, backend = scenario()
            open_held(page, backend)
            with page.expect_event('requestfailed', predicate=lambda r: '/api/labeling/cases/' in r.url):
                page.keyboard.press('Escape')
            backend['held'].pop().abort()
            page.wait_for_function('mediaResumes===1')
            assert not page.locator('#caseLabelDecisionDialog').is_visible()
            results.append({'scenario': 'Escape cancels pending read and restores media ownership', 'passed': True})
            page.close()

            page, backend = scenario()
            open_held(page, backend)
            wrong = page.evaluate('fixtureData')
            wrong['issue_id'] = 'cn2'
            backend['held'].pop().fulfill(json=wrong)
            page.locator('#caseLabelDecisionDialog [role=alert]').wait_for()
            assert page.locator('#caseDecisionRelabel').is_disabled()
            assert page.evaluate("caseLabelDecisionUi.context.caseData.issue_id==='cn1'")
            results.append({'scenario': 'mismatched Issue response remains blocked with inline error', 'passed': True})
            page.close()

            for change in ["state.selectedId='cn2'", "state.selectedBaselineIds=['other']", "state.session.username='bob'", 'state.pageNavigationEpoch++']:
                page, backend = scenario()
                open_held(page, backend)
                page.evaluate(change)
                backend['held'].pop().fulfill(json=page.evaluate('fixtureData'))
                page.wait_for_function('!document.querySelector("#caseLabelDecisionDialog").open')
                assert not page.locator('#caseLabelDecisionDialog').is_visible()
                results.append({'scenario': 'late response rejected: ' + change, 'passed': True})
                page.close()

        assert not errors, errors
        report = {'browser': browser.version, 'fixture': 'actual shell/modules/styles/API client, synthetic HTTP only', 'results': results, 'page_errors': errors}
        (OUTPUT / 'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(json.dumps(report, ensure_ascii=False))
        browser.close()


if __name__ == '__main__':
    run()
