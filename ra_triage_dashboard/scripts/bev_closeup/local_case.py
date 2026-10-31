import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

F = Path(os.environ['BEV_CLOSEUP_ATTEMPT_DIR']).resolve()
B = Path(os.environ['BEV_CLOSEUP_TASK_ROOT']).resolve()
R = Path('/volume/home/workspace/ra_auto_triage')
SHARED = Path('/volume/home/workspace/ra_triage_dashboard_deploy/experiments/manual_dashboard_product_ux_20260922/production-readiness-20261009/candidate/data/planning_constraints/worker.lock')
sys.path.insert(0, str(R))
sys.path.insert(0, str(B / 'code/ra_triage_dashboard/scripts/bev_closeup'))
import coordinator as C
import ares_animation.workflow as workflow
from ares_animation.layout.input import load_layout_snapshot
from ares_animation.render.animation_protocol import AnimationProtocol
from ares_animation.recording import renderer

ISSUE = sys.argv[1]
CASE = F / 'runs' / ISSUE
CASE.mkdir(parents=True, exist_ok=True)

def save(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.pending')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    temp.replace(path)

def event(name, **kwargs):
    with (CASE / 'events.jsonl').open('a') as stream:
        stream.write(json.dumps({'time': time.time(), 'event': name, **kwargs}) + '\n')

def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024**2), b''): h.update(block)
    return h.hexdigest()

def retain_closed_source(path):
    # A bounded local-input stream retains bytes on disk after its own writer exits.
    # Release only this task's closed-file pages; never change global/online cache settings.
    path = Path(path)
    path.resolve().relative_to(CASE.resolve())
    before = path.stat()
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        os.fdatasync(fd)
        os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
    finally: os.close(fd)
    after = path.stat()
    assert (before.st_ino, before.st_size, before.st_mtime_ns) == (after.st_ino, after.st_size, after.st_mtime_ns)
    event('owned_closed_input_stream_pages_released', file_name=path.name, bytes=after.st_size, content_size_mtime_unchanged=True)

def wait_resources():
    deadline = time.monotonic() + 1800
    while time.monotonic() < deadline:
        state = C.resource_state()
        disk = os.statvfs(F)
        if state['status'] == 'ready' and disk.f_bavail * disk.f_frsize >= 10 * 1024**3:
            return
        event('resource_wait', resources=state)
        time.sleep(5)
    raise RuntimeError('Original resource admission gate remained unavailable')

