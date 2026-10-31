"""Serve the real Workbench frontend against a frozen read-only API snapshot.

No production proxy, credentials, writes, scheduler or video source reads.
python3 -m ra_triage_dashboard.tests.preview_daily_media --snapshot /tmp/snapshot.json
"""
import argparse
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from ra_triage_dashboard.app.web_paths import render_index_html


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8794)
    parser.add_argument('--scenario', choices=['snapshot', 'empty', 'unavailable'], default='snapshot')
    args = parser.parse_args()
    snapshot = json.loads(args.snapshot.read_text())
    if args.scenario != 'snapshot':
        media = dict(selected=0,verified=0,triple_verified=0,camera_verified=0,bev_verified=0,
                     closeup=dict(receipt_status='ready',verified=0,queued=0,attention=0,unknown=0))
        version = dict(family='20261009',states_status='ready',states={'published':0},media=media)
        if args.scenario == 'unavailable':
            version.update(states_status='unavailable',states=None,media={})
        snapshot = dict(sources={},incremental=dict(enabled=True,families=['20261009'],versions=[version],
                        datasets=[],states={},media=version['media']))
    static = Path(__file__).resolve().parents[1] / 'static'
    shell = render_index_html((static/'index.html').read_text(), '/manual')
    marker = 'id="dailyCronPage" data-page="daily-cron">'
    notice = ('<p class="cron-alert" data-tone="warn"><span class="ui-lang-zh">'
              '部署前本地预览 · 云端真实只读快照 · 非实时数据 · 所有写入已禁用'
              '</span><span class="ui-lang-en">Local preview before deployment · '
              'Real cloud snapshot, frozen in time · All writes disabled</span></p>')
    if args.scenario == 'snapshot' and snapshot.get('preview', {}).get('captured_at'):
        at = datetime.fromtimestamp(snapshot['preview']['captured_at'], ZoneInfo('Asia/Shanghai')).strftime('%m-%d %H:%M:%S CST')
        notice = notice.replace('</p>', f' · {at}</p>')
    elif args.scenario != 'snapshot':
        notice = '<p class="cron-alert" data-tone="warn"><span class="ui-lang-zh">隔离测试状态 · 非实际进度</span><span class="ui-lang-en">Isolated test state · Not actual progress</span></p>'
    shell = shell.replace(marker, marker + notice)

    class Handler(BaseHTTPRequestHandler):
        def respond(self, data, content_type='application/json'):
            self.send_response(200)
            self.send_header('Content-Type', content_type+'; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(data if isinstance(data, bytes) else data.encode())

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == '/manual/api/daily-cron':
                return self.respond(json.dumps(snapshot, ensure_ascii=False))
            if path == '/manual/api/dashboard-config':
                return self.respond(json.dumps(dict(baselines=[dict(id='version-20261009', label='1009', scope='manual_sidecar_version_20261009', issue_count=628)], default_baseline_ids=['version-20261009'], tag_catalog=[])))
            if path == '/manual/api/session':
                return self.respond(json.dumps(dict(authenticated=False, can_write=False, read_only=True, browser_lca_fallback=False)))
            if path.startswith('/manual/api/'):
                return self.respond('{"items":[],"issues":0,"revision":0,"poll_after_ms":30000}')
            if path.startswith('/manual/static/'):
                file = (static/path[len('/manual/static/'):]).resolve()
                if not file.is_relative_to(static) or not file.is_file():
                    self.send_error(404)
                    return
                mime = 'text/javascript' if file.suffix == '.js' else 'text/css' if file.suffix == '.css' else 'application/octet-stream'
                return self.respond(file.read_bytes(), mime)
            if path in {'/manual', '/manual/', '/manual/daily-cron'}:
                return self.respond(shell, 'text/html')
            self.send_error(404)

        def do_POST(self):
            self.send_error(405)

        do_PUT = do_PATCH = do_DELETE = do_POST

        def log_message(self, *_):
            pass

    with ThreadingHTTPServer(('127.0.0.1', args.port), Handler) as server:
        print(f'http://127.0.0.1:{args.port}/manual/daily-cron?cron_version=20261009', flush=True)
        server.serve_forever()


if __name__ == '__main__':
    main()
