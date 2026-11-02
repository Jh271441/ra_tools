"""One read-only window over acquired, unreduced Bags; externally supervised."""
import hashlib
import json
from pathlib import Path
import resource
import struct
import sys

from ra_triage_dashboard.app.planning_constraint_extract import extract_frame


def schema_sha(cls):
    from google.protobuf.descriptor_pb2 import FileDescriptorSet
    value, seen = FileDescriptorSet(), set()
    def visit(descriptor):
        if descriptor.name in seen:
            return
        seen.add(descriptor.name)
        for child in descriptor.dependencies:
            visit(child)
        descriptor.CopyToProto(value.file.add())
    visit(cls.DESCRIPTOR.file)
    return hashlib.sha256(value.SerializeToString()).hexdigest()


def scan(request):
    import voy_vbag
    import rospy
    from google.protobuf.message import DecodeError
    start, end = request['start_ms'], request['end_ms']
    if type(start) is not int or not 0 < end-start <= 8400:
        raise ValueError('invalid_planning_window')
    def stamp(ms):
        return rospy.Time(ms//1000, ms%1000*1000000)
    rows, schemas = [], {}
    for value in request['inputs']:
        path = Path(value)
        if path.is_symlink() or not path.is_file():
            raise ValueError('invalid_planning_input')
        with voy_vbag.Bag(str(path)) as bag:
            for _, raw, published in bag.read_messages(topics=['/planning/planning_debug'],
                    start_time=stamp(start), end_time=stamp(end), raw=True):
                _, data, _, _, cls = raw
                ns, data = published.to_nsec(), bytes(data)
                if not start*1000000 <= ns < end*1000000:
                    continue
                if cls not in schemas:
                    schemas[cls] = schema_sha(cls)
                row = dict(publish_ns=str(ns), raw_sha256=hashlib.sha256(data).hexdigest(),
                           raw_bytes=len(data), schema_sha256=schemas[cls])
                try:
                    if len(data) < 4 or struct.unpack('<I', data[:4])[0] != len(data)-4:
                        raise ValueError('invalid_message_length')
                    message = cls()
                    message.ParseFromString(data[4:])
                    if not message.IsInitialized():
                        raise ValueError('missing_required_fields')
                except MemoryError:
                    raise  # A resource limit is not proof of a malformed source.
                except (DecodeError, ValueError) as exc:
                    row.update(decode='failed', full_protobuf_decode=False, frame=None,
                               error_type=type(exc).__name__)
                else:
                    # Extractor/schema faults are worker failures, not malformed bytes.
                    row.update(decode='passed', full_protobuf_decode=True,
                               frame=extract_frame(message, ns//1000000))
                rows.append(row)
                if len(rows) > 1000:
                    raise ValueError('oversized_planning_window')
    return rows


def main():
    resource.setrlimit(resource.RLIMIT_FSIZE, (512*1024**2,)*2)
    resource.setrlimit(resource.RLIMIT_AS, (4*1024**3,)*2)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    request = json.loads(Path(sys.argv[1]).read_text())
    output = Path(request['output'])
    try:
        rows = scan(request)
    except Exception as exc:
        output.with_suffix('.error.json').write_text(json.dumps({'error_type': type(exc).__name__}))
        raise
    raw = json.dumps(rows, ensure_ascii=False).encode()
    if len(raw) > 2*1024**2:
        raise ValueError('oversized_planning_window')
    pending = output.with_suffix('.pending')
    pending.write_bytes(raw)
    pending.replace(output)


if __name__ == '__main__':
    main()
