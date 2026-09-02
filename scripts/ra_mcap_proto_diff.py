#!/usr/bin/env python3
"""Decode and compare the first protobuf message on an MCAP topic."""

from __future__ import annotations

import argparse
from collections import Counter
import json
import struct
from typing import Any, Iterable, Iterator, Sequence

from google.protobuf import descriptor_pool, json_format, message_factory
from google.protobuf.descriptor_pb2 import DescriptorProto, FileDescriptorSet
from mcap.reader import make_reader


def _read_at(path: str, topic: str, index: int = 0):
  with open(path, "rb") as stream:
    for current_index, record in enumerate(
        make_reader(stream).iter_messages(topics=[topic])):
      if current_index == index:
        return record
  raise IndexError(f"Topic {topic!r} has no message at index {index}")


def _protobuf_payload(data: bytes) -> bytes:
  """Remove Voyager's uint32 little-endian frame length when present."""
  if len(data) >= 4 and struct.unpack("<I", data[:4])[0] == len(data) - 4:
    return data[4:]
  return data


def _message_names(
    package: str,
    messages: Iterable[DescriptorProto],
    parent: str = "",
) -> Iterator[str]:
  for message in messages:
    local_name = ".".join(part for part in (parent, message.name) if part)
    yield ".".join(part for part in (package, local_name) if part)
    yield from _message_names(package, message.nested_type, local_name)


def _build_message_class(schema):
  file_set = FileDescriptorSet()
  file_set.ParseFromString(schema.data)
  pool = descriptor_pool.DescriptorPool()
  pending = list(file_set.file)
  while pending:
    deferred = []
    for file_descriptor in pending:
      try:
        pool.AddSerializedFile(file_descriptor.SerializeToString())
      except Exception:  # Dependencies may appear later in the descriptor set.
        deferred.append(file_descriptor)
    if len(deferred) == len(pending):
      missing = ", ".join(item.name for item in deferred[:5])
      raise RuntimeError(f"Could not load protobuf descriptors: {missing}")
    pending = deferred

  leaf_name = schema.name.rsplit("/", 1)[-1].rsplit(".", 1)[-1]
  candidates = [
      name for file_descriptor in file_set.file
      for name in _message_names(file_descriptor.package,
                                 file_descriptor.message_type)
      if name.rsplit(".", 1)[-1] == leaf_name
  ]
  if len(candidates) != 1:
    raise RuntimeError(
        f"Expected one protobuf type named {leaf_name}, got {candidates}")
  descriptor = pool.FindMessageTypeByName(candidates[0])
  return candidates[0], message_factory.GetMessageClass(descriptor)


def _to_dict(message) -> dict[str, Any]:
  return json_format.MessageToDict(
      message,
      preserving_proto_field_name=True,
      always_print_fields_with_no_presence=False,
  )


def _short(value: Any, limit: int = 240) -> str:
  text = json.dumps(value, ensure_ascii=False, sort_keys=True)
  return text if len(text) <= limit else text[:limit] + "..."


def _diff(lhs: Any, rhs: Any, path: str = "$") -> Iterator[dict[str, Any]]:
  if isinstance(lhs, dict) and isinstance(rhs, dict):
    for key in sorted(set(lhs) | set(rhs)):
      child_path = f"{path}.{key}"
      if key not in lhs:
        yield {"path": child_path, "control": "<missing>", "feature": rhs[key]}
      elif key not in rhs:
        yield {"path": child_path, "control": lhs[key], "feature": "<missing>"}
      else:
        yield from _diff(lhs[key], rhs[key], child_path)
    return
  if isinstance(lhs, list) and isinstance(rhs, list):
    if len(lhs) != len(rhs):
      yield {
          "path": f"{path}.length",
          "control": len(lhs),
          "feature": len(rhs),
      }
    for index, (left_item, right_item) in enumerate(zip(lhs, rhs)):
      yield from _diff(left_item, right_item, f"{path}[{index}]")
    for index in range(len(rhs), len(lhs)):
      yield {
          "path": f"{path}[{index}]",
          "control": lhs[index],
          "feature": "<missing>",
      }
    for index in range(len(lhs), len(rhs)):
      yield {
          "path": f"{path}[{index}]",
          "control": "<missing>",
          "feature": rhs[index],
      }
    return
  if lhs != rhs:
    yield {"path": path, "control": lhs, "feature": rhs}


def _select_path(value: Any, selected_path: str | None) -> Any:
  for component in (selected_path or "").split("."):
    if component:
      value = value[component]
  return value


def compare(control_path: str, feature_path: str, topic: str,
            max_diffs: int, selected_path: str | None = None,
            message_index: int = 0) -> dict[str, Any]:
  control_schema, control_channel, control_record = _read_at(
      control_path, topic, message_index)
  feature_schema, feature_channel, feature_record = _read_at(
      feature_path, topic, message_index)
  if control_schema.data != feature_schema.data:
    raise RuntimeError("Control and feature protobuf schemas differ")
  type_name, message_class = _build_message_class(control_schema)
  control_message = message_class.FromString(
      _protobuf_payload(control_record.data))
  feature_message = message_class.FromString(
      _protobuf_payload(feature_record.data))
  control_dict = _select_path(_to_dict(control_message), selected_path)
  feature_dict = _select_path(_to_dict(feature_message), selected_path)
  differences = list(_diff(control_dict, feature_dict))
  differing_top_fields = Counter()
  for difference in differences:
    relative_path = difference["path"].removeprefix("$.")
    top_field = relative_path.split(".", 1)[0].split("[", 1)[0]
    differing_top_fields[top_field] += 1
  return {
      "topic": topic,
      "protobuf_type": type_name,
      "selected_path": selected_path,
      "message_index": message_index,
      "control": {
          "log_time": control_record.log_time,
          "payload_bytes": len(control_record.data),
      },
      "feature": {
          "log_time": feature_record.log_time,
          "payload_bytes": len(feature_record.data),
      },
      "different_field_count": len(differences),
      "different_top_fields": dict(differing_top_fields.most_common()),
      "differences": [{
          "path": difference["path"],
          "control": _short(difference["control"]),
          "feature": _short(difference["feature"]),
      } for difference in differences[:max_diffs]],
      "differences_truncated": len(differences) > max_diffs,
  }


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
  parser = argparse.ArgumentParser()
  parser.add_argument("control")
  parser.add_argument("feature")
  parser.add_argument("--topic", required=True)
  parser.add_argument("--max-diffs", type=int, default=100)
  parser.add_argument("--index", type=int, default=0)
  parser.add_argument(
      "--path",
      default=None,
      help="Optional dot-separated protobuf JSON subtree to compare.",
  )
  return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
  args = _parse_args(argv)
  print(json.dumps(
      compare(args.control, args.feature, args.topic, args.max_diffs,
              args.path, args.index),
      ensure_ascii=False,
      indent=2,
  ))


if __name__ == "__main__":
  main()
