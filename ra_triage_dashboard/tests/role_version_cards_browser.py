"""Actual version-card renderers and the 1030/1106 upload boundary, synthetic DB only."""
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def main(output_dir='/private/tmp/manual-role-cards-acceptance', base='http://127.0.0.1:50269'):
    out=Path(output_dir);out.mkdir(parents=True,exist_ok=True)
    checks=[];errors=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,channel='chrome')
        for width,language,theme in [(1440,'zh','dark'),(1440,'en','light'),(833,'zh','dark'),(390,'en','dark'),(320,'en','light')]:
            page=browser.new_page(viewport=dict(width=width,height=900))
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.add_init_script(f"localStorage.setItem('te-preview-language','{language}');localStorage.setItem('ra-triage-color-theme','{theme}');")
            page.goto(base+'/rd-results?baselines=version-20261106',wait_until='networkidle')
            expect(page.locator('.human-publication-table tbody tr')).to_have_count(20)
            for lane,field in [('rd','ra_rd_review_result'),('te','ra_review_result_sampling'),('arbitrated','ra_review_result_arbitrated')]:
                page.locator('#hpTab-'+lane).click()
                expect(page.locator('#hpTab-'+lane)).to_have_attribute('aria-selected','true')
                expect(page.locator('.rd-overview')).to_contain_text(field)
                assert 'lane='+lane in page.url
            page.screenshot(path=str(out/f'upload-1106-{width}-{language}-{theme}.png'),full_page=True)
            # Earlier releases retain the legacy upload workflow. Switching scope
            # and returning must restore all three formal lanes without a reload.
            page.evaluate("() => setBaselineScopes(['version-20261030'])")
            expect(page.locator('[data-rd-mode]')).to_have_count(2)
            expect(page.locator('[data-hp-lane]')).to_have_count(0)
            page.evaluate("() => setBaselineScopes(['version-20261106'])")
            expect(page.locator('[data-hp-lane]')).to_have_count(3)
            tasks=page.request.get(base+'/api/preview-version-tasks').json()['items']
            assert {t['role_cohort'] for t in tasks}=={'sampling','low'}
            page.evaluate("""tasks=>{
              clearTimeout(humanPublication.timer);state.activePage='review-assignments';
              document.body.dataset.activePage=state.activePage;
              document.querySelectorAll('.app-page').forEach(p=>p.classList.toggle('hidden',p.dataset.page!==state.activePage));
              document.querySelector('#pageTitle').textContent=uiText('任务分配','Task assignments');
              Object.assign(state.reviewAssignments,{splits:tasks,loading:false,lifecycle:'versions'});
              renderReviewAssignmentListFilters();renderReviewAssignmentList();
            }""",tasks)
            for task in tasks:
                card=page.locator('[data-review-assignment-batch="'+task['split_id']+'"]')
                expected='1106 · '+(('抽样集' if language=='zh' else 'Sampling') if task['role_cohort']=='sampling' else ('低置信集' if language=='zh' else 'Low confidence'))
                expect(card.locator('.review-assignment-batch-title')).to_have_text(expected)
                expect(card.locator('.review-assignment-batch-meta').first).to_have_text(
                    ('RD＋TE 交叉标注' if language=='zh' else 'RD + TE cross-review') if task['role_cohort']=='sampling'
                    else ('不含抽样 · RD 单人标注' if language=='zh' else 'Excludes sampling · One RD per case'))
                assert card.locator('.review-assignment-member').count()==len(task['members'])
                expect(card.locator('.review-assignment-progress-heading strong')).to_contain_text(f"{task['completed_count']} / {task['assignment_count']}")
                for link in card.locator('.review-assignment-batch-actions a').all():
                    assert task['split_id'] in link.get_attribute('href')
            assert not page.evaluate('document.documentElement.scrollWidth>innerWidth'),(width,language)
            page.screenshot(path=str(out/f'cards-{width}-{language}-{theme}.png'),full_page=True)
            # A runtime locale refresh keeps the same task scope and owners.
            page.evaluate("""() => {state.uiLanguage=state.uiLanguage==='zh'?'en':'zh';
              document.documentElement.dataset.uiLang=state.uiLanguage;renderReviewAssignmentListFilters();renderReviewAssignmentList();}""")
            expect(page.locator('.review-assignment-batch-title').first).to_have_text('1106 · '+('Sampling' if language=='zh' else '抽样集'))
            assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
            assert page.evaluate('state.reviewAssignments.splits.map(x=>x.split_id)')==[t['split_id'] for t in tasks]
            checks.append(dict(width=width,language=language,theme=theme,checks='three upload fields; 1030/1106 scope switching; real appendable cards, owners, progress, links and locale refresh',ok=True))
            page.close()
        browser.close()
    assert not errors,errors
    report=dict(checks=checks,errors=errors,device='macOS headless Chrome; resized viewport, not a physical phone')
    (out/'report.json').write_text(json.dumps(report,indent=2,ensure_ascii=False))
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
