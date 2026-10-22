"""Daily dataset choices are presentation unions, never GT/task migrations."""
import subprocess
import unittest
from pathlib import Path


class BaselinePickerUnionsTest(unittest.TestCase):
    def test_counts_selection_and_partial_old_links_keep_real_scope_ids(self):
        source = (Path(__file__).resolve().parents[1] / "static/js/format-api.js").read_text()
        script = source + r'''
const assert=require('node:assert/strict');
state={baselineCatalog:[],config:{},selectedBaselineIds:[]};uiText=x=>x;
const catalog=[
 {id:'0508',label:'0508',count:1071},
 {id:'1009-2026-10-15',label:'1009 2026-10-15',count:30},
 {id:'1009-2026-10-16',label:'1009 2026-10-16',count:100},
 {id:'1009-2026-10-17',label:'1009 2026-10-17',count:75},
 {id:'review-2026-10-18',label:'每日复核 2026-10-18',count:74},
 {id:'review-2026-10-15-extra',label:'补齐15',count:3},
 {id:'review-2026-10-16-extra',label:'补齐16',count:12},
 {id:'review-2026-10-18-extra',label:'补齐18',count:16},
];
const original=JSON.stringify(catalog),allowed=new Set(catalog.map(x=>x.id));
assert.deepEqual(normalizeBaselineIds("1009-2026-10-15,review-2026-10-15-extra；",{allowed}),["1009-2026-10-15","review-2026-10-15-extra"]);
const options=baselinePickerOptions(catalog,['1009-2026-10-15','review-2026-10-15-extra']);
assert.equal(options.length,5);
assert.deepEqual(options.map(x=>x.label),['0508 · 1071','1009 2026-10-15 · 33','1009 2026-10-16 · 112','1009 2026-10-17 · 75','1009 2026-10-18 · 90']);
assert.deepEqual(normalizeBaselineIds(options.filter(x=>x.selected).map(x=>x.value),{allowed}),['1009-2026-10-15','review-2026-10-15-extra']);
const partial=baselinePickerOptions(catalog,['review-2026-10-15-extra'])[1];
assert(partial.partial);assert(partial.label.includes('3/33'));assert.equal(partial.value,'review-2026-10-15-extra');
assert.deepEqual(normalizeBaselineIds([partial.value],{allowed}),['review-2026-10-15-extra']);
assert.deepEqual(normalizeBaselineIds([partial.fullValue],{allowed}),['1009-2026-10-15','review-2026-10-15-extra']);
assert.equal(JSON.stringify(catalog),original);
const retired={id:'fill-2026-10-17-3e2cc9cfbd',label:'信息补齐',count:2};
assert.equal(baselinePickerOptions([...catalog,retired],[]).some(x=>x.value===retired.id),false);
const historical=baselinePickerOptions([...catalog,retired],[retired.id]).find(x=>x.value===retired.id);
assert(historical.selected);assert(historical.label.includes('历史'));

const missing=baselinePickerOptions(catalog.filter(x=>x.id!=='review-2026-10-15-extra'),['1009-2026-10-15']);
assert.equal(missing[1].value,'1009-2026-10-15');assert.equal(missing[1].label,'1009 2026-10-15 · 30');
'''
        subprocess.run(["node", "-e", script], check=True, capture_output=True)
