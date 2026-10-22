"""Behavioral regression for source-bound Issue tags and safe read-only rendering."""
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SharedLabelSourceRenderingTest(unittest.TestCase):
    def test_tags_are_grouped_per_revision_and_legacy_values_remain_visible(self) -> None:
        script = (ROOT / "static/js/review-label-state.js").read_text() + r'''
const assert=require('node:assert/strict');
let language='zh';
uiText=(zh,en)=>language==='en'?en:zh;
t=(key)=>key;
escapeHtml=(value)=>String(value).replace(/[&<>"']/g,(c)=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
reviewTagCatalogItem=(key)=>({queue:{section:'interaction_decision',group:'false_trigger'},road:{section:'scene',group:'environment'}}[key]);
tagLabel=(key)=>({queue:'排队误触发场景',road:'道路施工'}[key]||key.replace(/^custom:/,''));
labelBadge=(value,fallback)=>`<span>${escapeHtml(value||fallback)}</span>`;
formatTime=(value)=>escapeHtml(value);
state={session:{}};
const source={state:'resolved',result_revision_id:4,revision_summaries:[
 {id:3,expected_output:'正确触发',author:'alice',tags:['road'],rationale:'one'},
 {id:4,expected_output:'误触发',author:'bob',tags:['queue','queue','custom:<unsafe>'],rationale:'<script>bad</script>\nTwo',is_excluded:true,created_at:'2026-10-22T01:00:00Z'}
]};
const rendered=sharedLabelStateSourceMarkup(source,'cn1');
const first=rendered.split('class="shared-label-revision"')[1];
const second=rendered.split('class="shared-label-revision"')[2];
assert.match(first,/道路施工/); assert.doesNotMatch(first,/排队误触发场景/);
assert.match(second,/排队误触发场景/); assert.doesNotMatch(second,/道路施工/);
assert.equal((second.match(/排队误触发场景/g)||[]).length,1);
assert.match(second,/data-tag-group="false_trigger"/);
assert.match(second,/其他标签/); assert.match(second,/&lt;unsafe&gt;/);
assert.match(second,/&lt;script&gt;bad&lt;\/script&gt;/); assert.doesNotMatch(second,/<script>/);
assert.match(second,/结果依据/); assert.match(second,/已排除此 Issue/);
assert.doesNotMatch(rendered,/<input|<button/);
assert.match(sharedLabelRevisionTagsMarkup({tags:[]}),/此版本未填写/);
assert.match(sharedLabelRevisionTagsMarkup({}),/未提供/);
const summary=sharedLabelStateButtonMarkup({issue_id:'cn1',label_state:{state:'resolved',sources:Array(100).fill({})}}, {showEmpty:true,summaryOnly:true});
assert.match(summary,/标签汇总/); assert.doesNotMatch(summary,/来源 100|GT 待复核|历史/);
assert.match(summary,/aria-haspopup="dialog"/);
const linked=sharedLabelStateSourceMarkup({...source,label_case_id:'label-hash-123'},'cn1',{
 combined_reviews:[{task_id:'campaign-rawhash',task_name:'10/16 联合复核',run_id:'run-rawhash',run_name:'10/16 完整版',revision_id:4,submission_id:'submission-rawhash'}]
});
const visible=linked.split('<details')[0];
assert.match(visible,/联合复核标签/);assert.match(visible,/10\/16 联合复核/);assert.match(visible,/10\/16 完整版/);
assert.doesNotMatch(visible,/label-hash|campaign-rawhash|run-rawhash|自由修正|Standalone correction/);
assert.match(linked,/<details/);assert.match(linked,/submission-rawhash/);
language='en';
const english=sharedLabelRevisionMarkup({id:9,tags:[],author:'bob'},{});
assert.match(english,/No Issue tags recorded/); assert.match(english,/No rationale recorded/);
assert.match(english,/Author/); assert.doesNotMatch(english,/标注说明/);
'''
        subprocess.run(["node"], input=script, text=True, check=True, capture_output=True)
