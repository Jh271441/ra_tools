#!/usr/bin/env python3
"""Read-only, bounded filesystem inventory for a Manual host migration.

Spec: {"roots": [{"id": "...", "path": "/...", "category": "copy"}]}.
Symlinks are recorded, never traversed. Their targets require explicit roots.
Metadata mode hashes JSON/JSONL/config files up to 16 MiB; payload hashes remain
pending until --hash-mode all or transfer verification. No source file is edited.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def inventory(spec, output, hash_mode='metadata'):
    output = Path(output).resolve()
    roots = spec['roots']
    ids = [r['id'] for r in roots]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate root IDs')
    for root in roots:
        source = Path(root['path']).absolute()
        if not source.is_absolute() or output == source or source in output.parents:
            raise ValueError('Output must be outside every source root')
    output.mkdir(parents=True, exist_ok=True)
    summary = {'schema_version': 1, 'started_at': datetime.now(timezone.utc).isoformat(),
               'hash_mode': hash_mode, 'roots': [], 'errors': 0,
               'warning': 'Live observation, not a frozen cutover snapshot; symlinks require review.'}
    inodes = set()
    unique_bytes = 0
    with (output / 'files.jsonl').open('x') as dest:
        for root in roots:
            source = Path(root['path']).absolute()
            counts = Counter()
            stack = [source]
            while stack:
                path = stack.pop()
                row = {'root_id': root['id'], 'relative_path': str(path.relative_to(source)),
                       'category': root.get('category', 'copy')}
                try:
                    before = path.lstat()
                    row.update(size=before.st_size, allocated_bytes=before.st_blocks * 512,
                               device=before.st_dev, inode=before.st_ino, nlink=before.st_nlink,
                               mtime_ns=before.st_mtime_ns)
                    if stat.S_ISLNK(before.st_mode):
                        row.update(type='symlink', target=os.readlink(path),
                                   resolved_target=str(path.resolve()), target_exists=path.exists())
                        counts['symlinks'] += 1
                    elif stat.S_ISDIR(before.st_mode):
                        counts['directories'] += 1
                        stack.extend(sorted(path.iterdir(), reverse=True))
                        continue
                    elif stat.S_ISREG(before.st_mode):
                        row['type'] = 'file'
                        counts['files'] += 1
                        counts['logical_bytes'] += before.st_size
                        counts['allocated_bytes'] += before.st_blocks * 512
                        identity = (before.st_dev, before.st_ino)
                        if identity not in inodes:
                            inodes.add(identity)
                            unique_bytes += before.st_size
                        do_hash = hash_mode == 'all' or (before.st_size <= 16 * 1024**2 and path.suffix.lower() in {'.json', '.jsonl', '.yaml', '.yml', '.csv', '.xlsx', '.txt'})
                        row['sha256'] = digest(path) if do_hash else None
                        after = path.stat()
                        row['stable_during_read'] = (before.st_size, before.st_mtime_ns, before.st_ino) == (after.st_size, after.st_mtime_ns, after.st_ino)
                        if not row['stable_during_read']:
                            row['sha256'] = None
                            counts['changed_during_read'] += 1
                        counts['hashed_files' if row['sha256'] else 'pending_hash_files'] += 1
                    else:
                        row['type'] = 'special'
                        counts['special'] += 1
                except OSError as exc:
                    row.update(type='error', error=str(exc))
                    summary['errors'] += 1
                    counts['errors'] += 1
                dest.write(json.dumps(row, ensure_ascii=False) + '\n')
            summary['roots'].append({**root, **counts})
    summary['unique_source_inode_bytes'] = unique_bytes
    summary['finished_at'] = datetime.now(timezone.utc).isoformat()
    summary['manifest_sha256'] = digest(output / 'files.jsonl')
    (output / 'summary.json').write_text(json.dumps(summary, indent=2))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--hash-mode', choices=['metadata', 'all'], default='metadata')
    args = parser.parse_args()
    result = inventory(json.loads(args.spec.read_text()), args.output, args.hash_mode)
    print(json.dumps(result))
    return 1 if result['errors'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
