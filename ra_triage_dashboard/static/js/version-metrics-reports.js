/* Report tables consume the exact summaries used by the cross-version chart. */
const VM_REPORT_IDS={20261009:'2210331546058',20261016:'2210331433301',20261023:'2210462491274',20261030:'2210502394530'};
function vmReportLink(family, reportId){
  const id=/^[0-9]{1,20}$/.test(reportId||'')?reportId:VM_REPORT_IDS[family];if(!id)return '';
  const label=uiText(`查看 ${family} 版本报告（新标签页）`,`Open ${family} release report (new tab)`);
  return `<a class="text-link vm-report-link" href="https://cooper.didichuxing.com/didocs/${id}" target="_blank" rel="noopener noreferrer" aria-label="${escapeHtml(label)}" title="${escapeHtml(label)}">${uiText('报告','Report')}</a>`;
}
function vmReconcileReports(){
  const s=versionMetrics;if(!Array.isArray(s.data?.items))return;
  if(!s.data.items.some(row=>row.family===s.thresholdFamily))s.thresholdFamily=[...s.data.items].sort((a,b)=>b.family.localeCompare(a.family))[0]?.family||'';
}
function vmFamilyLabel(family){return family.slice(4,6)+'-'+family.slice(6);}
function vmReferenceLabel(reference=versionMetrics.reference){return ({release:uiText('按版本取人工 GT','Release-specific human GT'),te:uiText('TE 原始标注','Original TE'),rd:uiText('RD 标注','RD labels'),te_prime:uiText('TE′ 人工标注','Manual TE′'),arbitrated:uiText('裁决结果','Adjudication')})[reference];}
function vmReferenceCounts(row){
  const names={arbitrated:uiText('复核','Adjudication'),te_prime:'TE′',te:'TE',rd:'RD'};
  return (row.reference_lanes||[]).map(lane=>names[lane]+' '+row.reference_counts[lane]).join(' · ');
}
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
function vmSampleChange(row){
  if(!Number.isInteger(row.current_sample_total) || row.current_sample_total===row.sample_total)return '';
  return uiText(`当前抽样 ${row.current_sample_total}`,`Current sample ${row.current_sample_total}`);
}
function vmCoverageCell(row,lane){
  const coverage=row.coverage?.[lane];if(!coverage)return '<span>—</span>';
  const known=uiText(`已观测 ${coverage.observed}/${coverage.total}；已标包含 OOS 和未接起`,`Observed ${coverage.observed}/${coverage.total}; filled includes OOS and unanswered`);
  if(!coverage.observed&&coverage.total)return `<span title="${escapeHtml(known)}">${uiText('未知','Unknown')}</span>`;
  return `<span class="vm-cell-stack" title="${escapeHtml(known)}">${vmCountRate(coverage.filled,coverage.total)}</span>`;
}
function vmReportEmpty(message,columns){return `<tr><td colspan="${columns}" class="vm-table-empty">${escapeHtml(message)}</td></tr>`;}
function vmWorkloadRow(label, point, byThreshold) {
  const selected = byThreshold && point?.threshold === versionMetrics.threshold;
  const header = `<th scope="row">${escapeHtml(label)}</th>`;
  if (!point) {
    return `<tr>${header}<td colspan="3" class="vm-table-empty">${uiText('暂无阈值数据','No threshold data')}</td></tr>`;
  }
  const baseline = point.full_low + point.reduction;
  const reductionRate = baseline ? vmPct(point.reduction / baseline, 1) : '—';
  const sample = byThreshold ? `<td>${vmCountRate(point.human_count, point.total)}</td>` : '';
  const share = byThreshold && point.full_total ? `<small>${vmPct(point.full_low / point.full_total)}</small>` : '';
  return `<tr${selected ? ' class="is-selected" aria-current="true"' : ''}>${header}
    <td><strong>${point.full_low} / ${point.full_total}</strong>${share}</td>
    <td><strong>${point.reduction}</strong><small>${reductionRate}</small></td>${sample}
    <td><strong>${vmPct(point.accuracy)}</strong><small>${point.correct}/${point.total}</small></td></tr>`;
}
function vmRenderWorkload(rows, empty) {
  const s = versionMetrics, byThreshold = s.thresholdExpanded;
  const scope = byThreshold ? rows.filter(row => row.family === s.thresholdFamily) : rows;
  const counts = scope.map(row => row.status === 'ready' ? row.thresholds?.find(t => t.threshold === .90)?.full_low : null);
  const complete = counts.length > 0 && counts.every(Number.isInteger);
  const total = complete ? counts.reduce((sum, count) => sum + count, 0).toLocaleString(i18nLocale()) : '—';
  const label = scope.length > 1 ? uiText('标注量合计', 'total reviews') : uiText('标注量', 'reviews');
  $('#vmWorkloadBaseline').textContent = `conf = 0.90 ${label} ${total}`;
  $('#vmWorkloadThreshold').textContent = vmThresholdText();
  $('#vmWorkloadDimension').textContent = byThreshold ? 'conf' : uiText('版本','Release');
  $('#vmWorkloadReleasePicker').hidden = !byThreshold;
  $('#vmWorkloadSampleHead').hidden = !byThreshold;
  $('#versionMetricsPage').querySelectorAll('[name="vmWorkloadMode"]').forEach(input => {
    input.checked = input.value === (byThreshold ? 'threshold' : 'release');
  });
  const body = $('#vmWorkloadRows');
  if (!byThreshold) {
    body.innerHTML = rows.map(row => vmWorkloadRow(row.family,
      row.status === 'ready' && row.thresholds?.find(t => t.threshold === s.threshold), false)
    ).join('') || vmReportEmpty(empty, 4);
    return;
  }
  const row = rows.find(item => item.family === s.thresholdFamily);
  $('#vmThresholdFamily').disabled = !rows.length;
  vmSelect('vmThresholdFamily', rows.map(row => [row.family, row.family]), s.thresholdFamily);
  const points = row?.status === 'ready' ? row.thresholds : [];
  body.innerHTML = points?.map(t => vmWorkloadRow(t.threshold.toFixed(2), t, true)).join('')
    || vmReportEmpty(rows.length ? uiText('当前版本暂无阈值数据','No threshold data for this release') : empty, 5);
}
function vmFreshnessSummary(rows){
  const times=rows.filter(row=>row.status==='ready').map(row=>new Date(row.observed_at)).filter(date=>Number.isFinite(date.getTime())).sort((a,b)=>a-b);
  if(!times.length)return {label:uiText('Trail · 待采集','Trail · Not collected'),title:uiText('点击更新指标，读取新的 Trail 快照','Update metrics to collect a new Trail snapshot')};
  const oldest=vmTime(times[0]),newest=vmTime(times[times.length-1]);
  return {label:uiText('最早快照','Oldest snapshot')+' · '+oldest,title:uiText(`所选版本最早／最新采集完成时间：${oldest} / ${newest} CST。版本调度会自动核对，也可手动更新。`,`Earliest / latest completed collection: ${oldest} / ${newest} CST. The version scheduler checks automatically. A manual refresh is also available.`)};
}
function vmRenderReports(){
  const s=versionMetrics,root=$('#versionMetricsPage');vmReconcileReports();
  root.querySelectorAll('[data-vm-aria-zh]').forEach(el=>el.setAttribute('aria-label',uiText(el.dataset.vmAriaZh,el.dataset.vmAriaEn)));
  $('#vmReferenceNote').textContent=uiText('评测参考：','Reference: ')+vmReferenceLabel()+' · '+uiText(s.exclusion==='exclude'?'剔除人工排除项':'全部三分类有效',s.exclusion==='exclude'?'Manual exclusions removed':'All valid samples');
  $('#vmChartReference').textContent=s.reference==='release'
    ?uiText('11-06 起，GT 按复核 → TE′ → TE → RD 取值。此前版本使用 TE。','From Nov 6, GT uses the first entry in this order: adjudication → TE′ → TE → RD. Earlier releases use TE.')
    :'GT · '+vmReferenceLabel();
  $('#vmSchemeDefinitions').innerHTML=VM_SCHEMES.map(key=>escapeHtml(vmSchemeShort(key)+' → '+vmScheme(key))).join('<br>');
  const freshness=vmFreshnessSummary(s.data?.items||[]);$('#vmDataFreshness').textContent=freshness.label;$('#vmDataFreshness').title=freshness.title;
  $('#vmSnapshotInfo').innerHTML=(s.data?.items||[]).filter(row=>row.status==='ready').map(row=>escapeHtml(row.family+' · '+uiText('采集','Collected')+' '+vmTime(row.started_at||row.observed_at)+' – '+vmTime(row.observed_at)+' CST')).join('<br>')||uiText('暂无 Trail 快照','No Trail snapshots');
  const rows=[...(s.data?.items||[])].reverse(),busy=s.loading||Boolean(s.error);
  $('#vmTableMetric').textContent=vmMetric(s.metric)+' · '+uiText('人工列为模拟值','Review columns are simulated');$('#vmReportTable').setAttribute('aria-label',uiText('各版本五方案指标','Five-scheme release metrics')+' · '+vmMetric(s.metric));
  $('#vmReportHead').innerHTML=`<tr><th scope="col">${uiText('版本','Release')}</th><th scope="col">${uiText('有效／抽样','Valid / sample')}</th><th scope="col">${uiText('有效 GT 来源','Valid GT sources')}</th><th scope="col">${uiText('TE 已标','TE filled')}</th><th scope="col">${uiText('RD 已标','RD filled')}</th>`+VM_SCHEMES.map(key=>`<th scope="col" title="${escapeHtml(vmScheme(key))}">${escapeHtml(vmSchemeShort(key))}</th>`).join('')+'</tr>';
  const empty=s.error?uiText('指标读取失败，请重试','Metrics unavailable. Please retry.'):s.loading?uiText('正在读取指标…','Loading metrics…'):uiText('暂无版本数据','No release data');
  vmRenderWorkload(busy ? [] : rows, empty);
  $('#vmReportRows').innerHTML=busy||!rows.length?vmReportEmpty(empty,10):rows.map(row=>{
    const change=vmSampleChange(row);
    const date=`<th scope="row" title="${escapeHtml('release-'+row.family+' · '+vmTime(row.observed_at)+' CST')}"><strong>${vmFamilyLabel(row.family)}</strong>${vmReportLink(row.family,row.report_id)}${row.membership_changed?`<small>${uiText('版本已变化','Membership changed')}</small>`:''}</th>`;
    if(row.status!=='ready')return `<tr>${date}<td><strong>—/${row.current_sample_total ?? '—'}</strong></td><td colspan="8" class="vm-table-empty">${row.reason==='human_fields_required'?uiText('请更新指标以补齐人工 GT 字段','Update metrics to collect the missing human GT fields'):row.status==='error'?uiText('Trail 快照不可用，请更新指标','Trail snapshot unavailable. Update metrics.'):uiText('暂无 Trail 快照，请更新指标','No Trail snapshot. Update metrics.')}</td></tr>`;
    return `<tr>${date}<td><strong>${row.valid_total}/${row.sample_total}</strong>${change?`<small>${escapeHtml(change)}</small>`:''}</td><td>${escapeHtml(vmReferenceCounts(row))}</td><td>${vmCoverageCell(row,'te')}</td><td>${vmCoverageCell(row,'rd')}</td>`+VM_SCHEMES.map(key=>`<td>${vmScoreCell(row,key)}</td>`).join('')+'</tr>';
  }).join('');
}
function vmBindReports(){
  $('#vmThresholdFamily').addEventListener('change',event=>vmChange({thresholdFamily:event.target.value},{local:true}));
  $('#versionMetricsPage').addEventListener('change', event => {
    if (event.target.name === 'vmWorkloadMode') {
      vmChange({thresholdExpanded:event.target.value === 'threshold'}, {local:true});
    }
  });
}
