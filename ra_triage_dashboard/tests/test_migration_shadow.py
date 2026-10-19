import asyncio
import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('migration_shadow', Path(__file__).parents[1] / 'scripts/run_migration_shadow.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_requires_every_external_writer_disabled():
    env = {key: 'false' for key in module.DISABLED}
    env.update(DASHBOARD_DEPLOYMENT_MODE='production', DASHBOARD_TRUST_PROXY_IDENTITY_HEADERS='true', DASHBOARD_TRUSTED_INGRESS_TOKEN_FILE='/private/shadow-token')
    module.validate_config(env)
    for key in module.DISABLED:
        with pytest.raises(ValueError):
            module.validate_config({**env, key: 'true'})
        with pytest.raises(ValueError):
            module.validate_config({k:v for k,v in env.items() if k != key})


def test_sso_preview_only_relaxes_ticket_validation_and_requires_own_path():
    env = {key: 'false' for key in module.DISABLED}
    env.update(DASHBOARD_DEPLOYMENT_MODE='production', DASHBOARD_TRUST_PROXY_IDENTITY_HEADERS='false',
               DASHBOARD_TRUSTED_INGRESS_TOKEN_FILE='/private/shadow-token', DASHBOARD_KYLIN_SSO_ENABLED='true',
               DASHBOARD_KYLIN_SSO_APP_ID='2103860', DASHBOARD_BASE_PATH='/manual-migration')
    module.validate_config(env, sso_preview=True)
    with pytest.raises(ValueError): module.validate_config(env)
    with pytest.raises(ValueError): module.validate_config({**env,'DASHBOARD_BASE_PATH':'/manual'}, sso_preview=True)
    with pytest.raises(ValueError): module.validate_config({**env,'DASHBOARD_DCHAT_NOTIFICATIONS_ENABLED':'true'}, sso_preview=True)
    with pytest.raises(ValueError): module.validate_config({**env,'DASHBOARD_TRUST_PROXY_IDENTITY_HEADERS':'true'}, sso_preview=True)
    with pytest.raises(ValueError): module.validate_config({**env,'DASHBOARD_KYLIN_SSO_APP_ID':''}, sso_preview=True)


@pytest.mark.parametrize('method', ['POST','PUT','PATCH','DELETE'])
def test_rejects_writes_before_identity_or_application(method):
    events=[]
    async def app(scope, receive, send):
        raise AssertionError('Read-only guard must not call application')
    async def receive():
        return {'type':'http.request', 'body':b''}
    async def send(event):
        events.append(event)
    scope={'type':'http','method':method,'path':'/api/labeling/cases/x/revisions','headers':[(b'x-user',b'jasperchen')]}
    asyncio.run(module.RejectWrites(app)(scope,receive,send))
    assert events[0]['status']==503


def test_health_and_lifespan_are_passed_through():
    calls=[]
    async def app(scope,receive,send):calls.append(scope['type'])
    asyncio.run(module.RejectWrites(app)({'type':'http','method':'GET'},None,None))
    asyncio.run(module.RejectWrites(app)({'type':'lifespan'},None,None))
    assert calls==['http','lifespan']


@pytest.mark.parametrize('fault', ['missing', 'writable', 'wrong_volume', 'wrong_sentinel', None])
def test_startup_requires_real_read_only_mounts(tmp_path, fault):
    rows = ['orangefs:remote-assist-stuck-model /mnt/ofs/manual-ro fuse.ofs ro,allow_other 0 0',
            'orangefs:remote-assist-stuck-model /mnt/ofs/manual-bags-ro fuse.ofs ro,allow_other 0 0']
    if fault == 'missing': rows.pop()
    if fault == 'writable': rows[0] = rows[0].replace(' ro,', ' rw,')
    if fault == 'wrong_volume': rows[0] = rows[0].replace('remote-assist-stuck-model', 'other')
    mounts = tmp_path / 'mounts'; mounts.write_text('\n'.join(rows))
    sentinel = tmp_path / 'sentinel'; sentinel.write_text('{"service":"%s"}' % ('other' if fault == 'wrong_sentinel' else 'manual'))
    if fault:
        with pytest.raises(ValueError): module.validate_media_mounts(mounts, sentinel)
    else:
        module.validate_media_mounts(mounts, sentinel)
