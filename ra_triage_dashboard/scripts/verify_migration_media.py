#!/usr/bin/env python3
"""Verify an entire media batch against a complete source SHA-256 manifest."""
import argparse
import hashlib
import json
from pathlib import Path
import time


def verify(manifest, root_id, target):
    target=target.resolve(); checked=0; total=0; errors=[]; expected=set();start=time.monotonic()
    for line in manifest.open():
        row=json.loads(line)
        if row['root_id']!=root_id:continue
        if row['type']!='file' or not row.get('sha256') or not row.get('stable_during_read'):
            errors.append({'path':row['relative_path'],'error':'source_not_verified_regular_file'});continue
        rel=Path(row['relative_path']);p=(target/rel).resolve()
        if rel.is_absolute() or '..' in rel.parts or target not in p.parents:
            errors.append({'path':str(rel),'error':'path_escape'});continue
        expected.add(str(rel))
        try:
            before=p.stat()
            if before.st_size!=row['size']:raise ValueError('size_mismatch')
            h=hashlib.sha256()
            with p.open('rb') as f:
                for chunk in iter(lambda:f.read(4*1024**2),b''):h.update(chunk)
            after=p.stat()
            if h.hexdigest()!=row['sha256']:raise ValueError('sha256_mismatch')
            if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('changed_during_verify')
            checked+=1;total+=before.st_size
        except (OSError,ValueError) as exc:errors.append({'path':str(rel),'error':str(exc)})
    actual={str(p.relative_to(target)) for p in target.rglob('*') if p.is_file()}
    extras=sorted(actual-expected)
    if not expected:errors.append({'error':'empty_source_manifest'})
    return {'root_id':root_id,'expected_files':len(expected),'verified_files':checked,'verified_bytes':total,
            'errors':errors,'extra_files':extras,'all_verified':not errors and not extras,
            'seconds':time.monotonic()-start,'source_manifest_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest()}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--manifest',type=Path,required=True);p.add_argument('--root-id',required=True);p.add_argument('--target',type=Path,required=True);p.add_argument('--receipt',type=Path,required=True)
    a=p.parse_args();r=verify(a.manifest,a.root_id,a.target);a.receipt.write_text(json.dumps(r,indent=2));print(json.dumps({**{k:v for k,v in r.items() if k not in {'errors','extra_files'}},'error_count':len(r['errors']),'extra_file_count':len(r['extra_files'])}));return 0 if r['all_verified'] else 1


if __name__=='__main__':raise SystemExit(main())
