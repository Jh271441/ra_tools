/* Report tables consume the exact summaries used by the cross-version chart. */
function vmVersionPage(rows,page=1,pageSize=DEFAULT_CASE_PAGE_SIZE){
  const size=CASE_PAGE_SIZES.includes(pageSize)?pageSize:DEFAULT_CASE_PAGE_SIZE;
  const ordered=[...rows].sort((a,b)=>b.family.localeCompare(a.family)),pages=Math.max(1,Math.ceil(ordered.length/size));
  const current=Number.isSafeInteger(page)?Math.max(1,Math.min(page,pages)):1;
  return {items:ordered.slice((current-1)*size,current*size),total:ordered.length,page:current,pageSize:size,pages};
}
function vmReconcileReports(){
  const s=versionMetrics;if(!Array.isArray(s.data?.items))return;
  const page=vmVersionPage(s.data.items,s.page,s.pageSize);s.page=page.page;s.pageSize=page.pageSize;
  if(!s.data.items.some(row=>row.family===s.thresholdFamily))s.thresholdFamily=[...s.data.items].sort((a,b)=>b.family.localeCompare(a.family))[0]?.family||'';
}
function vmFamilyLabel(family){return family.slice(4,6)+'-'+family.slice(6);}
function vmReferenceLabel(){return ({te:uiText('TE 原始标注','Original TE'),rd:uiText('RD 标注','RD labels'),te_prime:uiText('TE′ 人工标注','Manual TE′'),arbitrated:uiText('裁决结果','Adjudication')})[versionMetrics.reference];}
function vmCountRate(count,total){
  if(!total)return '<span>—</span>';
  return `<strong>${count}/${total}</strong><small>${vmPct(count/total)}</small>`;
}
function vmScoreCell(row,key){
  const m=row.metrics?.[key],value=vmValue(row,key);if(!m)return '<span>—</span>';
  let counts='';const label=vmClass(versionMetrics.metric),klass=label?m.per_class.find(item=>item.label===label):null;
  if(versionMetrics.metric==='accuracy')counts=`${m.correct}/${m.total}`;
  else if(klass)counts=`${klass.tp}/${klass.support}`;
  else if(versionMetrics.metric==='human_share')counts=`${m.human_count}/${m.total}`;
  else counts=`n=${m.total}`;
  const coverage=uiText(`模型输出覆盖 ${m.total}/${m.reference_total}`,`Output coverage ${m.total}/${m.reference_total}`);
  return `<strong title="${escapeHtml(coverage)}">${vmPct(value)}</strong><small>${escapeHtml(counts)}</small>`;
}
function vmCoverageCell(row,lane){
  const coverage=row.coverage?.[lane];if(!coverage)return '<span>—</span>';
  const known=uiText(`已观测 ${coverage.observed}/${coverage.total}；已标包含 OOS 和未接起`,`Observed ${coverage.observed}/${coverage.total}; filled includes OOS and unanswered`);
  if(!coverage.observed&&coverage.total)return `<span title="${escapeHtml(known)}">${uiText('未知','Unknown')}</span>`;
  return `<span class="vm-cell-stack" title="${escapeHtml(known)}">${vmCountRate(coverage.filled,coverage.total)}</span>`;
}
function vmReportEmpty(message,columns){return `<tr><td colspan="${columns}" class="vm-table-empty">${escapeHtml(message)}</td></tr>`;}
function vmFreshnessSummary(rows){
  const times=rows.filter(row=>row.status==='ready').map(row=>new Date(row.observed_at)).filter(date=>Number.isFinite(date.getTime())).sort((a,b)=>a-b);
  if(!times.length)return {label:uiText('Trail · 待采集','Trail · Not collected'),title:uiText('点击更新指标，读取新的 Trail 快照','Update metrics to collect a new Trail snapshot')};
  const oldest=vmTime(times[0]),newest=vmTime(times[times.length-1]);
  return {label:'Trail · '+oldest,title:uiText(`所选版本最早／最新采集完成时间：${oldest} / ${newest} CST。快照不是持续实时数据；点击更新指标重新采集。`,`Earliest / latest completed collection: ${oldest} / ${newest} CST. Snapshots are not continuously live; update metrics to collect again.`)};
}
function vmRenderReports(){
  const s=versionMetrics,root=$('#versionMetricsPage');vmReconcileReports();
  root.querySelectorAll('[data-vm-aria-zh]').forEach(el=>el.setAttribute('aria-label',uiText(el.dataset.vmAriaZh,el.dataset.vmAriaEn)));
  $('#vmReferenceNote').textContent=uiText('评测参考：','Reference: ')+vmReferenceLabel()+' · '+uiText(s.exclusion==='exclude'?'剔除人工排除项':'全部三分类有效',s.exclusion==='exclude'?'Manual exclusions removed':'All valid samples');
  $('#vmSchemeDefinitions').innerHTML=VM_SCHEMES.map(key=>escapeHtml(vmSchemeShort(key)+' → '+vmScheme(key))).join('<br>');
  const freshness=vmFreshnessSummary(s.data?.items||[]);$('#vmDataFreshness').textContent=freshness.label;$('#vmDataFreshness').title=freshness.title;
  $('#vmSnapshotInfo').innerHTML=(s.data?.items||[]).filter(row=>row.status==='ready').map(row=>escapeHtml(row.family+' · '+uiText('采集','Collected')+' '+vmTime(row.started_at||row.observed_at)+' – '+vmTime(row.observed_at)+' CST')).join('<br>')||uiText('暂无 Trail 快照','No Trail snapshots');
  const page=vmVersionPage(s.data?.items||[],s.page,s.pageSize),busy=s.loading||Boolean(s.error),disabled=busy||!page.total;
  $('#vmTableMetric').textContent=vmMetric(s.metric);$('#vmReportTable').setAttribute('aria-label',uiText('各版本五方案指标','Five-scheme release metrics')+' · '+vmMetric(s.metric));
  $('#vmReportHead').innerHTML=`<tr><th scope="col">${uiText('版本','Release')}</th><th scope="col">${uiText('有效／抽样','Valid / sample')}</th><th scope="col">${uiText('TE 已标','TE filled')}</th><th scope="col">${uiText('RD 已标','RD filled')}</th>`+VM_SCHEMES.map(key=>`<th scope="col" title="${escapeHtml(vmScheme(key))}">${escapeHtml(vmSchemeShort(key))}</th>`).join('')+'</tr>';
  const empty=s.error?uiText('指标读取失败，请重试','Metrics unavailable. Please retry.'):s.loading?uiText('正在读取指标…','Loading metrics…'):uiText('暂无版本数据','No release data');
  $('#vmReportRows').innerHTML=busy||!page.items.length?vmReportEmpty(empty,9):page.items.map(row=>{
    const date=`<th scope="row" title="${escapeHtml('release-'+row.family+' · '+vmTime(row.observed_at)+' CST')}"><strong>${vmFamilyLabel(row.family)}</strong>${row.membership_changed?`<small>${uiText('版本已变化','Membership changed')}</small>`:''}</th>`;
    if(row.status!=='ready')return `<tr>${date}<td colspan="8" class="vm-table-empty">${row.status==='error'?uiText('Trail 快照不可用，请更新指标','Trail snapshot unavailable. Update metrics.'):uiText('暂无 Trail 快照，请更新指标','No Trail snapshot. Update metrics.')}</td></tr>`;
    return `<tr>${date}<td><strong>${row.valid_total}/${row.sample_total}</strong></td><td>${vmCoverageCell(row,'te')}</td><td>${vmCoverageCell(row,'rd')}</td>`+VM_SCHEMES.map(key=>`<td>${vmScoreCell(row,key)}</td>`).join('')+'</tr>';
  }).join('');
  $('#vmPageLabel').textContent=busy?'— / —':uiText(`${page.page} / ${page.pages} · 共 ${page.total} 个版本`,`${page.page} / ${page.pages} · ${page.total} ${page.total===1?'release':'releases'}`);
  $('#vmPagePrevious').disabled=disabled||page.page===1;$('#vmPageNext').disabled=disabled||page.page===page.pages;
  const jump=$('#vmPageJump');jump.value=String(page.page);jump.max=String(page.pages);jump.disabled=$('#vmPageJumpButton').disabled=disabled;
  $('#vmPageSize').disabled=disabled;vmSelect('vmPageSize',CASE_PAGE_SIZES.map(size=>[size,String(size)]),s.pageSize);
  vmRenderThresholdReport();
}
function vmRenderThresholdReport(){
  const s=versionMetrics,rows=[...(s.data?.items||[])].sort((a,b)=>b.family.localeCompare(a.family)),panel=$('#vmThresholdAnalysis');
  panel.open=s.thresholdExpanded;$('#vmThresholdFamily').disabled=s.loading||Boolean(s.error)||!rows.length;
  vmSelect('vmThresholdFamily',rows.map(row=>[row.family,row.family.slice(0,4)+' / '+vmFamilyLabel(row.family)]),s.thresholdFamily);
  const row=rows.find(item=>item.family===s.thresholdFamily),available=row?.status==='ready';
  $('#vmThresholdScope').textContent=available?uiText(`已回刷全量 ${row.published_total} · 有效抽样 ${row.valid_total}`,`Published population ${row.published_total} · Valid samples ${row.valid_total}`):'';
  if(!s.thresholdExpanded)return;
  const error=s.error?uiText('指标读取失败，请重试','Metrics unavailable. Please retry.'):s.loading?uiText('正在读取指标…','Loading metrics…'):uiText('当前版本暂无有效快照','No valid snapshot for this release');
  $('#vmThresholdRows').innerHTML=!available||s.loading||s.error?vmReportEmpty(error,5):(row.thresholds||[]).map(t=>`<tr${t.threshold===s.threshold?' class="is-selected" aria-current="true"':''}><th scope="row">${t.threshold.toFixed(2)}</th><td>${vmCountRate(t.full_low,t.full_total)}</td><td>${t.reduction}</td><td>${vmCountRate(t.human_count,t.total)}</td><td><strong>${vmPct(t.accuracy)}</strong><small>${t.correct}/${t.total}</small></td></tr>`).join('');
}
function vmJumpReportPage(){
  const input=$('#vmPageJump'),value=Number(input.value);if(input.disabled)return;
  if(!input.value.trim()||!Number.isSafeInteger(value)){input.setCustomValidity(uiText('请输入整数页码','Enter a whole page number'));input.reportValidity();return;}
  input.setCustomValidity('');const page=vmVersionPage(versionMetrics.data?.items||[],value,versionMetrics.pageSize);vmChange({page:page.page},{local:true});
}
function vmBindReports(){
  $('#vmPagePrevious').addEventListener('click',()=>vmChange({page:versionMetrics.page-1},{local:true}));
  $('#vmPageNext').addEventListener('click',()=>vmChange({page:versionMetrics.page+1},{local:true}));
  $('#vmPageJumpButton').addEventListener('click',vmJumpReportPage);
  $('#vmPageJump').addEventListener('input',event=>event.target.setCustomValidity(''));
  $('#vmPageJump').addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();vmJumpReportPage();}});
  $('#vmPageSize').addEventListener('change',event=>{const size=Number(event.target.value);if(CASE_PAGE_SIZES.includes(size))vmChange({pageSize:size,page:1},{local:true});});
  $('#vmThresholdFamily').addEventListener('change',event=>vmChange({thresholdFamily:event.target.value},{local:true}));
  $('#vmThresholdAnalysis').addEventListener('toggle',event=>{if(versionMetrics.active&&event.target.open!==versionMetrics.thresholdExpanded)vmChange({thresholdExpanded:event.target.open},{local:true});});
}
