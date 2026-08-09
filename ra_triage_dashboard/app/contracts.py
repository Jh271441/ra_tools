from __future__ import annotations

"""Stable request and file-processing limits shared across HTTP modules.

This module deliberately has no runtime singletons.  Importing a validation
contract must not initialise the database, scan media, or build model clients.
"""

import re


ISSUE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{3,128}$")

MAX_UPLOAD_BYTES = 64 * 1024 * 1024
MAX_REVIEW_ATTACHMENTS = 4
MAX_REVIEW_ATTACHMENT_BYTES = 8 * 1024 * 1024
MAX_REVIEW_ATTACHMENTS_TOTAL_BYTES = 24 * 1024 * 1024
MAX_REVIEW_MULTIPART_REQUEST_BYTES = 26 * 1024 * 1024
MAX_REVIEW_ATTACHMENT_PIXELS = 40_000_000
MAX_REVIEW_ATTACHMENT_STORAGE_BYTES = 20 * 1024 * 1024 * 1024
MIN_REVIEW_ATTACHMENT_DISK_FREE = 256 * 1024 * 1024
MAX_BATCH_JSON_REQUEST_BYTES = 256 * 1024
MAX_SOURCE_PREVIEW_ROWS = 200
MAX_SOURCE_PREVIEW_CELL_LENGTH = 2_000

# Uploaded XLSX/XLSM files are ZIP containers.  The HTTP body limit alone does
# not protect openpyxl from a small archive expanding to several GiB.
MAX_SPREADSHEET_ARCHIVE_ENTRIES = 10_000
MAX_SPREADSHEET_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
MAX_SPREADSHEET_COMPRESSION_RATIO = 200
