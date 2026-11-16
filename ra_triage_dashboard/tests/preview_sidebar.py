"""Loopback shell preview using production sidebar bindings; no DB or writers.

python -m ra_triage_dashboard.tests.preview_sidebar --port 50275
Use ?fixture=loading or ?fixture=error for the existing Version Metrics states.
"""
import argparse
import re
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles


BOOTSTRAP = r"""
document.addEventListener('DOMContentLoaded', () => {
  state.activePage = 'version-metrics';
  state.session = {is_admin:true,access_role:'admin',can_view_intent:true,read_only:false,identity_pending:false,username:'preview',verified:true};
  state.uiLanguage = localStorage.getItem('ra-triage-ui-language') || 'zh';
  state.sidebarCollapsed = localStorage.getItem('ra-triage-sidebar-collapsed') === 'true';
  document.documentElement.dataset.uiLang = state.uiLanguage;
  document.documentElement.dataset.sessionPending = 'false';
  document.body.dataset.activePage = state.activePage;
  document.querySelectorAll('.app-page').forEach(page => page.classList.toggle('hidden', page.dataset.page !== state.activePage));
  renderSession();
  document.querySelectorAll('.sidebar-item').forEach(link => {
    link.classList.toggle('active', link.dataset.pageTarget === state.activePage);
    link.addEventListener('click', event => {event.preventDefault();closeMobileSidebar();});
  });
  bindSidebarNavigation();
  applySidebarState();
  const fixture = new URLSearchParams(location.search).get('fixture');
  versionMetrics.active = true;
  vmReadRoute();
  versionMetrics.loading = fixture === 'loading';
  versionMetrics.error = fixture === 'error' ? 'load_failed' : '';
  const draw = () => {
    document.querySelector('#pageTitle').textContent = uiText('版本指标 · 本地预览','Version metrics · local preview');
    document.querySelector('#languageToggleButton').textContent = state.uiLanguage === 'zh' ? 'EN' : '中文';
    applyDomI18n(document);renderVersionMetrics();applySidebarState();
  };
  document.querySelector('#languageToggleButton').addEventListener('click', () => {
    state.uiLanguage = state.uiLanguage === 'zh' ? 'en' : 'zh';
    document.documentElement.dataset.uiLang = state.uiLanguage;
    localStorage.setItem('ra-triage-ui-language', state.uiLanguage);draw();
  });
  document.querySelector('#themeToggleButton').addEventListener('click', () => applyColorTheme(state.colorTheme === 'light' ? 'dark' : 'light'));
  document.querySelector('#gtSyncControl').hidden = true;
  document.querySelector('#refreshButton').hidden = true;
  document.querySelector('#shortcutHelpButton').hidden = true;
  applyColorTheme(localStorage.getItem('ra-triage-color-theme') || 'dark');
  observeDashboardSelects();bindMobileWorkbench();draw();markUiReady();
});
"""


def create_preview_app():
    static = Path(__file__).resolve().parents[1] / 'static'
    original = (static / 'index.html').read_text()
    styles = re.findall(r'"((?:css/|vendor/)[^"\n]+\.css|styles\.css)"', original)
    modules = [name.strip() for name in (static / 'js/MANIFEST').read_text().splitlines()
               if name.strip() and not name.startswith('#') and name.strip() != 'bind-bootstrap.js']
    html = re.sub(r'<script\b[^>]*>[\s\S]*?</script>', '', original).replace('{{RA_TRIAGE_BASE_PATH}}', '')
    html = html.replace('</head>', ''.join(f'<link rel="stylesheet" href="/static/{name}">' for name in styles) + '</head>')
    html = html.replace('</body>', ''.join(f'<script src="/static/js/{name}"></script>' for name in modules) + f'<script>{BOOTSTRAP}</script></body>')
    app = FastAPI(docs_url=None, redoc_url=None)
    app.mount('/static', StaticFiles(directory=static), name='static')

    @app.get('/version-metrics', response_class=HTMLResponse)
    async def shell():
        return HTMLResponse(html, headers={'Cache-Control': 'no-store'})

    return app


if __name__ == '__main__':
    import uvicorn
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=50275)
    uvicorn.run(create_preview_app(), host='127.0.0.1', port=parser.parse_args().port, access_log=False)