def bounded_inputs(row, *, layout, output, duration_ms):
    root = Path(output)
    root.mkdir(parents=True, exist_ok=True)
    topics = sorted(set(load_layout_snapshot(layout)['topics']) | workflow.acquire_local_inputs_original_topics)
    half = duration_ms // 2 + 500
    start = int(row['capture_timestamp_ms']) - half
    end = int(row['capture_timestamp_ms']) + half
    metadata = root / 'trip-meta.yaml'
    bags = []

    def window(left, right, depth=0):
        key = f'{left}-{right}'
        bag = root / (key + '.bag')
        receipt = root / (key + '-receipt.json')
        intent = {'trip_id': row['trip_id'], 'start_ms': left, 'end_ms': right, 'topics': topics}
        if receipt.exists():
            previous = json.loads(receipt.read_text())
            assert previous['intent'] == intent and sha(bag) == previous['sha256']
            retain_closed_source(bag)
            bags.append(bag)
            return
        capped_partials = [p for p in root.glob(key+'-*.part.bag') if p.stat().st_size >= 512*1024**2]
        if capped_partials:
            for partial in capped_partials: retain_closed_source(partial)
            event('reuse_prior_size_limit_evidence_split', start_ms=left, end_ms=right, preserved_partials=len(capped_partials))
            if right-left <= 262 or depth >= 8: raise RuntimeError('Source window cannot split further within existing limits')
            middle = (left+right)//2
            window(left, middle, depth+1)
            window(middle, right, depth+1)
            return
        wait_resources()
        request_file = root / (key + '-request.json')
        result_file = root / (key + '-result.json')
        partial = root / (key + f'-{time.time_ns()}.part.bag')
        request = {**intent, 'metadata': str(metadata), 'output': str(partial), 'result': str(result_file)}
        save(request_file, request)
        timed_out = False
        with SHARED.open('a+') as shared:
            event('waiting_shared_source_lock', start_ms=left, end_ms=right)
            fcntl.flock(shared, fcntl.LOCK_EX)
            wait_resources()
            with (root / (key + '-source.private.log')).open('ab') as log:
                child = subprocess.Popen([sys.executable, os.environ['BEV_CLOSEUP_SOURCE_WORKER'], str(request_file)], stdout=log, stderr=log, start_new_session=True)
                event('source_worker_started', pid=child.pid, start_ms=left, end_ms=right, file_limit_bytes=512*1024**2, address_limit_bytes=4*1024**3, timeout_sec=120)
                try:
                    child.wait(timeout=120)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    os.killpg(child.pid, signal.SIGTERM)
                    try: child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(child.pid, signal.SIGKILL)
                        child.wait(timeout=5)
        result = json.loads(result_file.read_text()) if result_file.exists() else {}
        if child.returncode == 0 and not timed_out:
            partial.replace(bag)
            save(receipt, {'intent': intent, 'sha256': sha(bag), 'bytes': bag.stat().st_size, 'resource_limits_verified': True})
            retain_closed_source(bag)
            bags.append(bag)
            event('source_window_saved', start_ms=left, end_ms=right, bytes=bag.stat().st_size)
            return
        event('source_window_failed', start_ms=left, end_ms=right, returncode=child.returncode, timed_out=timed_out, error_type=result.get('error_type'), partial_preserved=partial.exists())
        size_limited = partial.exists() and partial.stat().st_size >= 512*1024**2
        if partial.exists(): retain_closed_source(partial)
        splittable = timed_out or size_limited or child.returncode == -signal.SIGXFSZ or result.get('error_type') == 'MemoryError'
        if splittable and right-left > 262 and depth < 8:
            middle = (left+right)//2
            window(left, middle, depth+1)
            window(middle, right, depth+1)
            return
        raise RuntimeError(f'Bounded source window failed: {key}; original evidence preserved')

    for left in range(start, end, 8400): window(left, min(left+8400, end))
    save(root / 'bounded-input-receipt.json', {'issue_id': row['issue_id'], 'trip_id': row['trip_id'], 'start_ms': start, 'end_ms': end, 'bags': [{'path': str(b), 'sha256': sha(b), 'bytes': b.stat().st_size} for b in bags], 'metadata_sha256': sha(metadata), 'source_payload_unchanged': True})
    event('all_source_windows_saved', count=len(bags))
    return {**row, 'input_bags': [str(b) for b in bags], 'trip_meta': str(metadata)}

