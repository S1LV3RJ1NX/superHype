"""Spreadsheet draft import: template generation, parsing, and user matching.

The downloadable sample workbook is the contract: its header row defines the
columns (email, name, post, self_comment, comment_1..comment_5). Uploads are
accepted as .xlsx (first worksheet) or .csv, headers are matched after
normalization (case, whitespace, underscores), and unknown columns are ignored.
Rows match the roster by email first (exact, case-insensitive), then by a
unique case-insensitive name; anything ambiguous stays unmatched and falls
back to AI generation. Nothing here touches the campaign: the caller feeds the
matched drafts back through PlanRequest.manual_drafts.
"""

import csv
import io
import re
from dataclasses import dataclass, field

from openpyxl import Workbook, load_workbook
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.user_repo import user_repo
from app.schemas.draft_import import (
    DraftImportPreview,
    DraftRowMatch,
    DraftRowUnmatched,
)
from app.schemas.post import ManualDraft

MAX_UPLOAD_BYTES = 2 * 1024 * 1024
MAX_COMMENTS = 5

# Canonical template columns, in sheet order.
TEMPLATE_COLUMNS: tuple[str, ...] = (
    "email",
    "name",
    "post",
    "self_comment",
    *(f"comment_{i}" for i in range(1, MAX_COMMENTS + 1)),
)

_EXAMPLE_ROW: tuple[str, ...] = (
    "jane@example.com",
    "Jane Doe",
    "We just shipped X and here is why it matters to teams like yours...",
    "Link in the comments!",
    "Congrats on the launch, the migration story is the best part.",
    "This solves a real pain we had last quarter.",
    "",
    "",
    "",
)


class DraftSheetError(ValueError):
    """The uploaded file could not be used as a draft sheet (bad type, size,
    missing headers, unreadable content). The message is safe to show the user.
    """


@dataclass
class ParsedDraftRow:
    """One usable data row from the sheet, before roster matching."""

    row: int  # 1-based row number in the sheet, header included
    email: str | None
    name: str | None
    draft: ManualDraft
    warnings: list[str] = field(default_factory=list)


def build_template() -> bytes:
    """The sample .xlsx the user downloads, fills, and uploads back."""
    wb = Workbook()
    ws = wb.active
    ws.title = "drafts"
    ws.append(list(TEMPLATE_COLUMNS))
    ws.append(list(_EXAMPLE_ROW))
    widths = {"A": 28, "B": 20, "C": 60, "D": 40}
    for col in "EFGHI":
        widths[col] = 40
    for col, width in widths.items():
        ws.column_dimensions[col].width = width
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _norm_header(value: object) -> str:
    """Normalize a header cell for matching: lowercase, alphanumerics only.

    "Self Comment", "self_comment", and " SELF-COMMENT " all become
    "selfcomment"; "Comment 1" and "comment_1" both become "comment1".
    """
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


_CANONICAL_BY_NORM = {_norm_header(c): c for c in TEMPLATE_COLUMNS}

_URL_ONLY = re.compile(r"https?://\S+")


