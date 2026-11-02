"""Promote an exact deployed source into the existing personal media controllers.

Dashboard promotion is owned by deploy_cloud.py. This separate operation drains
only the two verified personal-media controllers and preserves all source/retry
ledgers, layout, resource policy and other cron entries.
"""
import argparse
import fcntl
import io
import json
import os
from pathlib import Path
import signal
import shlex
import subprocess
import sys
import tarfile
import time
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'bev_closeup'))
from activate_daily import process, owns_lock, wait_exit
from offline_daily import TASK, REPO, LAYOUT_SHA, control, read, save, sha
from ra_triage_dashboard.scripts.planning_text.bundle import BASE_SHA, source_manifest

DATA = Path('/volume/home/workspace/ra_triage_dashboard_deploy/experiments/manual_dashboard_product_ux_20260922/production-readiness-20261009/candidate/data')
TOOLS = Path('/volume/home/workspace/ra_tools')


def active_media_entry():
    lines = (REPO/'tools/manual_sidecar/launch.sh').read_text().splitlines()
    entries = [part for line in lines if line.startswith('exec ') for part in shlex.split(line)
               if part.endswith('/scripts/bev_closeup/media_wrapper.py')]
    if len(entries) != 1:
        raise ValueError('unexpected_media_launch_entrypoint')
    entry = Path(entries[0])
    relative = entry.relative_to(TASK/'daily-sidecar/releases')
    expected = subprocess.check_output(['git', 'show', relative.parts[0]+':'+str(Path(*relative.parts[1:]))], cwd=TOOLS)
    if expected != entry.read_bytes():
        raise ValueError('active_media_release_changed')
    return str(entry)


def controllers(code, media_entry=None):
    expected = dict(orion=(str(code/'scripts/bev_closeup/orion_controller.py'), str(TASK), TASK/'worker.lock'),
                    media=(media_entry or str(code/'scripts/bev_closeup/media_wrapper.py'), str(REPO), REPO/'reports/manual_sidecar_20261019/controller.lock'))
    found = {name: [] for name in expected}
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():
            continue
        try:
            current = process(int(proc.name))
            if current['state'] == 'Z':
                continue
            for name, (command, cwd, lock) in expected.items():
                if command in current['argv'] and current['cwd'] == cwd and owns_lock(current['pid'], lock):
                    found[name].append(current)
        except (OSError, UnicodeError, ProcessLookupError):
            continue
    if any(len(value) != 1 for value in found.values()):
        raise ValueError('personal_controller_identity_not_unique')
    return {name: value[0] for name, value in found.items()}


def preflight(args):
    if subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=TOOLS, text=True).strip() != args.sha:
        raise ValueError('production_checkout_not_release')
    with urlopen('http://127.0.0.1:8785/health', timeout=10) as response:
        health = json.load(response)
    if health.get('ok') is not True or health.get('build_commit') != args.sha or health.get('storage') != 'postgres':
        raise ValueError('dashboard_exact_release_required')
    profile = control(TASK)
    if not profile or profile['release_sha'] != args.expected_release:
        raise ValueError('sidecar_changed_during_promotion')
    if (TASK/'orion/STOP').exists() or not (TASK/'STOP').exists():
        raise ValueError('unexpected_operator_stop_state')
    if read(TASK/'planning-text/control.json').get('enabled'):
        raise ValueError('text_control_already_active_requires_reconciliation')
    canary = read(Path(args.canary)/'acceptance.json')
    source = TOOLS/'ra_triage_dashboard'
    _, worker_sha = source_manifest(source)
    if (canary.get('status') != 'passed' or canary.get('worker_source_sha256') != worker_sha
            or canary.get('base_tool_sha256') != BASE_SHA or canary.get('layout_sha256') != LAYOUT_SHA
            or canary.get('media', {}).get('status') != 'verified'
            or canary.get('media', {}).get('frame_count') != 400
            or canary.get('media', {}).get('maximum_frame_time_error_ms', 2) > 1
            or canary.get('text', {}).get('frame_count', 0) <= 0
            or canary.get('text', {}).get('independent_audit') != 'passed'):
        raise ValueError('exact_worker_canary_not_accepted')
    current = controllers(Path(profile['code']), active_media_entry())
    return profile, current, worker_sha