class TracedProtocol(AnimationProtocol):
    def __init__(self, page, events, remaining):
        super().__init__(page, events, remaining)
        self.last_time = None
        self.step_index = 0
        self.worker_count = 0
        page.on('worker', self.worker_created)
        page.on('console', self.console_event)

    def worker_created(self, worker):
        self.worker_count += 1
        event('browser_worker_created', count=self.worker_count)

    def console_event(self, message):
        text = message.text
        if text.startswith(('animation_get_message', 'animation_render_done', 'animation_map_done')):
            event('animation_marker', marker=text[:160], step=self.step_index)

    def current_time(self):
        try: value = super().current_time()
        except Exception as exc:
            event('clock_read_failed', step=self.step_index, error_type=type(exc).__name__, markers=len(self.events), workers=self.worker_count)
            if self.step_index != 0: raise
            # Initial markers precede currentTime publication in the frozen runtime.
            # Use the existing protocol time-readiness budget; never invent a clock or frame.
            deadline = min(time.monotonic()+3, time.monotonic()+self.remaining())
            attempts = 0
            while time.monotonic() < deadline:
                self.page.wait_for_timeout(20)
                attempts += 1
                try: value = super().current_time(); break
                except RuntimeError: continue
            else:
                self.capture_clock_state('bounded_initial_clock_wait_exhausted')
                raise
            event('initial_clock_became_readable', timestamp_ms=value, attempts=attempts,
                  readiness_budget_ms=3000, runtime_unchanged=True, actual_time_gate_unchanged=True)
        if value != self.last_time:
            event('clock_observed', timestamp_ms=value, step=self.step_index, markers=len(self.events))
            self.last_time = value
        return value

    def capture_clock_state(self, phase):
        diagnostic = {'at':time.time(),'phase':phase,'step':self.step_index,'events':self.events[-20:]}
        script = """() => {
          const body = document.body?.innerText || '';
          const leaves = [...document.querySelectorAll('*')].filter(e => e.children.length===0 && (/^\d{13}$/.test(e.textContent?.trim() || '') || /Trip\s*bag/i.test(e.textContent || ''))).slice(0,20).map(e => ({tag:e.tagName,cls:e.className,text:e.textContent?.slice(0,200),parent:e.parentElement?.outerHTML.slice(0,1600)}));
          const names = Object.getOwnPropertyNames(globalThis).filter(k=>k.startsWith('_animation')).slice(0,50);
          return {body_text:body.slice(0,20000),timestamp_candidates:body.match(/\d{13}/g),leaves,animation_globals:names.map(k=>({name:k,type:typeof globalThis[k],value:['number','string','boolean'].includes(typeof globalThis[k])?String(globalThis[k]).slice(0,100):null}))};
        }"""
        try:diagnostic['page']=self.page.evaluate(script)
        except Exception as exc:diagnostic['page_error_type']=type(exc).__name__
        diagnostic['workers']=[]
        for worker in self.page.workers:
            try:
                state=worker.evaluate("""() => Object.getOwnPropertyNames(globalThis).filter(k=>k.startsWith('_animation')).slice(0,50).map(k=>({name:k,type:typeof globalThis[k],value:['number','string','boolean'].includes(typeof globalThis[k])?String(globalThis[k]).slice(0,100):null}))""")
                diagnostic['workers'].append({'url':worker.url,'animation_globals':state})
            except Exception as exc:diagnostic['workers'].append({'error_type':type(exc).__name__})
        save(CASE/'init-clock-diagnostic.json',diagnostic)
        event('clock_state_snapshot_saved',phase=phase,workers=len(diagnostic['workers']),timestamp_candidates=(diagnostic.get('page') or {}).get('timestamp_candidates'))

    def step(self):
        self.step_index += 1
        before = len(self.events)
        event('step_begin', step=self.step_index, markers=before)
        super().step()
        event('step_markers_ready', step=self.step_index, markers=len(self.events), new_markers=self.events[before:][-6:])

from ares_animation.preparation.local_inputs import MANDATORY_TOPICS
workflow.acquire_local_inputs_original_topics = MANDATORY_TOPICS
workflow.acquire_local_inputs = bounded_inputs
renderer.AnimationProtocol = TracedProtocol
command = json.loads((F / 'canary-command.json').read_text())
args = command[3:]
args[args.index('--source-rows')+1] = str(F / (ISSUE+'-source.json'))
args[args.index('--out')+1] = str(CASE)
if '--no-auto-download-map' in args: args.remove('--no-auto-download-map')
args[args.index('--reduce-workers')+1] = '1'
event('local_prepare_execution', reduce_workers=1, physical_group_pss_budget_bytes=8*1024**3, original_admission_gate_unchanged=True)
event('local_case_started', issue_id=ISSUE, original_time_and_media_gates=True, source_windows_bounded=True)
for closed in (CASE / 'work/inputs').rglob('*.bag'):
    retain_closed_source(closed)
wait_resources()
from ares_animation.cli import main
try:
    result = main(args)
    event('local_case_finished', issue_id=ISSUE, exit_code=result)
    raise SystemExit(result)
except Exception as exc:
    save(CASE / 'local-failure.json', {'issue_id': ISSUE, 'time': time.time(), 'error_type': type(exc).__name__, 'details_private_log': True})
    event('local_case_failed', issue_id=ISSUE, error_type=type(exc).__name__)
    raise
