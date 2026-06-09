#!/usr/bin/env python3
"""Summarize Q2 model master xlsx by version/source and daily precision."""

from __future__ import annotations

import argparse
import csv
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree as ET
from zipfile import ZipFile


XLSX_NS = {
    "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


@dataclass(frozen=True)
class SummaryConfig:
    sheet: str | None
    version_column: str
    group_column: str
    trigger_type_column: str
    result_column: str
    date_column: str
    positive_labels: set[str]
    negative_labels: set[str]
    manual_trigger_values: set[str]


def _column_index(cell_ref: str) -> int:
    match = re.match(r"([A-Z]+)", cell_ref or "")
    if not match:
        return 0
    index = 0
    for char in match.group(1):
        index = index * 26 + ord(char) - ord("A") + 1
    return index - 1


def _read_shared_strings(xlsx: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in xlsx.namelist():
        return []

    root = ET.fromstring(xlsx.read("xl/sharedStrings.xml"))
    strings: list[str] = []
    for item in root.findall("a:si", XLSX_NS):
        strings.append("".join(node.text or "" for node in item.findall(".//a:t", XLSX_NS)))
    return strings


def _sheet_paths(xlsx: ZipFile) -> dict[str, str]:
    workbook = ET.fromstring(xlsx.read("xl/workbook.xml"))
    rels = ET.fromstring(xlsx.read("xl/_rels/workbook.xml.rels"))
    rel_targets = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}

    paths: dict[str, str] = {}
    for sheet in workbook.findall("a:sheets/a:sheet", XLSX_NS):
        rel_id = sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
        target = rel_targets[rel_id].lstrip("/")
        paths[sheet.attrib["name"]] = target if target.startswith("xl/") else "xl/" + target
    return paths


def _read_cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    value_node = cell.find("a:v", XLSX_NS)

    if cell_type == "s" and value_node is not None:
        return shared_strings[int(value_node.text or "0")].strip()

    if cell_type == "inlineStr":
        inline = cell.find("a:is", XLSX_NS)
        if inline is None:
            return ""
        return "".join(node.text or "" for node in inline.findall(".//a:t", XLSX_NS)).strip()

    if value_node is None:
        return ""
    return (value_node.text or "").strip()


def read_xlsx_rows(path: Path, sheet_name: str | None = None) -> Iterable[list[str]]:
    """Read values from a single xlsx sheet using only the Python standard library."""
    with ZipFile(path) as xlsx:
        shared_strings = _read_shared_strings(xlsx)
        sheets = _sheet_paths(xlsx)
        if not sheets:
            raise ValueError("workbook has no sheets")

        if sheet_name is None:
            sheet_name = next(iter(sheets))
        if sheet_name not in sheets:
            available = ", ".join(sheets)
            raise ValueError(f"sheet {sheet_name!r} not found; available sheets: {available}")

        root = ET.fromstring(xlsx.read(sheets[sheet_name]))
        for row in root.findall("a:sheetData/a:row", XLSX_NS):
            values: list[str] = []
            for cell in row.findall("a:c", XLSX_NS):
                index = _column_index(cell.attrib.get("r", ""))
                while len(values) < index:
                    values.append("")
                values.append(_read_cell_value(cell, shared_strings))
            yield values


def parse_xlsx_date(value: str) -> str:
    """Return YYYY-MM-DD from common xlsx text/date serial formats."""
    value = (value or "").strip()
    if not value:
        return "(空)"

    match = re.search(r"\d{4}-\d{2}-\d{2}", value)
    if match:
        return match.group(0)

    try:
        serial = float(value)
    except ValueError:
        return value.split()[0]

    # Excel's 1900 date system includes the historical leap-year bug.
    base = datetime(1899, 12, 30)
    return (base + timedelta(days=serial)).strftime("%Y-%m-%d")


def _require_columns(header: list[str], names: Iterable[str]) -> dict[str, int]:
    positions = {name: index for index, name in enumerate(header)}
    missing = [name for name in names if name not in positions]
    if missing:
        raise ValueError(f"missing required columns: {', '.join(missing)}")
    return {name: positions[name] for name in names}


def _get(row: list[str], index: int, default: str = "") -> str:
    if index >= len(row):
        return default
    return row[index].strip() or default


def classify_sample(trigger_type: str, result: str, config: SummaryConfig) -> str:
    if trigger_type in config.manual_trigger_values:
        return "人工触发"
    if result in config.negative_labels:
        return result
    if result in config.positive_labels:
        return result
    return "未纳入"


def summarize(rows: list[list[str]], config: SummaryConfig) -> tuple[dict[tuple[str, str], Counter[str]], dict[str, Counter[str]]]:
    if not rows:
        raise ValueError("input sheet is empty")

    header = rows[0]
    column_indices = _require_columns(
        header,
        [
            config.version_column,
            config.group_column,
            config.trigger_type_column,
            config.result_column,
            config.date_column,
        ],
    )

    version_trigger_counts: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    daily_counts: dict[str, Counter[str]] = defaultdict(Counter)

    for row in rows[1:]:
        version = _get(row, column_indices[config.version_column], "(空)")
        group_value = _get(row, column_indices[config.group_column], "(空)")
        trigger_type = _get(row, column_indices[config.trigger_type_column])
        result = _get(row, column_indices[config.result_column])
        day = parse_xlsx_date(_get(row, column_indices[config.date_column]))
        sample_type = classify_sample(trigger_type, result, config)

        version_trigger_counts[(version, group_value)]["总数"] += 1
        version_trigger_counts[(version, group_value)][sample_type] += 1
        daily_counts[day]["total_rows"] += 1
        daily_counts[day][sample_type] += 1

    return version_trigger_counts, daily_counts


def version_trigger_rows(counts: dict[tuple[str, str], Counter[str]]) -> list[dict[str, str | int]]:
    categories = ["成功", "失败", "无需协助", "误触发", "人工触发", "未纳入"]
    rows: list[dict[str, str | int]] = []
    for (version, trigger), result_counts in sorted(counts.items(), key=lambda item: (item[0][0], item[0][1])):
        row: dict[str, str | int] = {"版本": version, "RA触发源": trigger, "总数": result_counts["总数"]}
        for category in categories:
            row[category] = result_counts[category]
        rows.append(row)
    return rows


def daily_metric_rows(counts: dict[str, Counter[str]]) -> list[dict[str, str | int | float]]:
    rows: list[dict[str, str | int | float]] = []
    for day in sorted(counts):
        valid_auto = counts[day]["成功"] + counts[day]["失败"] + counts[day]["无需协助"]
        false_trigger = counts[day]["误触发"]
        manual_trigger = counts[day]["人工触发"]
        precision_denominator = valid_auto + false_trigger
        recall_denominator = valid_auto + manual_trigger
        precision = valid_auto / precision_denominator if precision_denominator else 0.0
        recall = valid_auto / recall_denominator if recall_denominator else 0.0
        rows.append(
            {
                "日期": day,
                "成功": counts[day]["成功"],
                "失败": counts[day]["失败"],
                "无需协助": counts[day]["无需协助"],
                "误触发": false_trigger,
                "人工触发": manual_trigger,
                "准确率": round(precision, 4),
                "召回率": round(recall, 4),
                "未纳入": counts[day]["未纳入"],
                "总行数": counts[day]["total_rows"],
            }
        )
    return rows


def print_table(title: str, rows: list[dict[str, str | int | float]]) -> None:
    print(f"\n## {title}")
    if not rows:
        print("(no rows)")
        return

    headers = list(rows[0])
    print("| " + " | ".join(headers) + " |")
    print("| " + " | ".join("---" for _ in headers) + " |")
    for row in rows:
        print("| " + " | ".join(str(row[header]) for header in headers) + " |")


def write_csv(path: Path, rows: list[dict[str, str | int | float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return

    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "统计 Q2 model master 表：按 版本->RA触发源 计数，并按天计算准召率。"
            "默认按 RA触发源 分组；RA类型=人工触发 归为人工触发；其余按 ra结果 归为成功/失败/无需协助/误触发。"
        )
    )
    parser.add_argument("xlsx", type=Path, help="输入 xlsx 文件路径")
    parser.add_argument("--sheet", help="工作表名称；默认使用第一个工作表")
    parser.add_argument("--version-column", default="版本", help="版本列名")
    parser.add_argument("--group-column", default="RA触发源", help="版本统计的分组列名，默认使用 RA触发源")
    parser.add_argument("--trigger-type-column", default="RA类型", help="判断自触发/人工触发的列名，默认使用 RA类型")
    parser.add_argument("--result-column", default="ra结果", help="结果列名")
    parser.add_argument("--date-column", default="问题发生时间", help="日期列名")
    parser.add_argument("--positive-labels", default="成功,失败,无需协助", help="逗号分隔的有效自触发结果标签")
    parser.add_argument("--negative-labels", default="误触发", help="逗号分隔的误触发结果标签")
    parser.add_argument("--manual-trigger-values", default="人工触发", help="逗号分隔的人工触发 RA类型 值")
    parser.add_argument("--out-dir", type=Path, help="如提供则导出 CSV 到该目录")
    return parser.parse_args()


def split_labels(value: str) -> set[str]:
    return {item.strip() for item in value.split(",") if item.strip()}


def main() -> None:
    args = parse_args()
    config = SummaryConfig(
        sheet=args.sheet,
        version_column=args.version_column,
        group_column=args.group_column,
        trigger_type_column=args.trigger_type_column,
        result_column=args.result_column,
        date_column=args.date_column,
        positive_labels=split_labels(args.positive_labels),
        negative_labels=split_labels(args.negative_labels),
        manual_trigger_values=split_labels(args.manual_trigger_values),
    )

    rows = list(read_xlsx_rows(args.xlsx, config.sheet))
    version_counts, daily_counts = summarize(rows, config)
    by_version_trigger = version_trigger_rows(version_counts)
    daily_metrics = daily_metric_rows(daily_counts)

    print_table("版本 -> RA触发源统计", by_version_trigger)
    print_table("每日准召", daily_metrics)

    if args.out_dir:
        write_csv(args.out_dir / "version_trigger_counts.csv", by_version_trigger)
        write_csv(args.out_dir / "daily_precision.csv", daily_metrics)
        print(f"\nCSV 已导出到: {args.out_dir}")


if __name__ == "__main__":
    main()
