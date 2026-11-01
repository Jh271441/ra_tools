"""Actual Review modules with delayed synthetic API responses; no business writes."""
import json
import os
from pathlib import Path
import re
import runpy

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1] / "static"
OUTPUT = Path(os.environ.get("REVIEW_HYDRATION_QA_OUTPUT", "/tmp/review-hydration-qa"))
OUTPUT.mkdir(parents=True, exist_ok=True)
original = (ROOT / "index.html").read_text()
styles = json.loads("[" + re.search(r"const stylesheetPaths = \[([\s\S]*?)\];", original)[1].rstrip().rstrip(",") + "]")
html = re.sub(r"<script\b[^>]*>[\s\S]*?</script>", "", original).replace("{{RA_TRIAGE_BASE_PATH}}", "")
modules = [name.strip() for name in (ROOT / "js/MANIFEST").read_text().splitlines()
           if name.strip() and not name.startswith("#") and name.strip() != "bind-bootstrap.js"]
catalog = runpy.run_path(str(ROOT.parent / "app/runtime_catalogs.py"))["REVIEW_TAG_CATALOG"]

SETUP = r"""({catalog, hasProjection = true}) => {
  localStorage.clear();
  state.session = {username:'alice', verified:true, access_role:'writer', identity_pending:false};
  state.activePage = 'review'; state.selectedId = 'cn1'; state.selectedRunId = 'run'; state.reviewWorkSplitId = 'task';
  state.selectedBaselineIds = ['fixture']; state.modelRuns = [{id:'run', name:'Fixture Run'}];
  state.config = {missing_evidence_catalog:[], review_tag_catalog:catalog, review_notifications:{enabled:false}};
  document.documentElement.dataset.sessionPending = 'false';
  const revision = {id:201, author:'alice', expected_output:'误触发', tags:['u_turn'], is_excluded:false,
    rationale:'已保存的掉头说明 / Saved U-turn rationale', created_at:'2026-01-01T00:00:00+08:00'};
  const model = {id:101, model_run_id:'run', work_split_id:'task', author:'alice', model_review_status:'completed',
    note:'已保存的模型说明 / Saved model reason', tags:[], created_at:revision.created_at};
  window.fixtureData = {issue_id:'cn1', gt_label:'无需协助', media_status:'ready', annotations:[model],
    predictions:[{model_run_id:'run', model_label:'误触发', confidence:0.69}],
    label_state:{state:'resolved', expected_output:'误触发', gt_relation:'differs_from_gt',
      sources:hasProjection ? [{revision_summaries:[revision]}] : []},
    review_assignment:{assigned:true, split_id:'task', purpose:'model_review', workflow_mode:'model_review_and_case_label',
      model_run_id:'run', mode:'single'}};
  window.fixtureContext = {assigned:true, issue:{issue_id:'cn1'}, campaign:{id:'task', evaluation_run_id:'run'},
    case_revision:revision, model_review:model, case_revision_id:201, model_review_storage_id:101,
    label_state:fixtureData.label_state};
  api = async path => {
    if(path.includes('combined-review-context')) return new Promise((resolve,reject) => {window.resolveContext = resolve; window.rejectContext = reject;});
    return {};
  };
  state.selectedCase = fixtureData;
  setReviewView('cn1'); renderDetail(fixtureData); renderReview(fixtureData); bindMobileWorkbench();
}"""


