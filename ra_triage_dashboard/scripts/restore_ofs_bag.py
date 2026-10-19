#!/usr/bin/env python3
"""Restore one registered historical planning bag into bounded local scratch.

Explicit issue/trip/topic/request-window identity is required. Original payload
SHA-256, size and the ROSv2 connection/chunk index are checked before publication.
The indexed topics and message bounds must agree with the registered request.
"""
import argparse
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import tempfile

PREFIX = '/nfs/dataset-ofs-remote-assist-stuck/user/jasperchen/experiments/backups/'
ARCHIVES = {'cloud_reports_bags_20261013_localgzip_a2', 'cloud_reports_bags_20261013_gzip_a1'}


def inspect_index(path, row):
    """Read bounded ROSv2 index metadata without loading message chunks into RAM."""
    def fields(raw):
        result = {}; offset = 0
        while offset < len(raw):
            if len(raw) - offset < 4:
                raise ValueError('Truncated ROS field length')
            size = struct.unpack_from('<I', raw, offset)[0]; offset += 4
            if size > len(raw) - offset:
                raise ValueError('Truncated ROS field')
            key, sep, value = raw[offset:offset+size].partition(b'='); offset += size
            if not sep or key in result:
                raise ValueError('Invalid or duplicate ROS field')
            result[key] = value
        return result
    def stamp(raw):
        seconds, nanos = struct.unpack('<II', raw)
        if nanos >= 1000000000:
            raise ValueError('Invalid ROS timestamp')
        return seconds * 1000000000 + nanos
    size = path.stat().st_size
    with path.open('rb') as stream:
        if stream.read(13) != b'#ROSBAG V2.0\n':
            raise ValueError('Payload is not a ROS bag v2 file')
        def record():
            raw = stream.read(4)
            if len(raw) != 4:
                raise ValueError('Truncated ROS record')
            header_size = struct.unpack('<I', raw)[0]
            if header_size > 1024**2 or stream.tell() + header_size + 4 > size:
                raise ValueError('Invalid ROS header size')
            header = fields(stream.read(header_size))
            data_size = struct.unpack('<I', stream.read(4))[0]
            if data_size > 16*1024**2 or stream.tell() + data_size > size:
                raise ValueError('Invalid ROS index record size')
            return header, stream.read(data_size)
        header, _ = record()
        if header.get(b'op') != b'\x03':
            raise ValueError('Missing ROS bag header')
        position = struct.unpack('<Q', header[b'index_pos'])[0]
        if not stream.tell() <= position < size:
            raise ValueError('Missing ROS bag index')
        stream.seek(position)
        connections = {}; counts = {}; starts = []; ends = []
        while stream.tell() < size:
            header, data = record()
            if header.get(b'op') == b'\x07':
                cid = struct.unpack('<I', header[b'conn'])[0]
                meta = fields(data)
                connections[cid] = {'topic': header[b'topic'].decode(), 'type': meta[b'type'].decode()}
            elif header.get(b'op') == b'\x06':
                start = stamp(header[b'start_time']); end = stamp(header[b'end_time'])
                if start > end:
                    raise ValueError('Reversed ROS chunk timestamps')
                starts.append(start); ends.append(end)
                count = struct.unpack('<I', header[b'count'])[0]
                if len(data) != count * 8:
                    raise ValueError('Invalid ROS chunk counts')
                for offset in range(0, len(data), 8):
                    cid, n = struct.unpack_from('<II', data, offset)
                    counts[cid] = counts.get(cid, 0) + n
        if not connections or not starts or not sum(counts.values()) or set(counts) - set(connections):
            raise ValueError('Incomplete ROS connection/chunk index')
        if {c['topic'] for c in connections.values()} != {row['topic']}:
            raise ValueError('Actual ROS topics differ from registered request')
        if min(starts) < row['requested_start_ms'] * 1000000 or max(ends) > row['requested_end_ms'] * 1000000:
            raise ValueError('Actual ROS message bounds exceed requested window')
        return {'connections': [dict(c, messages=counts.get(cid, 0)) for cid,c in connections.items()],
                'actual_start_ms': min(starts)/1000000, 'actual_end_ms': max(ends)/1000000,
                'verification_basis': 'SHA-verified payload ROSv2 connection and chunk index'}


