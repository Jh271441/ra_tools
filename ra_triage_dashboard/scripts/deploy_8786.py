#!/usr/bin/env python3
"""Deploy an exact Git archive to the isolated 8786 experiment only.

Run on cloud_server with the dedicated dashboard interpreter. See
 docs/refactor-8786-operations.md. This does not migrate DBs or change config.
"""
from __future__ import annotations
import argparse
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
import time
import urllib.request

ROOT = Path('/volume/home/workspace/ra_triage_dashboard_deploy/experiments/manual_dashboard_product_ux_20260922')
PYTHON = Path('/volume/home/workspace/ra_triage_dashboard_venv/bin/python')
PROGRAM = 'ra_triage_dashboard_8786_dev'


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha(value: str) -> str:
    require(bool(re.fullmatch(r'[0-9a-f]{40}', value)), 'Expected a full lowercase Git SHA')
    return value


def config_fingerprints(root: Path) -> dict[str, str]:
    return {name: hashlib.sha256((root / 'config' / name).read_bytes()).hexdigest()
            for name in ('postgres_url', 'service_env.json')}


def archive_contents(archive: Path, expected_sha: str) -> dict[str, bytes]:
    """Validate Git identity and every path before writing anything."""
    sha(expected_sha)
    files = {}
    with tarfile.open(archive, 'r:*') as tar:
        require(tar.pax_headers.get('comment') == expected_sha, 'Archive Git SHA mismatch')
        for member in tar.getmembers():
            path = PurePosixPath(member.name)
            require(not path.is_absolute() and '..' not in path.parts and
                    path.parts and path.parts[0] == 'ra_triage_dashboard', 'Archive path outside dashboard')
            require(member.isdir() or member.isfile(), 'Archive links/devices are forbidden')
            if member.isfile():
                require(member.name not in files, 'Duplicate archive file')
                require(member.size <= 32 * 1024 * 1024, 'Unexpectedly large source file')
                files[member.name] = tar.extractfile(member).read()
    require('ra_triage_dashboard/app/main.py' in files, 'Missing dashboard application')
    return files


def stage_source(root: Path, commit: str, files: dict[str, bytes]) -> Path:
    source = root / ('source-' + sha(commit))
    if source.exists():
        current = {str(p.relative_to(source)): p.read_bytes() for p in source.rglob('*')
                   if p.is_file() and '__pycache__' not in p.parts and '.pytest_cache' not in p.parts}
        require(current == files, 'Existing immutable source differs from archive')
        return source
    temporary = root / ('source-' + commit + '.preparing')
    require(not temporary.exists(), 'Source staging directory already exists; inspect it first')
    temporary.mkdir()
    for name, data in files.items():
        target = temporary / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    os.replace(temporary, source)
    return source