def _cell(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _rows_from_xlsx(data: bytes) -> list[list[str]]:
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:
        raise DraftSheetError("Could not read the .xlsx file.") from exc
    try:
        ws = wb.worksheets[0]
        return [[_cell(v) for v in row] for row in ws.iter_rows(values_only=True)]
    finally:
        wb.close()


def _rows_from_csv(data: bytes) -> list[list[str]]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DraftSheetError("The .csv file is not valid UTF-8.") from exc
    return [[c.strip() for c in row] for row in csv.reader(io.StringIO(text))]


def parse_sheet(data: bytes, filename: str) -> list[ParsedDraftRow]:
    """Parse an uploaded draft sheet (.xlsx or .csv) into per-person drafts.

    Raises DraftSheetError for anything the user needs to fix (wrong type, too
    big, missing headers). Rows with no email, name, or content are skipped.
    """
    if len(data) > MAX_UPLOAD_BYTES:
        raise DraftSheetError("File is too large; the limit is 2 MB.")
    lowered = (filename or "").lower()
    if lowered.endswith(".xlsx"):
        grid = _rows_from_xlsx(data)
    elif lowered.endswith(".csv"):
        grid = _rows_from_csv(data)
    else:
        raise DraftSheetError("Upload a .xlsx or .csv file.")

    if not grid:
        raise DraftSheetError("The file is empty.")

    # Map canonical column -> index from the header row; unknown columns are
    # simply ignored so an extra "notes" column does not break the upload.
    col_index: dict[str, int] = {}
    for idx, header in enumerate(grid[0]):
        canonical = _CANONICAL_BY_NORM.get(_norm_header(header))
        if canonical is not None and canonical not in col_index:
            col_index[canonical] = idx
    if "email" not in col_index and "name" not in col_index:
        raise DraftSheetError(
            "No usable header row found. Download the sample template and keep "
            "its column names (email, name, post, self_comment, comment_1...)."
        )

    def get(row: list[str], column: str) -> str:
        idx = col_index.get(column)
        if idx is None or idx >= len(row):
            return ""
        return row[idx]

    out: list[ParsedDraftRow] = []
    for row_number, row in enumerate(grid[1:], start=2):
        email = get(row, "email")
        name = get(row, "name")
        post_body = get(row, "post")
        self_comment = get(row, "self_comment")
        comments = [
            c for i in range(1, MAX_COMMENTS + 1) if (c := get(row, f"comment_{i}"))
        ]

        warnings: list[str] = []
        # A post cell that is only a link is a leftover tracker artifact, not a
        # draft; treat it as blank so AI writes the post.
        if post_body and _URL_ONLY.fullmatch(post_body):
            warnings.append("The post cell contains only a URL; it was ignored.")
            post_body = ""

        if not any([email, name, post_body, self_comment, comments]):
            continue  # fully blank row (spreadsheets love trailing ones)

        out.append(
            ParsedDraftRow(
                row=row_number,
                email=email or None,
                name=name or None,
                draft=ManualDraft(
                    post_body=post_body or None,
                    self_comment=self_comment or None,
                    comments=comments,
                ),
                warnings=warnings,
            )
        )
    return out


async def match_rows(
    db: AsyncSession, rows: list[ParsedDraftRow]
) -> DraftImportPreview:
    """Match parsed rows against the user roster.

    Email wins (exact, case-insensitive). A row without an email falls back to
    its name, which must match exactly one user (case-insensitive) to count.
    A user claimed by an earlier row cannot be claimed again.
    """
    users = await user_repo.list(db)
    by_email = {u.email.lower(): u for u in users if u.email}
    by_name: dict[str, list] = {}
    for u in users:
        if u.name:
            by_name.setdefault(u.name.strip().lower(), []).append(u)

    matched: list[DraftRowMatch] = []
    unmatched: list[DraftRowUnmatched] = []
    claimed: set = set()

    for r in rows:
        user = None
        matched_by = ""
        reason = ""
        if r.email:
            user = by_email.get(r.email.lower())
            matched_by = "email"
            if user is None:
                reason = f"No user with email {r.email}."
        elif r.name:
            candidates = by_name.get(r.name.strip().lower(), [])
            if len(candidates) == 1:
                user = candidates[0]
                matched_by = "name"
            elif not candidates:
                reason = f"No user named {r.name}."
            else:
                reason = f"More than one user is named {r.name}; add an email."
        else:
            reason = "The row has neither an email nor a name."

        if user is not None and user.id in claimed:
            user = None
            reason = "This person already appeared in an earlier row."

        if user is None:
            unmatched.append(
                DraftRowUnmatched(row=r.row, email=r.email, name=r.name, reason=reason)
            )
            continue

        claimed.add(user.id)
        matched.append(
            DraftRowMatch(
                row=r.row,
                email=r.email,
                name=r.name,
                user_id=user.id,
                user_name=user.name,
                user_email=user.email,
                matched_by=matched_by,
                draft=r.draft,
                warnings=r.warnings,
            )
        )

    return DraftImportPreview(matched=matched, unmatched=unmatched)