def select(rows, issue, trip, topic, start, end):
    matches = [r for r in rows if (r['issue_id'],r['trip_id'],r['topic'],r['requested_start_ms'],r['requested_end_ms']) == (issue,trip,topic,start,end)]
    if len(matches) != 1:
        raise ValueError('Request identity must match exactly one registered archive')
    return matches[0]


def archive_path(row, mount):
    raw = row['ofs_path']
    if not raw.startswith(PREFIX):
        raise ValueError('Unknown archive prefix')
    rel = Path(raw[len(PREFIX):])
    if rel.is_absolute() or '..' in rel.parts or not rel.parts or rel.parts[0] not in ARCHIVES:
        raise ValueError('Archive path is outside the approved backup roots')
    root = mount.resolve()
    path = (root / rel).resolve()
    if root not in path.parents or (root / rel.parts[0]).resolve() not in path.parents:
        raise ValueError('Archive symlink escapes mount')
    return path


def restore(row, mount, scratch, budget):
    if not re.fullmatch(r'[0-9a-f]{64}', row['original_sha256']):
        raise ValueError('Invalid original digest')
    source = archive_path(row, mount)
    if source.stat().st_size != row['compressed_bytes']:
        raise ValueError('Compressed size differs from archive registration')
    size = int(row['original_bytes'])
    if size <= 0 or size > budget:
        raise ValueError('Bag exceeds scratch budget')
    scratch.mkdir(parents=True, exist_ok=True)
    with (scratch / '.restore.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        target = scratch / (row['original_sha256'] + '.bag')
        if target.exists():
            raise FileExistsError('Refusing to overwrite an existing scratch payload')
        used = sum(p.lstat().st_size for p in scratch.rglob('*') if p.is_file())
        if used + size > budget or shutil.disk_usage(scratch).free < size + 1024**3:
            raise ValueError('Scratch capacity gate failed')
        fd, temp = tempfile.mkstemp(prefix='.bag-', suffix='.partial', dir=scratch)
        try:
            digest = hashlib.sha256(); written = 0
            with os.fdopen(fd, 'wb') as out, gzip.open(source, 'rb') as inp:
                for block in iter(lambda: inp.read(4 * 1024**2), b''):
                    written += len(block)
                    if written > size:
                        raise ValueError('Decompressed payload exceeds registered size')
                    digest.update(block); out.write(block)
                out.flush(); os.fsync(out.fileno())
            if written != size or digest.hexdigest() != row['original_sha256']:
                raise ValueError('Original payload SHA-256/size mismatch')
            metadata = inspect_index(Path(temp), row)
            os.replace(temp, target)
        finally:
            Path(temp).unlink(missing_ok=True)
    return {'issue_id':row['issue_id'],'path':str(target),'bytes':size,'sha256':row['original_sha256'],'actual_topic_window_verified':True, **metadata}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--index',required=True,type=Path)
    p.add_argument('--mount',required=True,type=Path)
    p.add_argument('--scratch',required=True,type=Path)
    p.add_argument('--budget-gib',type=int,default=40)
    p.add_argument('--issue',required=True);p.add_argument('--trip',required=True);p.add_argument('--topic',required=True)
    p.add_argument('--start-ms',required=True,type=int);p.add_argument('--end-ms',required=True,type=int)
    a=p.parse_args()
    if not os.path.ismount(a.mount):raise SystemExit('OFS mount is not present')
    # Mount identity is checked independently of the presence of old directories.
    entries=[line.split() for line in Path('/proc/mounts').read_text().splitlines()]
    if not any(r[0]=='orangefs:remote-assist-stuck-model' and r[1]==str(a.mount) and r[2]=='fuse.ofs' for r in entries):
        raise SystemExit('Unexpected OFS volume identity')
    row=select(json.loads(a.index.read_text())['rows'],a.issue,a.trip,a.topic,a.start_ms,a.end_ms)
    print(json.dumps(restore(row,a.mount,a.scratch,a.budget_gib*1024**3)))


if __name__=='__main__':main()
