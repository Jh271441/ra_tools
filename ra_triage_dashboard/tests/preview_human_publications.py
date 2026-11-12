"""Loopback preview with real DB/routes and synthetic labels. Live writes disabled."""
import argparse
import json
import re
import tempfile
from pathlib import Path
from types import SimpleNamespace
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .preview_te_corrections import BOOTSTRAP
from .test_human_publication import db as database_fixture,submit,admit,choose,Trail
from ..app.human_publisher import HumanPublisher
from ..app.routers import human_publications as routes
from ..app.routers import version_datasets as version_routes


def create_preview_app():
    temporary=tempfile.TemporaryDirectory(prefix='human-publication-preview-')
    generator=database_fixture.__wrapped__(Path(temporary.name));database=next(generator)
    rows=database.version_dataset_gallery_rows('release-20261106-odd2')
    fake=Trail();publisher=HumanPublisher(database,temporary.name,fake,enabled=True)
    for n,row in enumerate(rows):
        iid=row['issue_id'];owner=row['binding']['assignee']
        if n%6==0:continue
        submit(database,iid,owner,'误触发' if n%2 else '正确触发')
        if n%6==1:submit(database,iid,'observer','无需协助')
        if n%6==2:admit(database,iid,'observer');submit(database,iid,'observer','无需协助')
        if n%6==3:
            human=database.human_label_context(iid)
            database.adjudicate_issue_label(baseline_scope=human['scope']['baseline_scope'],issue_id=iid,expected_output='正确触发',rationale='Synthetic final decision',
                actor='jasperchen',actor_source='test',actor_verified=True,expected_source_fingerprint=human['source_fingerprint'])
        if row['binding']['cohort']=='sampling' and n%3:
            submit(database,iid,row['binding']['assignees'][1],'无需协助')
    publisher.tick(force_ids=[r['issue_id'] for r in rows])
    # One known failed outcome for display; this adapter never contacts a service.
    iid=rows[1]['issue_id']
    with database.connect() as conn:conn.execute("UPDATE human_publications SET sync_state='needs_recheck',error_code='readback_failed' WHERE issue_id=? AND lane='rd'",(iid,))
    routes.database=database;routes.settings=SimpleNamespace(human_label_write_enabled=False,human_label_capabilities_file=None)
    routes._writer_identity=routes._admin_identity=lambda *a:SimpleNamespace(username='preview')
    version_routes.database=database;version_routes.settings=SimpleNamespace(ra_auto_triage_root=Path(temporary.name))
    static=Path(__file__).resolve().parents[1]/'static';original=(static/'index.html').read_text()
    css=re.findall(r'"((?:css/|vendor/)[^"\n]+\.css|styles\.css)"',original)
    modules=[name.strip().removesuffix('.js') for name in (static/'js/MANIFEST').read_text().splitlines() if name.strip() and not name.startswith('#') and name.strip()!='bind-bootstrap.js']
    html=re.sub(r'<script\b[^>]*>[\s\S]*?</script>','',original).replace('{{RA_TRIAGE_BASE_PATH}}','')
    html=html.replace('</head>',''.join(f'<link rel="stylesheet" href="/static/{p}">' for p in css)+'</head>')
    bootstrap=BOOTSTRAP.replace('version-20261016','version-20261106').replace('version-20261009','version-20261106').replace('1016','1106').replace('1009','1106')
    bootstrap=re.sub(r"state.baselineCatalog = .*?;", "state.baselineCatalog = [{id:'version-20261106',label:'1106 版本 · 合成示例',label_en:'Version 1106 · synthetic sample',count:60}];",bootstrap)
    bootstrap=bootstrap.replace("uiText('标注上传 · 合成数据预览','Label upload · synthetic preview')", "state.activePage==='version-datasets'?uiText('版本图库 · 合成数据预览','Version gallery · synthetic preview'):state.activePage==='users'?uiText('用户身份 · 合成数据预览','User roles · synthetic preview'):uiText('标注上传 · 合成数据预览','Label upload · synthetic preview')")
    bootstrap=bootstrap.replace("renderSessionNavigation();", "state.accessUsers="+json.dumps(database.list_access_users())+"; renderAccessUsers(); renderSessionNavigation();")
    bootstrap=bootstrap.replace("drawHeader(); renderRdResults();", "drawHeader(); applyDomI18n(document); if(state.activePage==='version-datasets')renderVersionDatasets({force:true});else if(state.activePage==='users')renderAccessUsers({preserveDrafts:true});else renderRdResults();")
    bootstrap=bootstrap.replace("() => loadRdResults();", "() => state.activePage==='version-datasets'?loadVersionDatasets():loadRdResults();")
    # A query parameter exposes the real identity form for responsive acceptance.
    bootstrap=bootstrap.replace("await loadRdResults();\n});", """if(location.pathname==='/version-datasets'){
      state.activePage='version-datasets';document.body.dataset.activePage=state.activePage;
      document.querySelectorAll('.app-page').forEach(p=>p.classList.toggle('hidden',p.dataset.page!==state.activePage));
      document.querySelector('#pageTitle').textContent=uiText('版本图库 · 合成数据预览','Version gallery · synthetic preview');
      applyDomI18n(document);setVersionDatasetsActive(true);
    }else{await loadRdResults();if(params.get('preview')==='users'){
      document.querySelectorAll('.app-page').forEach(p=>p.classList.toggle('hidden',p.dataset.page!=='users'));
      document.body.dataset.activePage='users';state.activePage='users';drawHeader();applyDomI18n(document);
    }}
});""")
    html=html.replace('</body>',''.join(f'<script src="/static/js/{m}.js"></script>' for m in modules)+f'<script>{bootstrap}</script></body>')
    app=FastAPI(docs_url=None,redoc_url=None);app.state.preview_temporary=temporary;app.state.database_generator=generator
    app.include_router(routes.router);app.include_router(version_routes.router);app.mount('/static',StaticFiles(directory=static),name='static')
    @app.get('/rd-results',response_class=HTMLResponse)
    @app.get('/version-datasets',response_class=HTMLResponse)
    async def shell():return HTMLResponse(html,headers={'Cache-Control':'no-store'})
    @app.get('/api/preview-human-context/{issue_id}')
    def preview_context(issue_id:str):return database.human_label_context(issue_id)
    return app


if __name__=='__main__':
    import uvicorn
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=50269);args=parser.parse_args()
    uvicorn.run(create_preview_app(),host='127.0.0.1',port=args.port,access_log=False)
