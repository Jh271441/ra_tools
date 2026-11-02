"""Owned sidecar watchdog; the controller's worker.lock remains authoritative."""
import fcntl
import os
from pathlib import Path
import subprocess
import sys
import time

from offline_daily import TASK, REPO, control, read, save


def ensure_importer(profile):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from ra_triage_dashboard.scripts.planning_text.runner import selected_control
    text = selected_control()
    if not text:
        return
    root = Path(text['data_dir'])/'planning_constraints'
    root.mkdir(parents=True, exist_ok=True)
    with (root/'importer.lock').open('a') as importer:
        try:
            fcntl.flock(importer, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
    command = Path(text['code'])/'scripts/planning_text/import_results.py'
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():
            continue
        try:
            if str(command) in (proc/'cmdline').read_bytes().decode().split('\0'):
                return  # Bootstrap may still be acquiring the singleton lock.
        except (OSError, UnicodeError):
            continue
    with (TASK/'planning-text/importer.private.log').open('a') as log:
        child = subprocess.Popen([str(REPO/'.venv-ares-animation/bin/python'), '-u', str(command)],
                                 cwd=REPO, stdout=log, stderr=log, start_new_session=True)
    stat = (Path('/proc')/str(child.pid)/'stat').read_text().rsplit(') ',1)[1].split()
    save(TASK/'planning-text/importer-launch.json', dict(pid=child.pid, start_ticks=stat[19],
         started_at=time.time(), command=str(command), cwd=str(REPO), release_sha=profile['release_sha']))


def main():
    profile = control(TASK)
    if not profile:
        return
    directory = TASK/'daily-sidecar'
    with (directory/'ensure.lock').open('a') as guard:
        try:
            fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        # Published text can arrive while video downloads or a controller drain
        # holds worker.lock. Its importer never creates a Bag/render worker.
        ensure_importer(profile)
        with (TASK/'worker.lock').open('a') as worker:
            try:
                fcntl.flock(worker, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return
        if (TASK/'orion/STOP').exists():
            return
        # A live owned process between startup and lock acquisition is also
        # preserved. Do not infer death from a stale progress file.
        for proc in Path('/proc').iterdir():
            if not proc.name.isdigit():
                continue
            try:
                argv = (proc/'cmdline').read_bytes().decode().split('\0')
                if (os.readlink(proc/'cwd') == str(TASK) and any(
                        a.endswith('/orion_controller.py') or a == str(TASK/'orion/controller.py') for a in argv)):
                    return
            except (OSError, UnicodeError):
                continue
        command = Path(profile['code'])/'scripts/bev_closeup/orion_controller.py'
        with (directory/'controller.private.log').open('a') as log:
            child = subprocess.Popen([str(REPO/'.venv-ares-animation/bin/python'), '-u', str(command)],
                                     cwd=TASK, stdout=log, stderr=log, start_new_session=True)
        stat = (Path('/proc')/str(child.pid)/'stat').read_text().rsplit(') ',1)[1].split()
        save(TASK/'orion/controller-launch.json', dict(pid=child.pid, started_at=time.time(),
             start_ticks=stat[19], command=str(command), cwd=str(TASK),
             source_sha256=profile['code_sha256']['scripts/bev_closeup/orion_controller.py'],
             release_sha=profile['release_sha'], activation=str(directory/'activation.json')))


if __name__ == '__main__':
    main()