def protected_source_fingerprints(source: Path) -> dict[str, str]:
    app = source / 'ra_triage_dashboard'
    paths = list((app / 'migrations/postgres').glob('*.sql'))
    paths += [p for p in app.glob('requirements*.txt') if p.is_file()]
    return {str(p.relative_to(app)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def check_runtime_identity(root: Path, expected: str, config: dict[str, str]) -> None:
    require((root / 'config/source_sha').read_text().strip() == expected, '8786 source changed concurrently')
    require(config_fingerprints(root) == config, '8786 configuration changed concurrently')


def atomic_source_pointer(root: Path, commit: str) -> None:
    target = root / 'config/source_sha'
    temporary = target.with_suffix('.deploy.tmp')
    with temporary.open('w') as stream:
        stream.write(sha(commit) + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, target)


def health(port: int, prefix: str) -> dict:
    with urllib.request.urlopen(f'http://127.0.0.1:{port}{prefix}/health', timeout=5) as response:
        return json.load(response)


def wait_health(commit: str) -> dict:
    for attempt in range(30):
        try:
            result = health(8786, '/manual-s6')
            require(result.get('ok') and result.get('build_commit') == commit, '8786 health identity mismatch')
            return result
        except Exception:
            if attempt == 29:
                raise
            time.sleep(1)
    raise RuntimeError('Unreachable health wait')


def activate(root: Path, commit: str, previous: str, config: dict[str, str]) -> dict:
    check_runtime_identity(root, previous, config)
    production = health(8785, '/manual').get('build_commit')
    switched = False
    try:
        atomic_source_pointer(root, commit)
        switched = True
        subprocess.run([str(PYTHON), str(root / 'service/run_ux.py'), '--check'], check=True)
        subprocess.run(['sudo', 'supervisorctl', 'restart', PROGRAM], check=True)
        live = wait_health(commit)
        check_runtime_identity(root, commit, config)
        require(health(8785, '/manual').get('build_commit') == production, '8785 changed during deployment')
        return {'health': live, 'production_sha': production}
    except BaseException:
        if switched:
            # Never clobber another operator's subsequent source switch.
            require((root / 'config/source_sha').read_text().strip() == commit,
                    'Concurrent source switch; automatic rollback stopped')
            atomic_source_pointer(root, previous)
            subprocess.run(['sudo', 'supervisorctl', 'restart', PROGRAM], check=True)
            wait_health(previous)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sha', required=True, type=sha)
    parser.add_argument('--expected-current', required=True, type=sha)
    parser.add_argument('--archive', required=True, type=Path)
    parser.add_argument('--evidence-dir', required=True, type=Path)
    parser.add_argument('--baseline-url-file', required=True, type=Path)
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    root = ROOT.resolve()
    evidence = args.evidence_dir.resolve()
    require(root in evidence.parents, 'Evidence must remain inside the experiment')
    evidence.mkdir(exist_ok=True, parents=True)
    # All invocations use one lock; immutable source is staged only after identity checks.
    with (root / 'service/deploy.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        config = config_fingerprints(root)
        check_runtime_identity(root, args.expected_current, config)
        previous = root / ('source-' + args.expected_current)
        candidate = stage_source(root, args.sha, archive_contents(args.archive, args.sha))
        require(protected_source_fingerprints(previous) == protected_source_fingerprints(candidate),
                'Schema/dependency changes require a separate reviewed migration workflow')
        # Require an isolated fixture URL, never initialize or capture a live DB by accident.
        from psycopg.conninfo import conninfo_to_dict
        dbname = conninfo_to_dict(args.baseline_url_file.read_text().strip())['dbname']
        require(dbname.startswith('manual_refactor'), 'Behavior comparison requires a named refactor fixture')
        capture = candidate / 'ra_triage_dashboard/scripts/capture_refactor_contract.py'
        outputs = []
        for label, source in [('before', previous), ('after', candidate)]:
            output = evidence / (label + '.json.gz')
            subprocess.run([str(PYTHON), str(capture), '--source-root', str(source / 'ra_triage_dashboard'),
                            '--url-file', str(args.baseline_url_file), '--env-file', str(root / 'config/service_env.json'),
                            '--output', str(output)], check=True)
            with gzip.open(output, 'rb') as stream:
                outputs.append(stream.read())
        require(outputs[0] == outputs[1], 'Frozen-database/API behavior changed; refusing deployment')
        with (evidence / 'tests.log').open('w') as log:
            result = subprocess.run([str(PYTHON), '-m', 'pytest', 'ra_triage_dashboard/tests', '-q'],
                                    cwd=candidate, stdout=log, stderr=subprocess.STDOUT)
        tail = (evidence / 'tests.log').read_text().splitlines()[-15:]
        print('\n'.join(line[:500] for line in tail), flush=True)
        require(result.returncode == 0, 'Full regression gate failed; inspect tests.log')
        check_runtime_identity(root, args.expected_current, config)
        receipt = {'sha': args.sha, 'previous': args.expected_current, 'config_hashes': config,
                   'archive_sha256': hashlib.sha256(args.archive.read_bytes()).hexdigest(),
                   'contract_sha256': hashlib.sha256(outputs[1]).hexdigest(), 'tests': tail[-1],
                   'activated': False}
        (evidence / 'verified.json').write_text(json.dumps(receipt, indent=2))
        if not args.check_only:
            receipt.update(activate(root, args.sha, args.expected_current, config))
            receipt['activated'] = True
            (evidence / 'release.json').write_text(json.dumps(receipt, indent=2))
        print(json.dumps({k: receipt[k] for k in ['sha', 'previous', 'tests', 'activated']}), flush=True)


if __name__ == '__main__':
    main()
