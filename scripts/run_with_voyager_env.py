#!/usr/bin/env python3
"""Execute a command with selected values from Voyager's VS Code env file.

The generated ``.vscode/voyager.env`` file is dotenv-like but is not safe to
``source`` as shell code (for example, ``LS_COLORS`` contains semicolons).
This launcher parses it as data and forwards only the paths needed by the
Orion Python client.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
from typing import Sequence


DEFAULT_ENV_FILE = Path("/home/didi/workspace/voyager/.vscode/voyager.env")
FORWARDED_KEYS = (
    "PATH",
    "PYTHONPATH",
    "LD_LIBRARY_PATH",
    "VOYAGER_ROOT",
    "VOY_LIB_DIR",
    "VOY_CONFIG_DIR",
    "VOY_DATA_DIR",
    "PLATFORM",
)
_KEY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def read_env_file(path: Path) -> dict[str, str]:
  values = {}
  for line_number, raw_line in enumerate(
      path.read_text(encoding="utf-8").splitlines(), start=1):
    line = raw_line.strip()
    if not line or line.startswith("#"):
      continue
    if line.startswith("export "):
      line = line[len("export "):].lstrip()
    if "=" not in line:
      raise ValueError(f"Invalid env line {line_number}: missing '='")
    key, value = line.split("=", 1)
    key = key.strip()
    if not _KEY_PATTERN.fullmatch(key):
      raise ValueError(f"Invalid env key on line {line_number}: {key!r}")
    values[key] = value
  return values


def build_environment(path: Path) -> dict[str, str]:
  source = read_env_file(path)
  missing = [key for key in FORWARDED_KEYS if key not in source]
  if missing:
    raise ValueError(f"Voyager env is missing required keys: {missing}")
  environment = dict(os.environ)
  environment.update({key: source[key] for key in FORWARDED_KEYS})
  return environment


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
  parser = argparse.ArgumentParser()
  parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
  parser.add_argument("command", nargs=argparse.REMAINDER)
  args = parser.parse_args(argv)
  if args.command and args.command[0] == "--":
    args.command = args.command[1:]
  if not args.command:
    parser.error("a command is required after --")
  return args


def main(argv: Sequence[str] | None = None) -> None:
  args = _parse_args(argv)
  environment = build_environment(args.env_file)
  os.execvpe(args.command[0], args.command, environment)


if __name__ == "__main__":
  main()
