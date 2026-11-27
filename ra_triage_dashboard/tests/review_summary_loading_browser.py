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
  fixtureData.label_state.sources=[{label_case_id:'labels',source_revision_ids:[201],state:'resolved',expected_output:revision.expected_output,revision_summaries:[revision]}];
  fixtureData.label_cases=[{id:'labels',revisions:[revision],resolution:{state:'resolved',heads:[revision]}}];
  fixtureData.label_state.human_publication={
    lanes:{rd:{state:'pending'},te:{state:'resolved',label:'正确触发'},arbitrated:{state:'none'}},
    sync:{rd:{sync_state:'not_ready'},te:{sync_state:'synced'},arbitrated:{sync_state:'not_ready'}}
  };
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
            assert page.locator('#annotationForm .human-role-summary').count() == 0
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

        def dialog_fits(page):
            return page.locator('#caseDecisionEvidence').evaluate(
                'n => n.scrollWidth <= n.clientWidth && document.documentElement.scrollWidth <= innerWidth')

        def finish(page, backend):
            data = page.evaluate('fixtureData')
            backend['held'].pop().fulfill(json=copy.deepcopy(data))
            page.locator('#caseLabelDecisionDialog [data-adopt-decision="201"]').wait_for()
            summary = page.locator('#caseLabelDecisionDialog .human-role-summary')
            assert summary.locator('strong').count() == 3
            assert all(text not in summary.inner_text() for text in ('待结论', 'Awaiting result', '已完成', 'Completed'))
            basis = page.locator('#caseDecisionEvidence .case-decision-basis')
            assert basis.is_visible()
            assert not basis.evaluate('n => n.open')
            toggle = basis.locator('summary')
            previous_focus = page.evaluate('document.activeElement.id')
            toggle.press('Enter')
            assert basis.evaluate('n => n.open')
            assert '#201' in basis.inner_text()
            assert 'alice' in basis.inner_text()
            assert data['label_cases'][0]['revisions'][0]['rationale'] in basis.inner_text()
            assert page.locator('.classification-flow h3').inner_text() == page.evaluate(
                'expectedOutputDisplayText(fixtureData.label_state.expected_output)')
            assert dialog_fits(page)
            assert ('已同步' if page.evaluate("state.uiLanguage === 'zh'") else 'Synced') in summary.inner_text()
            toggle.press('Enter')
            if previous_focus:
                page.locator('[id="' + previous_focus + '"]').focus()
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
                    dialog = page.locator('#caseLabelDecisionDialog')
                    if (width, language, theme) in [(320, 'en', 'light'), (1440, 'zh', 'dark')]:
                        dialog.screenshot(path=str(OUTPUT / f'summary-{width}-{language}-{theme}.png'))
                    assert not dialog.locator('[data-decision-trail]').is_visible()
                    page.locator('#caseLabelDecisionDialog [data-close-decision]').first.click()
                    page.wait_for_function('mediaResumes===1')
                    assert page.evaluate('document.querySelector("#annotationForm")===originalForm&&detailHeroMediaEl()===originalMedia')
                    assert 'Keep model draft' in page.locator('#annotationNote').input_value()
                    assert 'Keep Case draft' in page.locator('#combinedCaseRationale').input_value()
                    assert backend['posts'] == 0
                    results.append({'width': width, 'language': language, 'theme': theme, 'open_ms': round(elapsed, 2), 'passed': True})
                    page.close()

        if not os.environ.get('REVIEW_SUMMARY_SINGLE'):
            page, backend = scenario(320, 'zh', 'dark')
            page.evaluate("""()=>{
              fixtureData.label_cases = [];
              fixtureData.label_state = {state:'none', sources:[], human_publication:{
                lanes:{rd:{state:'pending',submitted:0,required:1}, te:{state:'pending',submitted:0,required:1},
                       arbitrated:{state:'none'}}, sync:{}}};
              fixtureData.exclusion_summary = null;
              fixtureData.trail_metadata_status = 'ready';
              fixtureData.dashboard_should_exclude = false;
            }""")
            open_held(page, backend)
            payload = page.evaluate('fixtureData')
            del payload['trail_metadata_status'], payload['dashboard_should_exclude']
            backend['held'].pop().fulfill(json=payload)
            headline = page.locator('.classification-flow h3')
            headline.wait_for()
            evidence = page.locator('#caseDecisionEvidence')
            assert headline.inner_text() == '等待人工标注'
            assert evidence.locator('.classification-flow li').count() == 2
            evidence.locator('.case-decision-basis summary').click()
            assert evidence.inner_text().count('0/1 人已提交') == 2
            assert '未裁决' in evidence.inner_text() and '暂无排除意见' in evidence.inner_text()
            assert '分歧' not in evidence.inner_text()
            assert 'RD、TE′ 尚待提交有效标注' in evidence.inner_text()
            assert evidence.locator('[data-decision-trail]').inner_text() == '不排除'
            page.locator('#caseLabelDecisionDialog').screenshot(path=str(OUTPUT / 'pending-roles-320-zh-dark.png'))
            page.evaluate("applyUiLanguage('en',{persist:false})")
            assert headline.inner_text() == 'Awaiting human labels'
            assert evidence.inner_text().count('0/1 reviewers submitted') == 2
            assert page.locator('#caseDecisionRelabel').is_disabled() and dialog_fits(page)
            results.append({'scenario': 'assigned roles without Case records, preserved Trail status and locale switch', 'passed': True})
            page.close()

            page, backend = scenario(390, 'en', 'light')
            open_held(page, backend)
            payload = page.evaluate('fixtureData')
            source = payload['label_state']['sources'][0]
            peer = dict(source['revision_summaries'][0], id=202, author='bob', expected_output='正确触发',
                        is_excluded=True, rationale='Evidence from the second reviewer')
            source.update(state='conflict', expected_output='', source_revision_ids=[201, 202])
            source['revision_summaries'].append(peer)
            payload['label_cases'][0]['resolution'].update(state='conflict', heads=source['revision_summaries'])
            payload['label_state'].update(state='conflict', expected_output='')
            payload['exclusion_summary']['is_excluded'] = True
            backend['held'].pop().fulfill(json=payload)
            headline = page.locator('.classification-flow h3')
            headline.wait_for()
            assert 'disputed' in headline.inner_text()
            basis = page.locator('.case-decision-basis')
            exclusion = page.locator('.case-decision-exclusion')
            assert exclusion.locator('h3').inner_text() == 'Exclusion pending'
            assert exclusion.locator('li b').all_inner_texts() == ['1 vote', '1 vote']
            assert page.locator('#caseDecisionRelabel').inner_text() == 'Relabel and decide'
            basis.locator('summary').click()
            assert 'alice' in basis.inner_text() and 'bob' in basis.inner_text()
            assert peer['rationale'] in basis.inner_text()
            # Matching classification and split exclusion must keep adjudication optional.
            payload['label_state'].update(state='resolved', expected_output='正确触发')
            source.update(state='resolved', expected_output='正确触发')
            for vote in source['revision_summaries']:
                vote['expected_output'] = '正确触发'
            payload['label_state']['human_publication']['lanes'].update(rd={'state':'resolved','label':'正确触发'})
            page.locator('#caseDecisionRefresh').click()
            page.wait_for_timeout(50)
            backend['held'].pop().fulfill(json=payload)
            page.locator('#caseDecisionRelabel', has_text='Review exclusion').wait_for()
            page.evaluate("applyUiLanguage('zh',{persist:false})")
            assert exclusion.locator('h3').inner_text() == '排除待确定'
            assert basis.evaluate('n=>n.open')
            basis.locator('summary').click()
            page.locator('.case-decision-result').screenshot(path=str(OUTPUT / 'classification-exclusion-flow.png'))
            assert dialog_fits(page)
            results.append({'scenario': 'conflicting opinions with attributed evidence and exclusion counts', 'passed': True})
            page.close()

            page, backend = scenario(320, 'en', 'light')
            page.evaluate("state.session.access_role='viewer'; bindReviewDetailActionShortcuts(); document.activeElement.blur()")
            page.keyboard.press('l')
            summary = page.locator('#sharedLabelStateDialog[open] .human-role-summary')
            summary.wait_for()
            assert 'Synced' in summary.inner_text()
            page.evaluate("applyUiLanguage('zh',{persist:false})")
            assert '已同步' in summary.inner_text()
            page.keyboard.press('l')
            page.wait_for_function('!document.querySelector("#sharedLabelStateDialog").open')
            page.evaluate('delete fixtureData.label_state.human_publication')
            page.keyboard.press('l')
            page.locator('#sharedLabelStateDialog[open]').wait_for()
            assert summary.count() == 0
            results.append({'scenario': 'read-only L shortcut, locale change and legacy Issue', 'passed': True})
            page.close()

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
