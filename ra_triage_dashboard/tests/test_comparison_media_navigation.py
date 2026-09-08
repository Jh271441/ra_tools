import subprocess
from pathlib import Path


def test_comparison_media_case_navigation_and_page_boundaries():
    script=Path('ra_triage_dashboard/static/js/media-dialog.js').read_text()+'''
const assert=require('node:assert/strict');
const state={activePage:'comparison',media:{snapshot:{referenceMedia:true,issueId:'a'},kind:'camera'},runComparison:{data:{page:1,page_count:2,items:[{issue_id:'a'},{issue_id:'b'}]}}};
const $=()=>({open:false});
let opened=[];let notices=[];
showToast=(x)=>notices.push(x);
openComparisonMedia=async(id,kind)=>{opened.push([id,kind]);state.media.snapshot.issueId=id;};
loadRunComparison=async()=>{state.runComparison.data={page:2,page_count:2,items:[{issue_id:'c'}]};};
(async()=>{
 await navigateComparisonMediaCase(1);assert.deepEqual(opened[0],['b','camera']);
 await navigateComparisonMediaCase(1);assert.deepEqual(opened[1],['c','camera']);assert.equal(state.runComparison.page,2);
 await navigateComparisonMediaCase(1);assert.equal(opened.length,2);assert.ok(notices.length);
})();
'''
    subprocess.run(['node','-e',script],check=True,capture_output=True)
