"""Bounded multi-Issue filters and explicit XLSX TE targets."""
import hashlib
import io
import json
from pathlib import Path
import re

import openpyxl

from .import_parsing import _validate_spreadsheet_archive
from .model_labels import TRIAGE_LABELS

MAX_QUERY_IDS = 500
MAX_QUERY_CHARS = 8000
MAX_EXCEL_ROWS = 20000
ISSUE_RE = re.compile(r'cn[0-9]+')


def filter_issue_rows(rows, query):
    """Keep existing single-token search; pasted lists use exact set membership."""
    if len(query) > MAX_QUERY_CHARS:
        raise ValueError('Issue 查询过长 / Issue query is too long')
    tokens = [part for part in re.split(r'[\s,，、;；]+', query.strip()) if part]
    if len(tokens) <= 1:
        return [row for row in rows if query.strip().lower() in row['issue_id'].lower()]
    ids = set()
    for token in tokens:
        cleaned = token.strip('()[]{}<>\"\'').lower()
        match = re.search(r'(?:/issue/|[?&]issue=)(cn[0-9]+)(?:\b|$)', cleaned)
        iid = match[1] if match else cleaned
        if not ISSUE_RE.fullmatch(iid):
            raise ValueError('多 Issue 查询含无效 ID / Invalid ID in multi-Issue query')
        ids.add(iid)
    if len(ids) > MAX_QUERY_IDS:
        raise ValueError('最多查询 500 个 Issue / Query at most 500 Issues')
    return [row for row in rows if row['issue_id'] in ids]


def file_row_fingerprint(source, iid, label, row_number):
    return hashlib.sha256(json.dumps(['te-xlsx-v1', source['sha256'], source['sheet'],
        row_number, iid, label], ensure_ascii=False).encode()).hexdigest()


def _header(value):
    return re.sub(r'[\s_\-]+', '', str(value or '')).casefold()


def parse_te_xlsx(filename, content):
    if Path(filename).suffix.lower() != '.xlsx':
        raise ValueError('请上传 .xlsx 文件 / Upload an .xlsx file')
    try:
        _validate_spreadsheet_archive(content)
        book = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=False, keep_links=False)
    except Exception as exc:
        raise ValueError('无法读取 XLSX 文件 / Could not read XLSX workbook') from exc
    source = dict(kind='xlsx', filename=filename.replace('\\','/').rsplit('/',1)[-1][:160],
                  sha256=hashlib.sha256(content).hexdigest(), rows=0, duplicates=0)
    result, errors = {}, []
    try:
        sheet = book.active
        source['sheet'] = sheet.title
        if sheet.max_row and sheet.max_row > MAX_EXCEL_ROWS+1:
            raise ValueError('Excel 最多 20000 行 / Workbook supports at most 20000 data rows')
        if sheet.max_column and sheet.max_column > 256:
            raise ValueError('Excel 最多支持 256 列 / Workbook supports at most 256 columns')
        values = sheet.iter_rows(max_row=MAX_EXCEL_ROWS+2)
        header = next(values, ())
        id_columns = [i for i, cell in enumerate(header) if _header(cell.value) in {'issueid','issue','问题id','问题编号'}]
        label_columns = [i for i, cell in enumerate(header) if _header(cell.value) in {'期望输出','expectedoutput','目标标签','修正结果','label','rareviewresultnew'}]
        if len(id_columns) != 1 or len(label_columns) != 1:
            raise ValueError('需要唯一的 Issue ID、期望输出列 / Exactly one Issue ID and expected_output column required')
        i_col, l_col = id_columns[0], label_columns[0]
        for number, cells in enumerate(values, 2):
            if not any(cell.value is not None and str(cell.value).strip() for cell in cells):
                continue
            if number > MAX_EXCEL_ROWS+1:
                raise ValueError('Excel 最多 20000 行 / Workbook supports at most 20000 data rows')
            source['rows'] += 1
            iid_cell, label_cell = cells[i_col], cells[l_col]
            iid = str(iid_cell.value or '').strip().lower()
            label = str(label_cell.value or '').strip()
            if label == '成功': label = '正确触发'
            if iid_cell.data_type == 'f' or label_cell.data_type == 'f':
                errors.append((number, '不可使用公式 / Formulas are not allowed'))
            elif not ISSUE_RE.fullmatch(iid):
                errors.append((number, 'Issue ID 无效 / Invalid Issue ID'))
            elif label not in TRIAGE_LABELS:
                errors.append((number, '期望输出须为正确触发、误触发或无需协助 / Invalid expected output'))
            elif iid in result:
                if result[iid]['label'] != label:
                    errors.append((number, '重复 Issue 的期望输出冲突 / Conflicting duplicate Issue'))
                else:
                    source['duplicates'] += 1
            else:
                result[iid] = dict(issue_id=iid, state='resolved', label=label, source_kind='xlsx',
                    source_row=number, authors=[], fingerprint=file_row_fingerprint(source, iid, label, number))
            if len(errors) >= 10: break
        if errors:
            raise ValueError('; '.join(f'第{number}行 / Row {number}: {reason}' for number, reason in errors))
        if not result:
            raise ValueError('Excel 没有有效数据 / Workbook has no data rows')
        return result, source
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError('XLSX 数据格式无效 / Invalid XLSX worksheet data') from exc
    finally:
        book.close()
