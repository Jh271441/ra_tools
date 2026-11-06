"""Loopback-only visual preview: real publication routes/UI, synthetic sources.

python3 -m ra_triage_dashboard.tests.preview_te_corrections --port 50268
No Trail client is created. Both real publication switches stay disabled.
"""
from __future__ import annotations

import argparse
import copy
from pathlib import Path
import re
import tempfile
import time
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from ra_triage_dashboard.app import rd_results as service
from ra_triage_dashboard.app.routers import rd_results as routes


BOOTSTRAP = r"""
document.addEventListener('DOMContentLoaded', async () => {
  const params = new URLSearchParams(location.search);
  state.activePage = 'rd-results';
  state.selectedBaselineIds = (params.get('baselines') || 'version-20261016').split(',');
  state.baselineCatalog = [{id:'version-20261016',label:'1016 版本 · 示例',label_en:'Version 1016 · sample',count:84},{id:'version-20261009',label:'1009 版本 · 示例',label_en:'Version 1009 · sample',count:84}];
  state.session = {is_admin:true,is_writer:true,read_only:false,identity_pending:false,username:'preview',verified:false};
  state.uiLanguage = localStorage.getItem('te-preview-language') || 'zh';
  document.documentElement.dataset.uiLang = state.uiLanguage;
  applyColorTheme(localStorage.getItem('ra-triage-color-theme') || 'dark');
  document.documentElement.dataset.sessionPending = 'false';
  document.body.dataset.activePage = 'rd-results';
  document.querySelectorAll('.app-page').forEach(p => p.classList.toggle('hidden',p.dataset.page !== 'rd-results'));
  document.querySelectorAll('.sidebar-item[data-page-target]').forEach(p => {
    p.classList.toggle('active',p.dataset.pageTarget === 'rd-results');
    p.inert = false; p.removeAttribute('aria-disabled');
    p.onclick = e => e.preventDefault();
  });
  const drawHeader = () => {
    document.querySelector('#pageTitle').textContent = uiText('标注上传 · 合成数据预览','Label upload · synthetic preview');
    document.querySelector('#languageToggleButton').textContent = state.uiLanguage === 'zh' ? 'EN' : '中文';
    renderBaselinePicker();
  };
  setBaselineScopes = async values => {
    rdForgetPreview(); state.selectedBaselineIds = values; rdPersist(); drawHeader(); await loadRdResults();
  };
  document.querySelector('#languageToggleButton').onclick = () => {
    state.uiLanguage = state.uiLanguage === 'zh' ? 'en' : 'zh';
    document.documentElement.dataset.uiLang = state.uiLanguage;
    localStorage.setItem('te-preview-language',state.uiLanguage); drawHeader(); renderRdResults();
  };
  document.querySelector('#themeToggleButton').onclick = () => applyColorTheme(document.documentElement.dataset.colorTheme === 'light' ? 'dark' : 'light');
  document.querySelector('#refreshButton').onclick = () => loadRdResults();
  document.querySelector('#sidebarToggle').onclick = () => {
    const collapsed = document.documentElement.dataset.sidebarPref !== 'collapsed';
    document.documentElement.dataset.sidebarPref = collapsed ? 'collapsed' : '';
    document.body.classList.toggle('sidebar-collapsed',collapsed);
  };
  document.addEventListener('click', () => closeAllMultiFilters());
  document.addEventListener('keydown', e => {if(e.key === 'Escape') closeAllMultiFilters();});
  renderSessionNavigation();
  document.querySelector('#sessionUserName').textContent = 'preview';
  document.querySelector('#sessionUserSource').textContent = uiText('合成数据 · 禁止写入','Synthetic data · uploads disabled');
  document.querySelector('#userAvatar').textContent = 'P';
  document.querySelector('#gtSyncControl').hidden = true;
  document.querySelector('#shortcutHelpButton').hidden = true;
  observeDashboardSelects(); bindMobileWorkbench(); drawHeader();
  await loadRdResults();
});
"""


