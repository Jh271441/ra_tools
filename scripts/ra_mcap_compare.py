#!/usr/bin/env python3
"""Stream and compare selected topics in two MCAP files."""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
from typing import Any, Sequence

from mcap.reader import make_reader


DEFAULT_TOPICS = (
    "topic:/planning/planning_debug",
    "topic:/planning/seed",
    "topic:/planning/assist_request",
    "topic:/planning/stuck_detection_recall_signal",
)


def summarize(path: Path, topics: Sequence[str]) -> dict[str, Any]:
  stats: dict[str, dict[str, Any]] = defaultdict(lambda: {
      "count": 0,
      "bytes": 0,
      "first_log_time_ns": None,
      "last_log_time_ns": None,
      "stream_sha256": hashlib.sha256(),
      "message_hashes": [],
      "schema_names": set(),
      "schema_encodings": set(),
      "message_encodings": set(),
  })
  with path.open("rb") as stream:
    reader = make_reader(stream)
    for schema, channel, message in reader.iter_messages(topics=list(topics)):
      item = stats[channel.topic]
      payload = bytes(message.data)
      item["count"] += 1
      item["bytes"] += len(payload)
      if item["first_log_time_ns"] is None:
        item["first_log_time_ns"] = int(message.log_time)
      item["last_log_time_ns"] = int(message.log_time)
      item["stream_sha256"].update(len(payload).to_bytes(8, "little"))
      item["stream_sha256"].update(payload)
      item["message_hashes"].append(hashlib.sha256(payload).hexdigest())
      if schema is not None:
        item["schema_names"].add(schema.name)
        item["schema_encodings"].add(schema.encoding)
      item["message_encodings"].add(channel.message_encoding)

  result = {}
  for topic in topics:
    item = stats[topic]
    result[topic] = {
        "count": item["count"],
        "bytes": item["bytes"],
        "first_log_time_ns": item["first_log_time_ns"],
        "last_log_time_ns": item["last_log_time_ns"],
        "stream_sha256": item["stream_sha256"].hexdigest(),
        "message_hashes": item["message_hashes"],
        "schema_names": sorted(item["schema_names"]),
        "schema_encodings": sorted(item["schema_encodings"]),
        "message_encodings": sorted(item["message_encodings"]),
    }
  return {
      "path": str(path),
      "size_bytes": path.stat().st_size,
      "topics": result,
  }


def compare(left: dict[str, Any], right: dict[str, Any],
            topics: Sequence[str]) -> dict[str, Any]:
  result = {}
  for topic in topics:
    lhs = left["topics"][topic]
    rhs = right["topics"][topic]
    lhs_hashes = lhs.pop("message_hashes")
    rhs_hashes = rhs.pop("message_hashes")
    first_difference = next(
        (index for index, pair in enumerate(zip(lhs_hashes, rhs_hashes))
         if pair[0] != pair[1]),
        None,
    )
    if first_difference is None and len(lhs_hashes) != len(rhs_hashes):
      first_difference = min(len(lhs_hashes), len(rhs_hashes))
    result[topic] = {
        "same_count": lhs["count"] == rhs["count"],
        "same_stream": lhs["stream_sha256"] == rhs["stream_sha256"],
        "first_different_message_index": first_difference,
        "left": lhs,
        "right": rhs,
    }
  return result


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
  parser = argparse.ArgumentParser()
  parser.add_argument("left", type=Path)
  parser.add_argument("right", type=Path)
  parser.add_argument("--topic", action="append", dest="topics")
  return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
  args = _parse_args(argv)
  topics = tuple(args.topics or DEFAULT_TOPICS)
  left = summarize(args.left, topics)
  right = summarize(args.right, topics)
  output = {
      "left_path": left["path"],
      "left_size_bytes": left["size_bytes"],
      "right_path": right["path"],
      "right_size_bytes": right["size_bytes"],
      "topics": compare(left, right, topics),
  }
  print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
  main()
