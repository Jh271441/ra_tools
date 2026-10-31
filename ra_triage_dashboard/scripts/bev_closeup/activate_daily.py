"""Install a pinned personal-media release, switching only idle owned controllers.

Dashboard deployment is separate and must have succeeded through deploy_cloud.
This command preserves the original launch environment and its existing guard.
"""
import argparse
from datetime import datetime
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import tarfile
import time

from offline_daily import TASK, REPO, RECIPE, LAYOUT_SHA, read, save, sha

FROZEN = {
    'local-fallback/20261030T0926Z/source_worker.py': '5fbecd9fdd3df252d9d3d9a0ecff3630577e4ef87d87f896e9f1d4178be148af',
    'local-fallback/20261030T0926Z/canary-command.json': 'dae9aa726ee62935b9d0a9315724e7c36552078763a06ba40aff687fdb437f18',
    'orion/pipeline.py': 'c2bc1e88829695321b335a2b5497575b3295d715700fa664d941705455fbdd35',
    'code/ra_triage_dashboard/scripts/bev_closeup/coordinator.py': 'f4f6d9c8b5c5fcac1292cd99d1ad8dec9eb692d89b12284e10f5d9fc01c8ff06',
    'code/ra_triage_dashboard/scripts/bev_closeup/inventory.py': '86cfaffcb6c81ee91cccb1f82e72b8fe5516e135706499b9acd0bbe95336119c',
    str(REPO/'tools/manual_sidecar/controller.py'): 'd1fad40602d64acaf4bc8442be8acfe6ea16c308d2eb771412c1af523f890a76',
    str(REPO/'tools/manual_sidecar/recovery.py'): '49da6ce4dbeb73d2ba60e003c4e22202723dc9eaae49d5474b0c182e2e9d6f1c',
    str(REPO/'tools/manual_sidecar/recovery-policy.json'): '80461920cb873fcdd7df16431d04dd9ae9f37b8e23984f8997e3a5696262f42f',
}
ORIGINAL_LAUNCH_SHA = '9acb1d51af0e5ffb6b70064b65c2a2d7e2897b47288e18d651077d5e99ac16a2'


def process(pid):
    path = Path('/proc')/str(pid)
    stat = (path/'stat').read_text().rsplit(') ',1)[1].split()
    return dict(pid=pid, start_ticks=stat[19], state=stat[0], cwd=os.readlink(path/'cwd'),
                argv=(path/'cmdline').read_bytes().decode().split('\0'),
                children=(path/f'task/{pid}/children').read_text().split())


def owns_lock(pid, path):
    # fdinfo records the lock owner as well as the opened inode.
    for fd in (Path('/proc')/str(pid)/'fd').iterdir():
        try:
            if os.path.realpath(fd) == str(path) and any(
                    line.startswith('lock:') and f' {pid} ' in line
                    for line in (fd.parent.parent/'fdinfo'/fd.name).read_text().splitlines()):
                return True
        except OSError:
            pass
    return False


def wait_exit(pid, ticks, timeout):
    until = time.monotonic()+timeout
    while time.monotonic() < until:
        try:
            current = process(pid)
            if current['start_ticks'] != ticks or current['state'] == 'Z':
                return
        except FileNotFoundError:
            return
        time.sleep(1)
    raise RuntimeError('owned_controller_did_not_drain')


