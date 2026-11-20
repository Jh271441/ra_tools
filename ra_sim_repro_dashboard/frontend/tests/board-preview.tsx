import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { useTranslation } from 'react-i18next';
import '../src/i18n';
import '../src/index.css';
import { ReleaseWorkflow, type BoardData } from '../src/components/ReleaseWorkflow';
import { Button } from '../src/components/ui/button';

let fail = false;
let reads = 0;
let writes = 0;
let mode: 'manual' | 'auto' = 'auto';
const versions = ['gen4-release-20261023','gen4-release-20261016','gen4-release-20261009'];
function fixture(release: string): BoardData {
  return {
    versions: versions.map(release => ({release,is_current:release===versions[1],cycle_status:'completed',has_job:false})),
    mode,driver_ready:true,scheduler_enabled:true,current_status:'ready',refreshing:false,
    selected:{release:release==='@current'?versions[1]:release,is_current:release==='@current'||release===versions[1],kind:'current',period:null,population_complete:true,
      issue_count:10,scenario_count:10,source_metrics:{online_precision:.8,online_recall:.7,eligible:10,excluded:0},
      metrics:{available:false},binary_id:123,synced_at:null,jobs:[],resume:{enabled:true,status:'running',checkpoint:'prepare'},
      label_cycle:{enabled:true,status:'checking',pending_count:0,check_seconds:3600,merge_seconds:21600},
      backfill:{enabled:true,status:'syncing',interval_seconds:21600,pending_count:1},
    },
  };
}
// Fixture-only transport: writes are counted locally and never reach an API.
window.fetch = async (input, init) => {
  const url = new URL(String(input), location.href);
  if (!url.pathname.startsWith('/sim/api/dashboard/workflow')) throw new Error('fixture transport only');
  if (init?.method && init.method !== 'GET') { writes++; mode = JSON.parse(String(init.body)).mode || mode; return Response.json({status:'ok'}); }
  reads++;
  await new Promise(resolve => setTimeout(resolve, 700));
  if (fail) return new Response('<html>Gateway timeout</html>', {status:504});
  return Response.json(fixture(url.searchParams.get('release') || '@current'));
};
function Preview() {
  const { i18n } = useTranslation();
  const [dark,setDark] = useState(false);
  const [failed,setFailed] = useState(false);
  const [counts,setCounts] = useState('');
  return <main className="mx-auto max-w-6xl space-y-4 p-4">
    <nav className="flex flex-wrap gap-2" aria-label="QA tools">
      <Button onClick={()=>void i18n.changeLanguage(i18n.language==='zh'?'en':'zh')}>中文 / English</Button>
      <Button onClick={()=>{setDark(!dark);document.documentElement.classList.toggle('dark',!dark);}}>Theme</Button>
      <Button onClick={()=>{fail=!fail;setFailed(fail);}}>API {failed?'failure':'success'}</Button>
      <Button onClick={()=>setCounts(`Reads ${reads} · Writes ${writes}`)}>Request counts</Button>
      <output>{counts}</output>
    </nav>
    <ReleaseWorkflow onOpenIssues={()=>{}}/>
  </main>;
}
createRoot(document.getElementById('root')!).render(<Preview/>);
