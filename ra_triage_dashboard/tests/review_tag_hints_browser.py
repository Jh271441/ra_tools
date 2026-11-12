"""Actual shared Review/Case tag controls with synthetic data; no business writes.

Run directly with a Python environment containing Playwright/Chromium.
"""
import json
import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from combined_review_hydration_browser import ROOT, SETUP, catalog, html, modules, styles


OUTPUT = Path(os.environ.get("REVIEW_TAG_HINTS_QA_OUTPUT", "/tmp/review-tag-hints-qa"))
HINT = "等待抬杆, 没有其他通行办法"
HTML_HINT = '<img src=x onerror="window.hintInjected=true"> & <b>Plain text</b>'
LONG_HINT = "Long description / 很长的说明 " + "unbroken" * 150
CATALOG = [dict(item, hint="") for item in catalog] + [
    dict(key=key, label=label, hint=hint, group="false_trigger", section="interaction_decision")
    for key, label, hint in (
        ("hover-gate", "园区抬杆", HINT),
        ("hover-html", "Literal markup", HTML_HINT),
        ("hover-long", "Long description", LONG_HINT),
    )
]


def bounds(locator, width, height=1000):
    box = locator.bounding_box()
    assert box and box["x"] >= 0 and box["y"] >= 0, box
    assert box["x"] + box["width"] <= width + 1, box
    assert box["y"] + box["height"] <= height + 1, box