def install_release(sha_value):
    release = TASK/'daily-sidecar/releases'/sha_value
    release.mkdir(parents=True, exist_ok=False)
    paths = ['ra_triage_dashboard/scripts/bev_closeup', 'ra_triage_dashboard/scripts/planning_text',
             'ra_triage_dashboard/config/bev_closeup']
    paths += ['ra_triage_dashboard/app/'+name for name in (
        '__init__.py', 'planning_constraint_extract.py', 'planning_constraints.py',
        'planning_constraint_index.py', 'planning_text_artifact.py', 'planning_text_daily.py')]
    archive = subprocess.check_output(['git', 'archive', sha_value, *paths], cwd=TOOLS)
    with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
        for item in stream.getmembers():
            (release/item.name).resolve().relative_to(release.resolve())
            if not (item.isfile() or item.isdir()):
                raise ValueError('unsafe_sidecar_release_member')
        stream.extractall(release)
    return release/'ra_triage_dashboard'


def idle_stop(current, command, lock):
    """Stop only this exact idle controller, with a final frozen child check."""
    pid, ticks = current['pid'], current['start_ticks']
    fresh = process(pid)
    if fresh['start_ticks'] != ticks or command not in fresh['argv'] or not owns_lock(pid, lock):
        raise ValueError('media_identity_changed_before_drain')
    frozen = False
    try:
        os.kill(pid, signal.SIGSTOP)
        frozen = True
        fresh = process(pid)
        if fresh['children']:
            raise ValueError('media_controller_busy_preserved')
        os.kill(pid, signal.SIGTERM)
        os.kill(pid, signal.SIGCONT)
        frozen = False
        wait_exit(pid, ticks, 60)
    finally:
        if frozen:
            os.kill(pid, signal.SIGCONT)


