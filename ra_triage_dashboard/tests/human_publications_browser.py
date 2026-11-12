"""Headless Chrome acceptance against the loopback synthetic preview."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright,expect


def choose(page,selector,value):
    widget=page.locator(selector).locator('..')
    trigger=widget.locator('.ui-select-trigger');trigger.scroll_into_view_if_needed();trigger.click()
    option=widget.locator(f'[data-ui-select-value="{value}"]');expect(option).to_be_visible();option.click()


def main(output_dir='/private/tmp/manual-role-acceptance'):
    out=Path(output_dir);out.mkdir(exist_ok=True)
    checks=[];errors=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,channel='chrome')
        for width,language,theme in [(1440,'zh','dark'),(1440,'en','light'),(390,'zh','light'),(390,'en','dark'),(320,'en','light')]:
            page=browser.new_page(viewport=dict(width=width,height=900))
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.add_init_script(f"localStorage.setItem('te-preview-language','{language}');localStorage.setItem('ra-triage-color-theme','{theme}');")
            page.goto('http://127.0.0.1:50269/rd-results?baselines=version-20261106',wait_until='networkidle')
            expect(page.locator('.human-publication-table tbody tr')).to_have_count(20)
            assert not page.evaluate('document.documentElement.scrollWidth>innerWidth'),(width,language)
            assert page.locator('#hpStatus').evaluate("e=>!!e.closest('.ui-select')")
            page.locator('#hpSearch').fill('cn1')
            if not page.locator('#languageToggleButton').is_visible():page.locator('#mobileTopbarMore > summary').click()
            page.locator('#languageToggleButton').click()
            expect(page.locator('#hpSearch')).to_have_value('cn1')
            if not page.locator('#languageToggleButton').is_visible():page.locator('#mobileTopbarMore > summary').click()
            page.locator('#languageToggleButton').click()
            page.locator('#hpSearch').fill('')
            choose(page,'#hpSelectionAction','page')
            page.locator('[data-hp-action=preview]').click()
            expect(page.locator('#hpPreview')).to_be_visible()
            expect(page.locator('[data-hp-action=commit]')).to_be_disabled()
            page.locator('[data-hp-action=close-preview]').click()
            page.locator('[data-rd-action=next]').click()
            expect(page.locator('#hpPageJump')).to_have_value('2')
            assert 'page=2' in page.url
            assert page.locator('[data-hp-id]:checked').count()==0
            page.locator('#hpPageJump').fill('999');page.locator('#hpPageJump').press('Enter')
            expect(page.locator('#hpPageJump')).to_have_value('3')
            page.reload(wait_until='networkidle');expect(page.locator('#hpPageJump')).to_have_value('3')
            page.locator('#hpPageJump').fill('1');page.locator('[data-rd-action=jump]').click()
            expect(page.locator('#hpPageJump')).to_have_value('1')
            page.locator('#hpTab-te').click();expect(page.locator('#hpTab-te')).to_have_attribute('aria-selected','true')
            assert 'lane=te' in page.url
            page.locator('#hpTab-arbitrated').click();expect(page.locator('#hpTab-arbitrated')).to_have_attribute('aria-selected','true')
            page.locator('#hpTab-rd').click()
            # Shared select opens by keyboard, supports Escape, and stays within viewport.
            trigger=page.locator('#hpStatus').locator('..').locator('.ui-select-trigger')
            trigger.focus();trigger.press('Enter')
            page.keyboard.press('Escape')
            page.locator('[data-hp-action="history:cn10"]').click()
            expect(page.locator('[data-hp-action=close-history]')).to_be_visible()
            assert 'history_issue=cn10' in page.url
            page.locator('[data-hp-action=close-history]').click()
            page.screenshot(path=str(out/f'{width}-{language}-{theme}.png'),full_page=True)
            assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
            # Empty and failure states keep pagination disabled.
            page.locator('#hpSearch').fill('cn99999999');page.locator('#hpSearch').press('Enter')
            expect(page.locator('.human-publication-table tbody tr')).to_have_count(0)
            expect(page.locator('[data-rd-action=next]')).to_be_disabled()
            page.route('**/api/human-publications?*',lambda route:route.fulfill(status=503,content_type='application/json',body='{"detail":"fixture failure"}'))
            page.locator('[data-hp-action=refresh]').click()
            expect(page.locator('.rd-notice.is-error')).to_be_visible()
            expect(page.locator('[data-rd-action=next]')).to_be_disabled()
            page.screenshot(path=str(out/f'{width}-{language}-failure.png'),full_page=True)
            checks.append(dict(width=width,language=language,theme=theme,ok=True));page.close()
        page=browser.new_page(viewport=dict(width=320,height=900))
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto('http://127.0.0.1:50269/rd-results?baselines=version-20261106&preview=users',wait_until='networkidle')
        assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
        assert page.locator('[data-annotation-role]').count()==5
        assert page.locator('[data-annotation-role]').first.evaluate("e=>!!e.closest('.ui-select')")
        choose(page,'[data-access-user="jasperchen"] [data-annotation-role]','te')
        if not page.locator('#languageToggleButton').is_visible():page.locator('#mobileTopbarMore > summary').click()
        page.locator('#languageToggleButton').click()
        expect(page.locator('[data-access-user="jasperchen"] [data-annotation-role]')).to_have_value('te')
        page.screenshot(path=str(out/'users-320.png'),full_page=True)
        checks.append(dict(page='users',width=320,check='shared roles, language draft retention, overflow',ok=True));page.close()
        for width,language,theme in [(1440,'zh','dark'),(390,'en','dark'),(320,'en','light')]:
            page=browser.new_page(viewport=dict(width=width,height=900))
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.add_init_script(f"localStorage.setItem('te-preview-language','{language}');localStorage.setItem('ra-triage-color-theme','{theme}');")
            page.goto('http://127.0.0.1:50269/version-datasets?dataset=release-20261106-odd2',wait_until='networkidle')
            expect(page.locator('#versionDatasetGrid .version-card')).to_have_count(20)
            assert not page.evaluate('document.documentElement.scrollWidth>innerWidth'),('gallery',width)
            # A size change on page one must actually reload and persist in the URL.
            choose(page,'#versionDatasetPageSize','10')
            expect(page.locator('#versionDatasetGrid .version-card')).to_have_count(10)
            assert 'page_size=10' in page.url
            page.locator('#versionDatasetJump').fill('999');page.locator('#versionDatasetJump').press('Enter')
            expect(page.locator('#versionDatasetJump')).to_have_value('6')
            page.reload(wait_until='networkidle');expect(page.locator('#versionDatasetJump')).to_have_value('6')
            choose(page,'#versionDatasetOwner','yupuxue')
            expect(page.locator('#versionDatasetJump')).to_have_value('1')
            page.wait_for_function("versionDatasetState.members?.items.every(x=>x.reviewers.some(r=>r.username==='yupuxue'))")
            assert page.locator('#versionDatasetGrid .version-card').count()>0
            assert page.locator('.version-joint-result').first.inner_text().startswith('Reviewed' if language=='en' else '复核')
            page.locator('#versionDatasetGrid').screenshot(path=str(out/f'gallery-{width}-owners.png'))
            # Runtime language switching retains the owner, page size and query scope.
            if not page.locator('#languageToggleButton').is_visible():page.locator('#mobileTopbarMore > summary').click()
            page.locator('#languageToggleButton').click()
            expect(page.locator('#versionDatasetOwner')).to_have_value('yupuxue')
            expect(page.locator('#versionDatasetPageSize')).to_have_value('10')
            choose(page,'#versionDatasetReviewStatus','completed')
            page.wait_for_function("!versionDatasetState.loadingKey")
            assert page.evaluate("versionDatasetState.members.items.every(x=>x.reviewers.find(r=>r.username==='yupuxue').submitted)")
            choose(page,'#versionDatasetOwner','');choose(page,'#versionDatasetReviewStatus','all')
            page.wait_for_function("!versionDatasetState.loadingKey")
            page.screenshot(path=str(out/f'gallery-{width}-{language}-switched-{theme}.png'),full_page=True)
            assert not page.evaluate('document.documentElement.scrollWidth>innerWidth'),('gallery-final',width)
            page.locator('#versionDatasetSearch').fill('cn999999');page.locator('#versionDatasetSearch').press('Enter')
            expect(page.locator('#versionDatasetGrid .version-card')).to_have_count(0)
            expect(page.locator('#versionDatasetNext')).to_be_disabled();expect(page.locator('#versionDatasetJump')).to_be_disabled()
            checks.append(dict(page='version-gallery',width=width,language=language,theme=theme,ok=True));page.close()
        # Render the changed Review components with a real synthetic DB context.
        for width in [1440,390,320]:
            page=browser.new_page(viewport=dict(width=width,height=900))
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto('http://127.0.0.1:50269/rd-results?baselines=version-20261106',wait_until='networkidle')
            human=page.request.get('http://127.0.0.1:50269/api/preview-human-context/cn10').json()
            page.add_script_tag(url='http://127.0.0.1:50269/static/js/review-form.js')
            page.evaluate("""human=>{
              clearTimeout(humanPublication.timer);state.activePage='review';document.body.dataset.activePage='review';
              document.querySelectorAll('.app-page').forEach(p=>p.classList.toggle('hidden',p.dataset.page!=='review'));
              document.querySelector('#reviewGalleryView').classList.add('hidden');document.querySelector('#reviewDetailView').classList.remove('hidden');
              document.querySelector('#reviewPane').innerHTML='<form id="annotationForm" class="review-form">'+supplementalReviewNoticeMarkup(human)+'<div id="humanReviewStatus"></div><textarea id="fixtureDraft">draft preserved</textarea></form>';
              renderHumanReviewStatus(human);window.updateTagSummary=window.updateEvidenceSummary=window.syncReviewTagCreatorPlacement=window.renderCombinedReviewContextStatus=()=>{};
            }""",human)
            page.locator('.review-task-supplemental-notice summary').click()
            if width<761:
                box=page.locator('.review-task-supplemental-notice summary').bounding_box()
                assert box['height']>=44 and box['width']>=44
            expect(page.locator('.human-role-summary')).to_contain_text('RD')
            page.evaluate("state.uiLanguage='en';document.documentElement.dataset.uiLang='en';refreshReviewFormLanguage();")
            expect(page.locator('#fixtureDraft')).to_have_value('draft preserved')
            expect(page.locator('.review-task-supplemental-notice')).to_contain_text('Your annotation is advisory')
            expect(page.locator('.human-role-summary')).to_contain_text('labels')
            assert not page.evaluate('document.documentElement.scrollWidth>innerWidth'),('review-component',width)
            page.locator('#reviewPane').screenshot(path=str(out/f'review-status-{width}.png'))
            checks.append(dict(page='review-components',width=width,language='zh→en',ok=True));page.close()
        browser.close()
    assert not errors,errors
    (out/'report.json').write_text(json.dumps(dict(checks=checks,errors=errors,device='macOS headless Chrome; resized viewport, not a real device'),indent=2))
    print(json.dumps(checks))


if __name__=='__main__':main()
