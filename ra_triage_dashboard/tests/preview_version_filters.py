"""Local-only UI preview: actual page modules + workbench, synthetic in-memory DB.

Run from the repository root with python3 -m ra_triage_dashboard.tests.preview_version_filters.
No production DB, credentials, Trail, or mutation endpoints are used.
"""
import argparse
import json
import re
import tempfile
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

from ra_triage_dashboard.app.version_workbench import workbench, gallery_csv

STATIC = Path(__file__).resolve().parents[1] / 'static'
FAMILY = '20261009'
DATASET = 'release-20261009-odd2'


def preview_rd_summary(rows):
    """Synthetic manual labels only; never use prediction or joint completion."""
    counts = {'正确触发': 0, '误触发': 0, '无需协助': 0}
    pending = conflict = 0
    for row in rows:
        sample = int(row['issue_id'][2:]) % 10
        if sample < 3:
            pending += 1
        elif sample == 3:
            conflict += 1
        else:
            counts['正确触发' if sample < 7 else '误触发' if sample < 9 else '无需协助'] += 1
    return dict(source='manual_issue_labels', source_status='ready', total=len(rows), completed=sum(counts.values()), pending=pending,
                conflict=conflict, distribution=counts, synthetic=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8794)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='version-filter-preview-') as directory:
        root = Path(directory)
        folder = root / 'reports/te_review_monitor/snapshots'
        folder.mkdir(parents=True)
        rows, observations = [], []
        for i in range(1, 41):
            target = i <= 24
            sample = i % 3 == 0
            low = target and (not sample or i % 2 == 0)
            status = 'published' if i <= 34 else 'waiting_metadata' if i <= 37 else 'excluded'
            day = f'2026-10-{20 + i % 7:02}'
            rows.append(dict(issue_id=f'cn9000{i:03}', is_target=target, is_sample=sample,
                             is_low=low, state=status, software_version='1.gen4-release-20261009.demo',
                             first_seen=day, updated_at=day,
                             issue_time=int(datetime.fromisoformat(day+'T02:00:00+00:00').timestamp()*1000),
                             binding={'assignee': 'demo-reviewer'}, review_submitted=i % 4 == 0,
                             prediction={'model_label':'正确触发','model_confidence':0.68} if i <= 34 else None))
            if target and i % 7:
                observations.append(dict(issue_id=f'cn9000{i:03}', dataset='1009', date=day,
                    version='1.gen4-release-20261009.demo', reason='sample' if sample else 'low',
                    te_status='filled' if i % 4 == 0 else 'unfilled',
                    te_value=['失败','未接起','超出范围','误触发','成功','无需协助'][i // 4 - 1] if i % 4 == 0 else None))
        (folder/'1009.json').write_text(json.dumps(dict(schema_version=1, source_field='ra_review_result_new',
            dataset='1009', date='', snapshot_revision='a'*64, last_success_at=datetime.now(timezone.utc).isoformat(), rows=observations)))
        (folder.parent/'version-membership-1009.json').write_text('{"schema_version":1}')
        catalog = dict(id=DATASET, release_family=FAMILY, targets=24, total=40, revision=1, historical=False)
        db = SimpleNamespace(list_version_datasets=lambda:[catalog], version_dataset_gallery_rows=lambda _:json.loads(json.dumps(rows)),
                             version_dataset_rd_summary=lambda ids:preview_rd_summary([{'issue_id':iid} for iid in ids]))

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                request = urlsplit(self.path)
                try:
                    if request.path.startswith('/static/'):
                        path = (STATIC/request.path[len('/static/'):]).resolve()
                        if not path.is_relative_to(STATIC) or not path.is_file():
                            self.send_error(404); return
                        return self.respond(path.read_bytes(), 'text/css' if path.suffix=='.css' else 'text/javascript')
                    if request.path == '/api/version-datasets':
                        return self.respond(json.dumps({'items':[catalog]}).encode(), 'application/json')
                    if request.path.endswith('/batches'):
                        return self.respond(b'{"items":[]}', 'application/json')
                    if request.path in [f'/api/version-datasets/{DATASET}/workbench', f'/api/version-datasets/{DATASET}/workbench.csv']:
                        params = {k:v[-1] for k,v in parse_qs(request.query).items()}
                        for key in ['page', 'page_size']:
                            if key in params: params[key] = int(params[key])
                        data, selected = workbench(db, root, DATASET, **params)
                        # Never link synthetic IDs to a real external service.
                        data['count_scope']['trail_links'] = {}
                        if request.path.endswith('.csv'):
                            return self.respond(gallery_csv(selected).encode(), 'text/csv')
                        return self.respond(json.dumps(data).encode(), 'application/json')
                    if request.path != '/version-datasets':
                        self.send_error(404); return
                    source = (STATIC/'index.html').read_text()
                    start = source.index('          <section class="app-page tool-page version-datasets-page')
                    end = source.index('<section class="app-page tool-page daily-cron-page', start)
                    page = source[start:end].replace('version-datasets-page hidden', 'version-datasets-page')
                    color_preview = 'colors' in parse_qs(request.query)
                    if color_preview:
                        page = page.replace('<section class="gallery-panel version-gallery"', '<div id="previewGtColors" class="analysis-cluster-grid"></div><section class="gallery-panel version-gallery"')
                    styles = re.findall(r'"([^"\n]+\.css)"', source.split('const stylesheetPaths = [')[1].split('];')[0])
                    links = ''.join(f'<link rel="stylesheet" href="/static/{p}">' for p in styles)
                    scripts = ''.join(f'<script src="/static/js/{p}.js"></script>' for p in ['core-base','i18n-messages','i18n','format-api','daily-review','version-datasets','version-rd','analysis'])
                    html = f'''<!doctype html><html lang="zh-CN" data-ui-lang="zh" data-color-theme="dark"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>版本筛选 · 本地预览</title>{links}</head>
<body data-active-page="version-datasets"><main style="padding:12px;max-width:1504px;margin:auto;min-width:0">
<header class="section-heading" style="flex-wrap:wrap;gap:12px"><h1><span class="ui-lang-zh">版本数据</span><span class="ui-lang-en">Version data</span></h1><span class="muted"><span class="ui-lang-zh">本地预览 · 示例数据 · 无真实媒体</span><span class="ui-lang-en">Local preview · Sample data · No real media</span></span><div class="ui-choice-group"><button class="button button-secondary" id="previewLanguage" type="button">EN / 中文</button><button class="button button-secondary" id="previewTheme" type="button">Light / 深色</button><button class="button button-secondary" id="previewFailure" type="button">Error / 失败</button></div></header>{page}</main>{scripts}<script>
state.uiLanguage='zh';state.activePage='version-datasets';
let previewFail=false;
api=async(path,options={{}})=>{{if(previewFail)throw new Error('Preview failure');const r=await fetch(path,{{signal:options.signal}});if(!r.ok)throw new Error('Preview '+r.status);return r.json();}};
function previewGtColors(){{const mount=document.getElementById('previewGtColors');if(!mount)return;mount.innerHTML=[{{all:655,ready:281,blocked:0}},{{all:655,ready:281,blocked:90}}].map((counts,i)=>'<div style="min-width:0">'+analysisGtChartMarkup({{gt_update_counts:counts}},{{prefix:'preview'+i}})+'</div>').join('');bindAnalysisPieHover(mount);}};
document.getElementById('previewLanguage').onclick=()=>{{state.uiLanguage=state.uiLanguage==='zh'?'en':'zh';document.documentElement.dataset.uiLang=state.uiLanguage;renderVersionDatasets();previewGtColors();}};
document.getElementById('previewTheme').onclick=()=>{{const d=document.documentElement.dataset;d.colorTheme=d.colorTheme==='dark'?'light':'dark';}};
document.getElementById('previewFailure').onclick=()=>{{previewFail=!previewFail;loadVersionDatasets();}};
document.addEventListener('click',e=>{{const a=e.target.closest('a');if(a&&!a.getAttribute('href')?.startsWith('/api/'))e.preventDefault();if(e.target.closest('[data-version-open]'))e.stopImmediatePropagation();}},true);
window.addEventListener('popstate',()=>setVersionDatasetsActive(true));
setVersionDatasetsActive(true);
previewGtColors();
</script></body></html>'''
                    return self.respond(html.encode(), 'text/html')
                except Exception as error:
                    self.send_error(400, str(error))

            def respond(self, content, content_type):
                self.send_response(200)
                self.send_header('Content-Type', content_type+'; charset=utf-8')
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(content)

        server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
        print(f'http://127.0.0.1:{server.server_port}/version-datasets', flush=True)
        try:
            server.serve_forever()
        finally:
            server.server_close()


if __name__ == '__main__':
    main()
