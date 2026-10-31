"""One durable closeup local attempt; admission belongs to the original sidecar."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from offline_daily import control, enabled, read, save, sha, numeric_attempt, REPO


def environment(attempt, profile):
    sys.path.insert(0, str(REPO))
    from ares_animation.adapters.voyager import load_voyager_environment
    _, env = load_voyager_environment()
    for key in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy']:
        env.pop(key, None)
    data = attempt/'data'
    data.mkdir(exist_ok=True)
    for source in Path(env['VOY_DATA_DIR']).iterdir():
        target = data/source.name
        if source.name != 'hdmap_files' and not target.exists():
            target.symlink_to(source, target_is_directory=source.is_dir())
    env.update(VOY_DATA_DIR=str(data), XDG_CACHE_HOME=str(attempt/'cache'),
               PYTHONPYCACHEPREFIX=str(attempt/'pycache'),
               PLAYWRIGHT_BROWSERS_PATH=profile['browser_cache'],
               BEV_CLOSEUP_ATTEMPT_DIR=str(attempt), BEV_CLOSEUP_TASK_ROOT=profile['task_root'],
               BEV_CLOSEUP_SOURCE_WORKER=profile['source_worker'],
               OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1',
               NO_PROXY='*', no_proxy='*')
    return env


def processes(root_pid):
    records = {}
    for path in Path('/proc').iterdir():
        if not path.name.isdigit():
            continue
        try:
            fields = (path/'stat').read_text().rsplit(') ', 1)[1].split()
            rss = int(fields[21])*os.sysconf('SC_PAGE_SIZE')
            try:
                pss = next(int(line.split()[1])*1024 for line in (path/'smaps_rollup').read_text().splitlines() if line.startswith('Pss:'))
            except (OSError, StopIteration):
                pss = rss
            records[int(path.name)] = dict(pid=int(path.name), ppid=int(fields[1]), start_ticks=fields[19], pss=pss)
        except (OSError, ValueError, IndexError):
            pass
    owned = {root_pid}
    while True:
        more = {pid for pid, r in records.items() if r['ppid'] in owned} - owned
        if not more:
            return [records[p] for p in owned if p in records]
        owned |= more


def stop_owned(child, known):
    for sig in [signal.SIGTERM, signal.SIGKILL]:
        for record in reversed(known):
            try:
                fields = (Path('/proc')/str(record['pid'])/'stat').read_text().rsplit(') ', 1)[1].split()
                if fields[19] == record['start_ticks']:
                    os.kill(record['pid'], sig)
            except OSError:
                pass
        if sig == signal.SIGTERM:
            time.sleep(3)
    child.wait(timeout=15)


def scratch_bytes(attempt):
    total, seen = 0, set()
    for folder, _, names in os.walk(attempt, followlinks=False):
        for name in names:
            path = Path(folder)/name
            if path.is_symlink():
                continue
            try:
                info = path.stat()
            except OSError:
                continue
            inode = info.st_dev, info.st_ino
            if inode not in seen:
                total += info.st_size
                seen.add(inode)
    return total


def main():
    os.umask(0o077)
    attempt = Path(sys.argv[1]).resolve()
    numeric_attempt(attempt)
    claim = read(attempt/'claim.json')
    root = Path(claim['closeup_task_root'])
    profile = control(root)
    if not enabled(profile) or claim['closeup_code'] != profile['code']:
        raise ValueError('local_closeup_not_activated')
    for file, expected in profile['frozen_executor_sha256'].items():
        if sha(file) != expected:
            raise ValueError('frozen_local_executor_changed')
    row = claim['row']
    save(attempt/'started.json', dict(started_at=time.time(), pid=os.getpid(), attempt=int(attempt.name)))
    save(attempt/(row['issue_id']+'-source.json'), [row])
    # Preserve the previously verified local recipe/flags, replacing only this
    # frozen source, layout and per-attempt output location in local_case.py.
    command = read(Path(profile['local_template'])/'canary-command.json')
    command[command.index('--layout-json')+1] = profile['layout']
    save(attempt/'canary-command.json', command)
    code = Path(profile['code'])/'scripts/bev_closeup/local_case.py'
    policy = read(Path(profile['code'])/'config/bev_closeup/recovery-policy.json')
    env = environment(attempt, profile)
    with (attempt/'render.private.log').open('a') as log:
        child = subprocess.Popen([sys.executable, '-u', str(code), row['issue_id']],
                                 cwd=REPO, env=env, stdout=log, stderr=log, start_new_session=True)
        started = time.monotonic()
        last_scratch = 0
        while child.poll() is None:
            owned = processes(child.pid)
            reason = None
            if sum(p['pss'] for p in owned) > 8*1024**3:
                reason = 'local_group_memory_limit'
            if time.monotonic()-started > policy['local_deadline_seconds']:
                reason = 'local_deadline'
            disk = os.statvfs(attempt)
            if disk.f_bavail*disk.f_frsize < 10*1024**3:
                reason = 'disk_reserve'
            if time.monotonic()-last_scratch >= 10:
                if scratch_bytes(attempt) > 40*1024**3:
                    reason = 'scratch_limit'
                last_scratch = time.monotonic()
            if reason:
                stop_owned(child, owned)
                save(attempt/'result.json', dict(state='failed', code=reason, finished_at=time.time()))
                return
            time.sleep(2)
    save(attempt/'result.json', dict(state='rendered' if child.returncode == 0 else 'failed',
         returncode=child.returncode, finished_at=time.time(), publication_pending=child.returncode == 0))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        save(Path(sys.argv[1])/'result.json', dict(state='failed', code=type(exc).__name__, finished_at=time.time()))
        raise
