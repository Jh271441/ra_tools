/* Counts come only from the server's shared Manual Issue-label projection. */
function renderVersionRD(d=null, failed=false) {
  const el=document.getElementById('versionRDPanel'),s=versionDatasetState;
  if(!el)return;
  if(failed||d?.source_status==='unsupported'){el.innerHTML=`<p class="version-rd-empty">${failed?uiText('RD 标注暂不可用，请刷新重试','RD annotations unavailable; refresh to retry'):uiText('此历史固定集暂不提供 RD 统计','RD statistics are unavailable for this frozen historical set')}</p>`;return;}
  if(!d){el.innerHTML=`<p class="version-rd-empty">${uiText('正在读取 RD 标注…','Loading RD annotations…')}</p>`;return;}
  if(!d.total){el.innerHTML=`<p class="version-rd-empty">${uiText('当前范围暂无复核目标','No review targets in this scope')}</p>`;return;}
  const rate=(100*d.completed/d.total).toFixed(1);
  const categories=[['正确触发',uiText('正确触发','Correct trigger'),'rd-correct'],['误触发',uiText('误触发','False trigger'),'rd-false'],['无需协助',uiText('无需协助','No assistance needed'),'rd-assistance']];
  const scope=[versionDatasetScopeLabel(),s.date||uiText('全部日期','All dates')].join(' · ');
  const source=uiText('Manual 当前人工结论；冲突及需复核不计已标。分母为筛选范围内全部目标，不随 TE 状态或翻页改变。','Current Manual human conclusions; conflicts and rechecks are not labeled. Denominator: all filtered targets, independent of TE status and pagination.');
  const pending=uiText(`待标 ${d.pending} · 冲突待确认 ${d.conflict}`,`Pending ${d.pending} · Conflicts to resolve ${d.conflict}`);
  const markup=`<div class="version-rd-grid">
    <section class="page-card version-rd-block" aria-labelledby="versionRDProgressTitle">
      <header class="version-rd-header section-heading version-chart-heading">
        <h2 id="versionRDProgressTitle" title="${escapeHtml(source+' · '+scope)}">${uiText('RD 标注进度','RD labeling progress')}</h2>
        <div class="version-rd-legend version-rd-progress-legend" tabindex="0" role="group" aria-label="${escapeHtml(source+' '+uiText('RD 标注状态图例，可横向滚动','RD labeling status legend; scroll horizontally'))}">
          <span class="version-rd-category"><i class="rd-filled" aria-hidden="true"></i><span>${uiText('已标','Labeled')}</span><span>${d.completed} / ${d.total}</span></span>
          <span class="version-rd-category"><i class="rd-pending" aria-hidden="true"></i><span>${uiText('待标','Pending')}</span><span>${d.pending}</span></span>
          <span class="version-rd-category" title="${escapeHtml(uiText('冲突或来源已变更，需复核','Conflicting or changed sources; needs recheck'))}"><i class="rd-conflict" aria-hidden="true"></i><span>${uiText('冲突','Conflicts')}</span><span>${d.conflict}</span></span>
          <strong>${rate}%</strong>
        </div>
      </header>
      <div class="version-rd-track" role="progressbar" aria-valuemin="0" aria-valuemax="${d.total}" aria-valuenow="${d.completed}" aria-label="${escapeHtml(uiText('RD 标注完成率','RD annotation completion'))}" aria-valuetext="${escapeHtml(rate+'% · '+pending)}" title="${escapeHtml(pending)}"><i class="rd-filled" style="flex:${d.completed} 0 0"></i><i class="rd-pending" style="flex:${d.pending} 0 0"></i><i class="rd-conflict" style="flex:${d.conflict} 0 0"></i></div>
    </section>
    <section class="page-card version-rd-block" aria-labelledby="versionRDMixTitle">
      <header class="version-rd-header section-heading version-chart-heading">
        <h2 id="versionRDMixTitle" title="${escapeHtml(source+' · '+uiText('占已标有效结果','Share of valid labeled results'))}">${uiText('RD 三分类分布','RD classification mix')}</h2>
        ${d.completed?`<div class="version-rd-legend" tabindex="0" role="group" aria-label="${escapeHtml(uiText('三分类图例；占已标有效结果，可横向滚动','Classification legend; share of valid labeled results; scroll horizontally'))}">${categories.map(([key,label,cls])=>{const count=d.distribution[key],share=(100*count/d.completed).toFixed(1);return `<span class="version-rd-category" title="${escapeHtml(label+' · '+count+' / '+d.completed)}"><i class="${cls}" aria-hidden="true"></i><span>${label}</span><span>${share}%</span></span>`;}).join('')}</div>`:''}
      </header>
      ${d.completed?`<div class="version-rd-stack" aria-hidden="true">${categories.filter(([key])=>d.distribution[key]>0).map(([key,,cls])=>`<i class="${cls}" style="flex:${d.distribution[key]} 0 0"></i>`).join('')}</div>`:`<p class="version-rd-empty">${uiText('暂无有效三分类结果','No valid classifications yet')}</p>`}
    </section>
  </div>`;
  // Preserve focused legends and their horizontal scroll on unchanged polling.
  if(el.innerHTML!==markup){
    const legends=[...el.querySelectorAll('.version-rd-legend')];
    const focus=legends.indexOf(document.activeElement),scrolls=legends.map(x=>x.scrollLeft);
    el.innerHTML=markup;
    el.querySelectorAll('.version-rd-legend').forEach((x,i)=>{x.scrollLeft=scrolls[i]||0;if(i===focus)x.focus({preventScroll:true});});
  }
}