def promote(args):
    directory = TASK/'daily-sidecar'
    record = directory/'promotions'/args.sha
    record.mkdir(parents=True, exist_ok=True)
    if (record/'activation.json').exists():
        raise ValueError('promotion_already_recorded_requires_reconciliation')
    with (directory/'activation.lock').open('a') as activation, (directory/'ensure.lock').open('a') as ensure:
        fcntl.flock(activation, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(ensure, fcntl.LOCK_EX | fcntl.LOCK_NB)
        profile, before, worker_sha = preflight(args)
        if not args.apply:
            print(json.dumps(dict(status='ready', release_sha=args.sha,
                worker_source_sha256=worker_sha, controllers=before)))
            return
        code = install_release(args.sha)
        hashes = {str(p.relative_to(code)): sha(p) for p in code.rglob('*') if p.is_file()}
        if hashes['config/bev_closeup/layout.json'] != LAYOUT_SHA:
            raise ValueError('pinned_layout_changed')
        launch = REPO/'tools/manual_sidecar/launch.sh'
        old_entry = active_media_entry()
        old_launch = launch.read_text()
        cron = subprocess.check_output(['crontab', '-l'], text=True)
        old_ensure = str(Path(profile['code'])/'scripts/bev_closeup/ensure_daily.py')
        if old_launch.count(old_entry) != 1 or cron.count(old_ensure) != 1:
            raise ValueError('personal_launch_or_cron_changed')
        if before['media']['children']:
            raise ValueError('media_controller_busy_retry_at_boundary')
        save(record/'before.json', dict(profile=profile, controllers=before, launch_sha256=sha(launch)))
        (record/'launch-before.sh').write_text(old_launch)
        (record/'crontab-before.txt').write_text(cron)
        (record/'activation-before.json').write_bytes((directory/'activation.json').read_bytes())
        changed = False
        try:
            (TASK/'orion/STOP').touch()
            print(json.dumps(dict(stage='draining_owned_orion', pid=before['orion']['pid'])), flush=True)
            wait_exit(before['orion']['pid'], before['orion']['start_ticks'], 600)
            idle_stop(before['media'], old_entry, REPO/'reports/manual_sidecar_20261019/controller.lock')
            save(record/'drained.json', dict(at=time.time(), controllers=before))
            new = dict(profile, code=str(code), code_sha256=hashes, release_sha=args.sha,
                       layout=str(code/'config/bev_closeup/layout.json'))
            text = dict(enabled=True, code=str(code), code_sha256=hashes, release_sha=args.sha,
                data_dir=str(DATA), base_tool=str(REPO/'bags/releases/ares_animation_bd9f187/tool.tar.gz'),
                worker_source_sha256=worker_sha, promoted_at=time.time())
            changed = True
            save(TASK/'planning-text/control.json', text)
            save(directory/'control.json', new)
            pending = launch.with_suffix('.planning-pending')
            pending.write_text(old_launch.replace(old_entry, str(code/'scripts/bev_closeup/media_wrapper.py')))
            pending.chmod(launch.stat().st_mode & 0o777)
            pending.replace(launch)
            subprocess.run(['crontab', '-'], input=cron.replace(old_ensure, str(code/'scripts/bev_closeup/ensure_daily.py')),
                           text=True, check=True)
            (TASK/'orion/STOP').unlink()
            with (record/'startup.private.log').open('a') as log:
                media_child = subprocess.Popen(['bash', str(launch)], cwd=REPO, stdout=log, stderr=log, start_new_session=True)
                save(record/'media-launch.json', dict(pid=media_child.pid, at=time.time(), command=str(launch)))
            # Call ensure after releasing its guard. No second controller may start meanwhile.
            fcntl.flock(ensure, fcntl.LOCK_UN)
            subprocess.run([str(REPO/'.venv-ares-animation/bin/python'), str(code/'scripts/bev_closeup/ensure_daily.py')],
                           cwd=TASK, check=True, timeout=90)
            until = time.monotonic()+60
            while True:
                try:
                    after = controllers(code)
                    break
                except ValueError:
                    if time.monotonic() >= until:
                        raise
                    time.sleep(1)
            activation_record = dict(state='activated', release_sha=args.sha, previous_release_sha=profile['release_sha'],
                activated_at=time.time(), worker_source_sha256=worker_sha, layout_sha256=LAYOUT_SHA,
                previous=before, controllers=after, importer=read(TASK/'planning-text/importer-launch.json'),
                canary=str(Path(args.canary)/'acceptance.json'), canary_sha256=sha(Path(args.canary)/'acceptance.json'),
                not_before=profile['not_before'], shared_local_slots=2,
                preserved_frozen_executor_sha256=profile['frozen_executor_sha256'])
            save(record/'activation.json', activation_record)
            save(directory/'activation.json', activation_record)
            save(TASK/'planning-text/activation.json', activation_record)
            print(json.dumps(dict(state='activated', release_sha=args.sha, worker_source_sha256=worker_sha)))
        except Exception as exc:
            save(record/'failure.json', dict(error_type=type(exc).__name__, controls_changed=changed, at=time.time()))
            if not changed:
                # Only the old verified code may resume; no replacement was started.
                (TASK/'orion/STOP').unlink(missing_ok=True)
                fcntl.flock(ensure, fcntl.LOCK_UN)
                subprocess.run([str(REPO/'.venv-ares-animation/bin/python'),
                                str(Path(profile['code'])/'scripts/bev_closeup/ensure_daily.py')], cwd=TASK, check=True, timeout=90)
                try:
                    old_media_live = owns_lock(before['media']['pid'], REPO/'reports/manual_sidecar_20261019/controller.lock')
                except OSError:
                    old_media_live = False
                if not old_media_live:
                    with (record/'resume-previous.private.log').open('a') as log:
                        subprocess.Popen(['bash', str(launch)], cwd=REPO, stdout=log, stderr=log, start_new_session=True)
            # A changed/new owner is never killed or duplicated by rollback guesswork.
            raise


if __name__ == '__main__':
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sha', required=True)
    parser.add_argument('--expected-release', required=True)
    parser.add_argument('--canary', required=True)
    parser.add_argument('--apply', action='store_true')
    promote(parser.parse_args())
