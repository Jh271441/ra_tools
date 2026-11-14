import React from 'react';
import { createRoot } from 'react-dom/client';
import i18n from '../src/i18n';
import '../src/index.css';
import { Overview } from '../src/components/Overview';
import type { CollectionScope, KpiSummary, SummaryResponse } from '../src/types';

// Synthetic preview only: rendering and local button feedback never call an API.
const params=new URLSearchParams(location.search);
await i18n.changeLanguage(params.get('lang') || 'zh');
document.documentElement.classList.toggle('dark',params.get('theme')==='dark');
const collection:CollectionScope={available:false,reason_code:params.get('reason') || 'collecting',collection_status:'collecting',collected_issue_count:751,auto_count:598,manual_count:153,evaluated_issue_count:1,observed_at:'2026-11-15T01:06:00+08:00'};
const base:KpiSummary={version_key:'gen4-release-20261030',label:'release20261030',total_cases:1489,road_positive_cases:1489,sim_positive_cases:1200,reproduced_cases:1320,sim_repro_rate:.886,precision:.799,recall:.765,f1:.782,specificity:.1,accuracy:.7,model_repro_rate:0,fn_fallback_rate:0,fp_suppress_rate:0,positive_auto_repro_rate:.91,negative_auto_repro_rate:.86,positive_manual_repro_rate:.77,evaluated_cases:1485,dpe_coverage:.997,quality_gate_passed:true,root_causes:{},source_gt:{total_scenarios:1489,auto_trigger_tp:939,auto_trigger_fp:274,manual_trigger_fn:276,online_precision:.774,online_recall:.773},sim_estimate:{data_source:'shared_execution',estimated_tp:927,estimated_fn:284,estimated_fp:233,same_version_projection:{available:true,population_coverage:.997,sim_precision:.799,sim_business_recall:.765}}};
const pending:KpiSummary={...base,version_key:'gen4-release-20261106',label:'release20261106',total_cases:751,evaluated_cases:1,collection_scope:collection,root_causes:{},source_gt:null,precision:null,recall:null,f1:null,sim_repro_rate:null,quality_gate_passed:false,sim_estimate:{data_source:'collection_pending',job_id:49750139,estimated_tp:null,estimated_fn:null,estimated_fp:null,same_version_projection:{available:false}}};
const summary:SummaryResponse={business_current_version:pending.version_key,business_metrics:null,business_collection:collection,business_status:'collecting',current:null,legacy_current:base,previous:base,deltas:{},generated_at:collection.observed_at!};
createRoot(document.getElementById('root')!).render(<main className="mx-auto max-w-7xl p-3 md:p-5"><Overview summary={summary} comparison={[base,pending]} onOpenCurrent={()=>{}} onOpenIssues={()=>{}} /></main>);