def activate(args):
    os.umask(0o077)
    directory = TASK/'daily-sidecar'
    directory.mkdir(exist_ok=True)
    lock = (directory/'activation.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if (directory/'activation.json').exists():
        raise ValueError('activation_already_recorded_requires_reconciliation')
    cron = subprocess.check_output(['crontab','-l'], text=True)
    marker = '# BEGIN RA_BEV_CLOSEUP_DAILY'
    if marker in cron:
        raise ValueError('closeup_cron_already_registered')
    tools = Path('/volume/home/workspace/ra_tools')
    if subprocess.check_output(['git','rev-parse','HEAD'], cwd=tools, text=True).strip() != args.sha:
        raise ValueError('dashboard_checkout_is_not_release')
    not_before = datetime.fromisoformat(args.not_before).timestamp()
    if not_before <= time.time()+120:
        raise ValueError('activation_must_precede_scheduled_start')
    for file, expected in FROZEN.items():
        if sha(TASK/file) != expected:
            raise ValueError('frozen_executor_changed')
    launch = REPO/'tools/manual_sidecar/launch.sh'
    if sha(launch) != ORIGINAL_LAUNCH_SHA:
        raise ValueError('original_media_launch_changed')
    orion = process(args.orion_pid)
    media = process(args.media_pid)
    if (orion['start_ticks'] != args.orion_ticks or orion['cwd'] != str(TASK)
            or str(TASK/'orion/controller.py') not in orion['argv']
            or not owns_lock(args.orion_pid, TASK/'worker.lock')):
        raise ValueError('orion_controller_identity_changed')
    if (media['start_ticks'] != args.media_ticks or media['cwd'] != str(REPO)
            or 'tools/manual_sidecar/controller.py' not in media['argv']
            or not owns_lock(args.media_pid, REPO/'reports/manual_sidecar_20261019/controller.lock')):
        raise ValueError('original_media_controller_identity_changed')
    if media['children'] or orion['children']:
        raise ValueError('owned_controller_busy_retry_at_boundary')
    release = directory/'releases'/args.sha
    release.mkdir(parents=True, exist_ok=False)
    archive = subprocess.check_output(['git','archive',args.sha,
        'ra_triage_dashboard/scripts/bev_closeup','ra_triage_dashboard/config/bev_closeup'], cwd=tools)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        for member in tar.getmembers():
            target = (release/member.name).resolve()
            target.relative_to(release.resolve())
            if member.issym() or member.islnk():
                raise ValueError('release_archive_links_forbidden')
        tar.extractall(release)
    code = release/'ra_triage_dashboard'
    hashes = {str(p.relative_to(code)): sha(p) for p in code.rglob('*') if p.is_file()}
    if hashes['config/bev_closeup/layout.json'] != LAYOUT_SHA:
        raise ValueError('release_layout_mismatch')
    # Real browser dependency preflight, with no Bag/source or network activity.
    env = dict(os.environ, PLAYWRIGHT_BROWSERS_PATH='/tmp/manual-sidecar-browsers')
    subprocess.run([str(REPO/'.venv-ares-animation/bin/python'), '-c',
        'from playwright.sync_api import sync_playwright; '
        'p=sync_playwright().start(); b=p.chromium.launch(headless=True,args=["--no-sandbox"]); '
        'b.close(); p.stop()'], cwd=REPO, env=env, check=True, timeout=60,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    profile = dict(enabled=True, not_before=not_before, recipe_id=RECIPE, layout_sha256=LAYOUT_SHA,
        layout=str(code/'config/bev_closeup/layout.json'), code=str(code), code_sha256=hashes,
        release_sha=args.sha, task_root=str(TASK), browser_cache='/tmp/manual-sidecar-browsers',
        local_template=str(TASK/'local-fallback/20261030T0926Z'),
        source_worker=str(TASK/'local-fallback/20261030T0926Z/source_worker.py'),
        frozen_executor_sha256={str(TASK/file): expected for file, expected in FROZEN.items()})
    save(directory/'control.json', profile)
    save(directory/'before.json', dict(orion=orion, media=media, original_launch_sha256=sha(launch)))
    (directory/'original-media-launch.sh').write_bytes(launch.read_bytes())
    # This wrapper calls original controller.main and uses its lifetime lock.
    old = 'tools/manual_sidecar/controller.py'
    script = launch.read_text()
    if script.count(old) != 1:
        raise ValueError('unexpected_launch_entrypoint')
    pending = launch.with_suffix('.closeup-pending')
    pending.write_text(script.replace(old, str(code/'scripts/bev_closeup/media_wrapper.py')))
    pending.chmod(launch.stat().st_mode & 0o777)
    args.switch_started = True
    pending.replace(launch)
    # Existing Orion exits at its normal batch boundary; do not kill downloads.
    (TASK/'orion/STOP').touch()
    wait_exit(args.orion_pid, args.orion_ticks, 300)
    # Freeze only the exact, idle personal controller for the final child check.
    # Always resume on failure; production model/Capture services are untouched.
    frozen = False
    try:
        current = process(args.media_pid)
        if current['start_ticks'] != args.media_ticks:
            raise ValueError('media_identity_changed_before_switch')
        os.kill(args.media_pid, signal.SIGSTOP)
        frozen = True
        current = process(args.media_pid)
        if current['children']:
            raise ValueError('media_started_work_before_switch')
        os.kill(args.media_pid, signal.SIGTERM)
        os.kill(args.media_pid, signal.SIGCONT)
        frozen = False
        wait_exit(args.media_pid, args.media_ticks, 60)
    finally:
        if frozen:
            os.kill(args.media_pid, signal.SIGCONT)
    (TASK/'orion/STOP').unlink()
    subprocess.run([str(REPO/'.venv-ares-animation/bin/python'), str(code/'scripts/bev_closeup/ensure_daily.py')],
                   cwd=TASK, check=True)
    # Preserve every other cron entry; this guard only restarts our owned process.
    line = f'*/5 * * * * {REPO}/.venv-ares-animation/bin/python {code}/scripts/bev_closeup/ensure_daily.py >> {directory}/ensure.private.log 2>&1'
    (directory/'crontab-before.txt').write_text(cron)
    subprocess.run(['crontab','-'], input=cron.rstrip()+'\n'+marker+'\n'+line+'\n# END RA_BEV_CLOSEUP_DAILY\n',
                   text=True, check=True)
    save(directory/'activation.json', dict(state='activated_scheduled', release_sha=args.sha,
         not_before=not_before, activated_at=time.time(), layout_sha256=LAYOUT_SHA,
         original_media_launch_sha256=ORIGINAL_LAUNCH_SHA, media_launch_sha256=sha(launch),
         shared_local_slots=2, old_controllers=dict(orion=orion,media=media),
         new_orion=read(TASK/'orion/controller-launch.json')))
    print(json.dumps(dict(state='activated_scheduled', not_before=not_before, release_sha=args.sha)))


def rollback_failed_switch():
    """Restore only our own changed entrypoint; never take over another owner."""
    directory = TASK/'daily-sidecar'
    profile = read(directory/'control.json')
    backup = directory/'original-media-launch.sh'
    launch = REPO/'tools/manual_sidecar/launch.sh'
    if not backup.exists() or not profile:
        return
    expected = backup.read_text().replace('tools/manual_sidecar/controller.py',
               str(Path(profile['code'])/'scripts/bev_closeup/media_wrapper.py'))
    if launch.read_text() != expected:
        return
    launch.write_bytes(backup.read_bytes())
    save(directory/'control.json', dict(profile, enabled=False))
    before = read(directory/'before.json')
    media = before['media']
    try:
        current = process(media['pid'])
        if current['start_ticks'] == media['start_ticks'] and current['state'] == 'T':
            os.kill(media['pid'], signal.SIGCONT)
    except FileNotFoundError:
        pass
    # If the original Orion process already drained, restart its original code
    # only when the lifetime lock is free. Preserve an active replacement.
    with (TASK/'worker.lock').open('a') as worker:
        try:
            fcntl.flock(worker, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
    (TASK/'orion/STOP').unlink(missing_ok=True)
    with (directory/'rollback.private.log').open('a') as log:
        child = subprocess.Popen([str(REPO/'.venv-ares-animation/bin/python'), '-u', str(TASK/'orion/controller.py')],
                                 cwd=TASK, stdout=log, stderr=log, start_new_session=True)
    current = process(child.pid)
    save(TASK/'orion/controller-launch.json', dict(pid=child.pid, started_at=time.time(),
         start_ticks=current['start_ticks'], command=str(TASK/'orion/controller.py'), cwd=str(TASK),
         source_sha256=sha(TASK/'orion/controller.py'), rollback=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sha', required=True)
    parser.add_argument('--not-before', required=True)
    parser.add_argument('--orion-pid', type=int, required=True)
    parser.add_argument('--orion-ticks', required=True)
    parser.add_argument('--media-pid', type=int, required=True)
    parser.add_argument('--media-ticks', required=True)
    args = parser.parse_args()
    try:
        activate(args)
    except Exception as exc:
        if getattr(args, 'switch_started', False):
            rollback_failed_switch()
        save(TASK/'daily-sidecar/activation-failure.json', dict(code=type(exc).__name__, at=time.time()))
        raise