def run():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    bootstrap = (ROOT / "js/bind-bootstrap.js").read_text()
    start = bootstrap.index('  document.addEventListener("keydown", (event) => {\n    if (!$("#mediaDialog").open)')
    keyboard = bootstrap[start:bootstrap.index('  window.addEventListener("popstate"', start)]
    results, errors = [], []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.set_default_timeout(6000)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route("http://tag-hints.test/**", lambda route: route.fulfill(
            status=200, content_type="text/html", body=html))
        page.goto("http://tag-hints.test/manual/review")
        for name in styles:
            page.add_style_tag(content=(ROOT / name).read_text())
        for name in modules:
            page.add_script_tag(content=(ROOT / "js" / name).read_text())
        page.add_script_tag(content=keyboard)
        for labeling in (False, True):
            for width in (320, 390, 1440):
                page.set_viewport_size({"width": width, "height": 1000})
                for language in ("zh", "en"):
                    for theme in ("dark", "light"):
                        print("checking", labeling, width, language, theme, flush=True)
                        page.evaluate(SETUP, {"catalog": CATALOG})
                        page.evaluate("""([labeling,lang,theme]) => {
                          resolveContext({context:fixtureContext}); window.writes=[];
                          api=async(path,opts)=>{
                            if(opts?.method && opts.method!=='GET') {writes.push(path); throw Error('Unexpected business write in hint QA');}
                            return {context:fixtureContext};
                          };
                          if (labeling) {
                            state.activePage='labeling';
                            state.caseLabeling={...state.caseLabeling,issueId:'cn1',caseData:fixtureData,taskId:''};
                            document.querySelectorAll('.app-page').forEach(n=>n.classList.toggle('hidden',n.id!=='caseLabelingPage'));
                            $('#caseLabelingDetail').classList.remove('hidden');
                            renderCaseLabelingEditor(fixtureData);
                          }
                          applyUiLanguage(lang,{persist:false}); applyColorTheme(theme,{persist:false});
                          const owner=labeling?$('#caseLabelingMedia'):$('#detailPane');
                          const media=document.createElement('div'); media.className='detail-hero-media';
                          media.innerHTML='<button data-video-play type="button">Play</button><button data-video-jump="-1" type="button">Left</button><button data-video-jump="1" type="button">Right</button>';
                          owner.append(media); state.detailMedia.kind='video'; window.hits=[];window.hops=[];
                          media.querySelectorAll('button').forEach(b=>b.addEventListener('click',()=>hits.push(b.textContent)));
                          navigateAdjacentCase=async direction=>{hops.push(direction);};
                          navigateCaseLabelingIssue=async direction=>{hops.push(direction);};
                          $('#nextIssueButton').disabled=false;
                        }""", [labeling, language, theme])
                        root = page.locator("#caseLabelingEditor" if labeling else "#reviewPane")
                        group = root.locator('[data-tag-dropdown-group="false_trigger"]')
                        summary = group.locator(":scope > summary")
                        panel = group.locator(".review-tag-options")
                        row = group.locator('[data-review-tag-option="hover-gate"]')
                        check = row.locator('input[name="reviewTags"]')
                        tip = row.locator('[role="tooltip"]')
                        summary.scroll_into_view_if_needed()
                        summary.click()
                        expect(panel).to_be_visible()
                        # Hover reads the saved hint without selecting the label.
                        row.locator("[data-ui-info-hover]").hover()
                        try:
                            expect(tip).to_be_visible()
                        except AssertionError:
                            print(row.evaluate("n=>({classes:n.className,style:n.querySelector('[role=tooltip]').getAttribute('style'),dropdown:n.closest('details').open,bound:n.closest('#reviewPane,#caseLabelingEditor').dataset.selectedReviewTagControlsBound})"))
                            print("page errors", errors)
                            page.screenshot(path=str(OUTPUT / "failure.png"))
                            raise
                        expect(tip.locator("span")).to_have_text(HINT)
                        expect(check).not_to_be_checked()
                        bounds(tip, width)
                        assert check.get_attribute("aria-describedby") == tip.get_attribute("id")
                        assert tip.evaluate("n=>n.closest('label')") is None
                        tip.click()
                        expect(check).not_to_be_checked()
                        # The existing action menu stays unobstructed and provides
                        # an explicit touch entry that only moves focus.
                        row.locator("[data-tag-menu-toggle]").scroll_into_view_if_needed()
                        page.evaluate("()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))")
                        row.locator("[data-tag-menu-toggle]").click()
                        expect(tip).not_to_be_visible()
                        action = row.locator("[data-show-review-tag-hint]")
                        expect(action).to_be_visible()
                        expect(action).to_have_text("查看说明" if language == "zh" else "View description")
                        if width < 640:
                            assert action.bounding_box()["height"] >= 44
                        if width == 1440:
                            action.focus()
                            page.keyboard.press("Enter")
                        else:
                            action.click()
                        expect(check).to_be_focused()
                        expect(check).not_to_be_checked()
                        expect(tip).to_be_visible()
                        assert page.evaluate("writes.length") == 0
                        page.keyboard.press("Space")
                        page.keyboard.press("ArrowLeft")
                        page.keyboard.press("ArrowRight")
                        assert page.evaluate("hits") == ["Play", "Left", "Right"]
                        expect(check).not_to_be_checked()
                        expect(panel).to_be_visible()
                        # Composing Escape belongs to the input method. Ordinary
                        # Escape closes the dropdown and releases its focus once.
                        check.evaluate("n=>n.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',isComposing:true,bubbles:true,cancelable:true}))")
                        expect(panel).to_be_visible()
                        page.keyboard.press("Escape")
                        expect(panel).not_to_be_visible()
                        expect(tip).not_to_be_visible()
                        expect(check).not_to_be_focused()
                        summary.click()
                        empty = group.locator('[data-review-tag-option="traffic_light"]')
                        empty.locator("input").focus()
                        expect(empty.locator('[role="tooltip"] span')).to_have_text(
                            "暂无说明" if language == "zh" else "No description yet")
                        # Runtime locale updates keep the original checkbox and selection.
                        empty.locator("input").evaluate("n=>{n.checked=true;window.originalHintInput=n;}")
                        other = "en" if language == "zh" else "zh"
                        page.evaluate("lang=>applyUiLanguage(lang,{persist:false})", other)
                        expect(empty.locator('[role="tooltip"] span')).to_have_text(
                            "No description yet" if other == "en" else "暂无说明")
                        assert empty.locator("input").evaluate("n=>n===originalHintInput && n.checked")
                        page.evaluate("lang=>applyUiLanguage(lang,{persist:false})", language)
                        literal = group.locator('[data-review-tag-option="hover-html"]')
                        literal.locator("input").focus()
                        expect(literal.locator('[role="tooltip"] span')).to_have_text(HTML_HINT)
                        assert literal.locator('[role="tooltip"] img, [role="tooltip"] b').count() == 0
                        assert not page.evaluate("Boolean(window.hintInjected)")
                        long_row = group.locator('[data-review-tag-option="hover-long"]')
                        page.keyboard.press("ArrowDown")
                        expect(long_row.locator("input")).to_be_focused()
                        long_tip = long_row.locator('[role="tooltip"]')
                        expect(long_tip).to_be_visible()
                        bounds(long_tip, width)
                        assert long_tip.evaluate("n=>n.scrollWidth<=n.clientWidth+1")
                        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
                        if (width, language, theme) in ((320, "en", "light"), (1440, "zh", "dark")):
                            summary.evaluate("n=>n.focus({preventScroll:true})")
                            page.mouse.move(4, 4)
                            expect(long_tip).not_to_be_visible()
                            row.locator("[data-ui-info-hover]").hover()
                            expect(tip).to_have_css("opacity", "1")
                            page.screenshot(path=str(OUTPUT / f"{'labeling' if labeling else 'review'}-{width}-{language}-{theme}.png"))
                        page.mouse.click(4, 4)
                        expect(panel).not_to_be_visible()
                        expect(long_tip).not_to_be_visible()
                        results.append(dict(labeling=labeling, width=width, language=language, theme=theme, passed=True))
        # Catalog edits and later insertion use the same delegated component;
        # original checkbox nodes and current selection survive text refresh.
        root = page.locator("#caseLabelingEditor")
        group = root.locator('[data-tag-dropdown-group="false_trigger"]')
        group.locator(":scope > summary").click()
        row = group.locator('[data-review-tag-option="hover-gate"]')
        row.locator("input").focus()
        page.evaluate("""() => {
          const root=$('#caseLabelingEditor');
          window.originalGateInput=root.querySelector('input[value="hover-gate"]');
          originalGateInput.checked=true;
          const item=reviewTagCatalogItem('hover-gate'); item.hint='Updated description / 更新说明';
          syncReviewDropdownShortcutHints(root);
          const added={key:'hover-dynamic',label:'Dynamic tag',hint:'Newly inserted hint',group:'false_trigger',section:'interaction_decision'};
          state.config.review_tag_catalog.push(added);
          root.querySelector('[data-tag-dropdown-group="false_trigger"] .review-tag-options').insertAdjacentHTML('beforeend',reviewTagOptionMarkup(added,false,'false_trigger'));
          syncReviewDropdownShortcutHints(root); bindReviewTagCatalogControls(root);
        }""")
        expect(row.locator('[role="tooltip"] span')).to_have_text("Updated description / 更新说明")
        assert row.locator("input").evaluate("n=>n===originalGateInput && n.checked")
        added = group.locator('[data-review-tag-option="hover-dynamic"]')
        added.locator("input").focus()
        expect(added.locator('[role="tooltip"] span')).to_have_text("Newly inserted hint")
        # Existing button-based info controls retain click/focus/Escape behavior.
        root.evaluate("""root=>root.insertAdjacentHTML('beforeend',
          '<span class="ui-info model-review-run-help" data-ui-info data-qa-shared-info><button type="button" aria-expanded="false">Info</button><span class="ui-info-tooltip model-review-run-tooltip" role="tooltip">Existing shared info</span></span>')""")
        info = root.locator("[data-qa-shared-info]")
        info.locator("button").click()
        expect(info.locator('[role="tooltip"]')).to_be_visible()
        expect(info.locator("button")).to_have_attribute("aria-expanded", "true")
        page.keyboard.press("Escape")
        expect(info.locator('[role="tooltip"]')).not_to_be_visible()
        expect(info.locator("button")).to_be_focused()
        expect(info.locator("button")).to_have_attribute("aria-expanded", "false")
        assert page.evaluate("writes.length") == 0
        assert not errors, errors
        browser.close()
    (OUTPUT / "results.json").write_text(json.dumps(results, indent=2))
    print(f"Passed {len(results)} viewport/language/theme/page combinations; {OUTPUT}")


if __name__ == "__main__":
    run()
