"""Versioned overlay on a pinned, byte-verified Ares tool; never rewrites its Release."""
import gzip
import hashlib
import json
from pathlib import Path
import tarfile
import tempfile

from ra_triage_dashboard.app.planning_text_artifact import digest

BASE_SHA = '65f93abc08a0a948afc48444a22ada04304fb2d37fa097497299c7c6955f2c28'
FILES = ('app/planning_constraint_extract.py', 'app/planning_constraints.py',
         'app/planning_text_artifact.py', 'scripts/planning_text/__init__.py',
         'scripts/planning_text/hook.py', 'scripts/planning_text/worker.py')


def source_manifest(code):
    files = {name: digest(Path(code)/name) for name in FILES}
    return files, hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()


def build(base, code, members, output):
    """Keep renderer/runtime bytes unchanged. The hook and ownership are explicit."""
    if digest(base) != BASE_SHA:
        raise ValueError('planning_base_tool_sha_mismatch')
    files, source_sha = source_manifest(code)
    manifest = dict(schema_version=1, base_tool_sha256=BASE_SHA,
                    worker_source_sha256=source_sha, files=files, members=members)
    output = Path(output)
    if output.exists():
        raise FileExistsError('planning_overlay_exists')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as temporary:
        root = Path(temporary)/'tool'
        root.mkdir()
        with tarfile.open(base) as archive:
            for member in archive.getmembers():
                target = (root/member.name).resolve()
                target.relative_to(root.resolve())
                if not (member.isfile() or member.isdir()):
                    raise ValueError('unsafe_base_tool_member')
                if member.size > 128*1024**2:
                    raise ValueError('oversized_base_tool_member')
            archive.extractall(root)
        for name in FILES:
            path = root/'ra_triage_dashboard'/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((Path(code)/name).read_bytes())
        for folder in ('ra_triage_dashboard', 'ra_triage_dashboard/app', 'ra_triage_dashboard/scripts'):
            (root/folder/'__init__.py').touch()
        (root/'planning-worker-manifest.json').write_text(json.dumps(manifest, sort_keys=True))
        target = root/'ares_animation/preparation/voyager.py'
        original = target.read_text()
        marker = '    bounds = pose_bounds(sources, margin_m=margin_m)'
        if original.count(marker) != 1:
            raise ValueError('planning_pre_reduction_hook_boundary_changed')
        hook = '''    # Versioned road-text overlay; independent failure does not fail video.
    try:
        from ra_triage_dashboard.scripts.planning_text.hook import before_reduce
        before_reduce(sources, trip_id, output, already_reduced=already_reduced)
    except Exception:
        pass  # Hook writes its own bounded, non-secret failure receipt.
'''
        target.write_text(original.replace(marker, hook+marker))
        tool_manifest = json.loads((root/'tool-manifest.json').read_text())
        tool_manifest['worker_overlay'] = {k: v for k, v in manifest.items() if k != 'members'}
        tool_manifest['files'] = {str(p.relative_to(root)): digest(p)
            for p in sorted(root.rglob('*')) if p.is_file() and p.name != 'tool-manifest.json'}
        (root/'tool-manifest.json').write_text(json.dumps(tool_manifest, sort_keys=True))
        with output.open('xb') as raw, gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as zipped:
            with tarfile.open(fileobj=zipped, mode='w') as archive:
                for path in sorted(root.rglob('*')):
                    info = archive.gettarinfo(str(path), arcname=str(path.relative_to(root)))
                    info.uid = info.gid = info.mtime = 0
                    info.uname = info.gname = ''
                    if path.is_file():
                        with path.open('rb') as stream:
                            archive.addfile(info, stream)
                    else:
                        archive.addfile(info)
    return dict(status='built', sha256=digest(output), bytes=output.stat().st_size,
                worker_source_sha256=source_sha, base_tool_sha256=BASE_SHA)
