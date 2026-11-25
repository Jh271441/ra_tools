from pathlib import Path
import shutil
import subprocess
import unittest


class LabelingIssueExportTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node required")
    def test_all_pages_filter_snapshot_duplicates_and_incomplete_guard(self):
        source = Path(__file__).resolve().parents[1] / "static/js/case-labeling.js"
        script = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
let calls=[],blobs=[],downloads=[],release,block=true,bad=false;
const ids=Array.from({length:31},(_,i)=>'cn'+(i+1));
Object.assign(global,{$:()=>null,state:{caseLabeling:{search:'junction',taskId:'task',issueIds:['cn1','cn2'],status:['resolved'],author:['alice'],assignee:['bob'],cluster:'reason-key',exclusion:['excluded'],label:['误触发'],gt:['正确触发'],commentState:['with'],page:2,pageSize:20,data:{total:31}}},DEFAULT_CASE_PAGE_SIZE:20,joinFilterList:x=>(x||[]).join(','),selectedBaselineQueryValue:()=> '0508,0821',uiText:(zh,en)=>en,showToast(){},window:{setTimeout(){}},document:{body:{appendChild(){}},createElement:()=>({click(){downloads.push(this.download)},remove(){}})},api:async url=>{calls.push(url);if(block)await new Promise(r=>release=r);return {total:31,items:ids.slice(0,10).map(issue_id=>({issue_id})),queue_issue_ids:bad?ids.slice(0,10):ids}}});
URL.createObjectURL=blob=>{blobs.push(blob);return 'blob:fixture'};
vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));selectedActiveLabelingBaselineIds=()=>['0508'];
(async()=>{
 const first=exportCaseLabelingIssues();await exportCaseLabelingIssues();assert.equal(calls.length,1);
 const p=new URL(calls[0],'http://local').searchParams;
 for(const [key,value] of Object.entries({baselines:'0508,0821',task_id:'task',q:'junction',issue_ids:'cn1,cn2',status:'resolved',author:'alice',assignee:'bob',cluster:'reason-key',exclusion:'excluded',label:'误触发',gt:'正确触发',comment_state:'with',page:'1',page_size:'10'}))assert.equal(p.get(key),value);
 state.caseLabeling.search='changed while exporting';release();await first;
 assert.equal(downloads[0],'labeling-issues-31.csv');assert.equal((await blobs[0].text()).trim().split('\r\n').length,32);assert.equal(state.caseLabeling.page,2);assert.equal(state.caseLabeling.exportingIssues,false);
 block=false;bad=true;await assert.rejects(exportCaseLabelingIssues(),/complete Issue list/);assert.equal(downloads.length,1);assert.equal(state.caseLabeling.exportingIssues,false);
})().catch(e=>{console.error(e);process.exitCode=1});
"""
        result = subprocess.run(["node", "-e", script, str(source)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