def run():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.set_default_timeout(6000)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route("http://review-hydration.test/**", lambda route: route.fulfill(status=200, content_type="text/html", body=html))
        page.goto("http://review-hydration.test/manual/review")
        for name in styles:
            page.add_style_tag(content=(ROOT / name).read_text())
        for name in modules:
            override = Path(os.environ.get("REVIEW_HYDRATION_SOURCE_ROOT", "/nonexistent")) / name
            page.add_script_tag(content=(override if override.is_file() else ROOT / "js" / name).read_text())
        results = []
        for width in [320, 390, 1440]:
            page.set_viewport_size({"width": width, "height": 1000})
            for language in ["zh", "en"]:
                for theme in ["dark", "light"]:
                    page.evaluate(SETUP, {"catalog": catalog})
                    page.evaluate("([lang,theme]) => {applyUiLanguage(lang,{persist:false});applyColorTheme(theme,{persist:false});}", [language, theme])
                    assert page.locator('input[name="reviewTags"][value="u_turn"]').is_checked(), "saved Case tags must render before the context response"
                    assert "Saved U-turn rationale" in page.locator("#combinedCaseRationale").input_value()
                    note = page.locator("#annotationNote")
                    note.fill("Early edit / 提前修改模型说明")
                    page.evaluate("resolveContext({context:fixtureContext})")
                    page.wait_for_function("state.combinedReviewLoad?.status === 'ready'")
                    assert note.input_value() == "Early edit / 提前修改模型说明"
                    assert page.locator('input[name="reviewTags"][value="u_turn"]').is_checked()
                    assert "Saved U-turn rationale" in page.locator("#combinedCaseRationale").input_value()
                    draft_fields = page.evaluate("readReviewDraft('cn1','run','task','alice').edited_fields")
                    assert draft_fields == ["note"], draft_fields
                    page.evaluate("api=async()=>({context:fixtureContext});renderReview(fixtureData)")
                    page.wait_for_function("state.combinedReviewLoad?.status === 'ready'")
                    assert page.locator("#annotationNote").input_value() == "Early edit / 提前修改模型说明"
                    assert page.locator('input[name="reviewTags"][value="u_turn"]').is_checked()
                    assert page.locator("#reviewSaveButton").is_enabled()
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (width, language, theme, "overflow")
                    if (width, language, theme) in [(320, "en", "light"), (1440, "zh", "dark")]:
                        page.evaluate("scrollTo(0,0)")
                        page.screenshot(path=str(OUTPUT / f"review-{width}-{language}-{theme}.png"), full_page=True)
                    results.append({"width": width, "language": language, "theme": theme, "passed": True})

        # Even a prefetched core record without the label projection must hydrate
        # saved labels after a model-only edit while the context is delayed.
        page.evaluate(SETUP, {"catalog": catalog, "hasProjection": False})
        page.locator("#annotationNote").fill("Keep this new model note")
        page.evaluate("resolveContext({context:fixtureContext})")
        page.wait_for_function("state.combinedReviewLoad?.status === 'ready'")
        assert page.locator('input[name="reviewTags"][value="u_turn"]').is_checked()
        assert page.locator("#annotationNote").input_value() == "Keep this new model note"
        assert "Saved U-turn rationale" in page.locator("#combinedCaseRationale").input_value()

        # A context failure leaves saved fields visible and exposes a usable retry.
        page.evaluate(SETUP, {"catalog": catalog})
        page.evaluate("rejectContext(new Error('Synthetic timeout'))")
        page.wait_for_function("state.combinedReviewLoad?.status === 'error'")
        assert page.locator('input[name="reviewTags"][value="u_turn"]').is_checked()
        assert page.locator("#reviewSaveButton").is_disabled()
        page.evaluate("api=async()=>({context:fixtureContext})")
        page.locator("[data-retry-combined-context]").click()
        page.wait_for_function("state.combinedReviewLoad?.status === 'ready'")
        assert page.locator("#reviewSaveButton").is_enabled()

        # Intentional clears through the existing chip/textarea interactions
        # remain edits after rerender and a fresh server context response.
        page.locator('[data-remove-review-tag="u_turn"]').click()
        page.locator("#combinedCaseRationale").fill("")
        page.evaluate("renderReview(fixtureData)")
        page.wait_for_function("state.combinedReviewLoad?.status === 'ready'")
        assert not page.locator('input[name="reviewTags"][value="u_turn"]').is_checked()
        assert page.locator("#combinedCaseRationale").input_value() == ""

        assert not errors, errors
        report = {"browser": browser.version, "fixture": "actual shell/modules/styles with synthetic APIs",
                  "combinations": results, "errors": errors,
                  "additional": ["delayed context without core projection", "error state and retry", "intentional tag/rationale clears"]}
        (OUTPUT / "browser-results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(json.dumps(report, ensure_ascii=False))
        browser.close()


if __name__ == "__main__":
    run()