def create_preview_app():
    temporary = tempfile.TemporaryDirectory(prefix='te-correction-preview-')
    static = Path(__file__).resolve().parents[1] / 'static'
    specs = [
        ('resolved', '正确触发', '误触发', '成功'),
        ('resolved', '误触发', '成功', '误触发'),
        ('resolved', '无需协助', '误触发', None),
        ('resolved', '正确触发', '成功', '成功'),
        ('resolved', '误触发', None, '误触发'),
        ('conflict', '', '误触发', '误触发'),
        ('pending', '', None, None),
        ('resolved', '无需协助', '成功', '无需协助'),
        ('resolved', '误触发', '未接起', '误触发'),
        ('stale', '', '成功', '误触发'),
        ('resolved', '正确触发', '误触发', '无需协助'),
        ('resolved', '无需协助', '无需协助', '无需协助'),
    ]
    local, remote, observations = {}, {}, []
    for n in range(84):
        state, label, te, rd = specs[n % len(specs)]
        iid = f'cn{35655695+n}'
        local[iid] = dict(issue_id=iid,state=state,label=label,fingerprint=f'synthetic-{n}',
                          authors=[['reviewer_one','reviewer_two','reviewer_with_a_long_name'][n % 3]],
                          baseline_scope='synthetic',source_revision_ids=[],decision_id=None)
        remote[iid] = {service.FIELD:rd,service.TE_FIELD:te,**{k:'preserved' for k in service.PROTECTED}}
        observations.append(dict(issue_id=iid,te_status='filled' if te else 'unfilled',te_value=te))

    # Simulate one TE edit made elsewhere after the automatic snapshot.
    remote['cn35655695'][service.TE_FIELD] = '成功'
    read_te = service.read_te_observations
    def delayed_te_read(client, ids):
        time.sleep(1)
        return read_te(client, ids)
    service.read_te_observations = delayed_te_read

    class SyntheticTrail:
        def fetch(self, ids):
            return [dict(issue_id=iid, **copy.deepcopy(remote[iid])) for iid in ids]

        def update(self, values):
            raise AssertionError('Preview prohibits publication')

    routes.settings = SimpleNamespace(data_dir=temporary.name,ra_auto_triage_root=temporary.name,
                                     trail_rd_write_enabled=False,trail_te_write_enabled=False)
    routes._writer_identity = routes._admin_identity = lambda *args: SimpleNamespace(username='preview')
    routes.members = lambda *args: list(local)
    routes.resolve_request_baseline_ids = lambda raw, **kwargs: raw.split(',')
    routes.te_snapshot = lambda *args: (dict(source_status='ready',last_success_at='2026-11-06T03:00:00+00:00'),observations)
    service.local_rows = lambda db, ids: {iid:copy.deepcopy(local[iid]) for iid in ids if iid in local}
    service.adapter = lambda *args, **kwargs: SyntheticTrail()
    original = (static / 'index.html').read_text()
    css = re.findall(r'"((?:css/|vendor/)[^"\n]+\.css|styles\.css)"',original)
    modules = ['core-base','text-input','issue-query','i18n-messages','i18n','format-api','session-config','routing','rd-results','review-tags','mobile-workbench']
    html = re.sub(r'<script\b[^>]*>[\s\S]*?</script>', '', original).replace('{{RA_TRIAGE_BASE_PATH}}','')
    html = html.replace('</head>', ''.join(f'<link rel="stylesheet" href="/static/{p}">' for p in css)+'</head>')
    html = html.replace('</body>', ''.join(f'<script src="/static/js/{m}.js"></script>' for m in modules)+f'<script>{BOOTSTRAP}</script></body>')
    html = html.replace('<title>','<title>合成数据预览 · ')
    app = FastAPI(docs_url=None,redoc_url=None)
    app.state.preview_temporary = temporary
    app.include_router(routes.router)
    app.mount('/static',StaticFiles(directory=static),name='static')

    @app.get('/rd-results',response_class=HTMLResponse)
    async def preview():
        return HTMLResponse(html,headers={'Cache-Control':'no-store'})

    return app


if __name__ == '__main__':
    import uvicorn
    parser = argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=50268)
    args = parser.parse_args()
    uvicorn.run(create_preview_app(),host='127.0.0.1',port=args.port,access_log=False)
