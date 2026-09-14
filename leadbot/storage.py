"""
Where leads end up: a Google Sheet (or local CSV) organised into
separate tabs by lead quality, with automatic overflow handling.

SHEET ORGANISATION (Google Sheets):
  Each category gets its own tab (worksheet). Within each tab, once a
  worksheet reaches MAX_ROWS rows of data (not counting the header), a
  new overflow tab is created automatically: "With Website 2", etc.

  Tab layout:
  ┌─────────────────────┬──────────────────────────────────────────────┐
  │ Tab name            │ Which leads go here                          │
  ├─────────────────────┼──────────────────────────────────────────────┤
  │ With Website        │ lead.website is non-empty                    │
  │ No Website          │ lead.website is empty                        │
  │ With Website 2/3/…  │ overflow once With Website hits MAX_ROWS     │
  │ No Website 2/3/…    │ overflow once No Website hits MAX_ROWS       │
  └─────────────────────┴──────────────────────────────────────────────┘

  MAX_ROWS default: 1000 data rows per tab (configurable via
  "sheet_max_rows" in config.json).

  Deduplication is global: a lead already in ANY tab (across ALL overflow
  tabs for both categories) is never added again.

CSV fallback (no Google Sheets):
  Two files: leads_with_website.csv and leads_no_website.csv.
  No row-limit splitting (CSV files handle millions of rows fine).
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import List

from .models import Lead, LEAD_FIELDS

MAX_ROWS_DEFAULT = 1000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _category(lead: Lead) -> str:
    """Return the base tab/file name for this lead."""
    return "With Website" if lead.website.strip() else "No Website"


# ---------------------------------------------------------------------------
# CSV storage (fallback, no Google account needed)
# ---------------------------------------------------------------------------

class CSVStorage:
    """Two CSV files, one per category. Accumulates across runs."""

    def __init__(self, base_path: str = "leads"):
        self._paths = {
            "With Website": Path(f"{base_path}_with_website.csv"),
            "No Website":   Path(f"{base_path}_no_website.csv"),
        }

    def _load_keys(self, path: Path) -> set:
        if not path.exists():
            return set()
        with path.open(newline="", encoding="utf-8") as f:
            return {
                Lead(**{k: row.get(k, "") for k in LEAD_FIELDS}).dedup_key
                for row in csv.DictReader(f)
            }

    def load_existing_keys(self) -> set:
        keys: set = set()
        for path in self._paths.values():
            keys |= self._load_keys(path)
        return keys

    def append_new_leads(self, leads: List[Lead]) -> int:
        existing = self.load_existing_keys()
        added = 0
        buckets: dict[str, list] = {"With Website": [], "No Website": []}
        for lead in leads:
            if lead.dedup_key not in existing:
                buckets[_category(lead)].append(lead)
                existing.add(lead.dedup_key)
                added += 1

        for cat, bucket in buckets.items():
            if not bucket:
                continue
            path = self._paths[cat]
            write_header = not path.exists()
            with path.open("a", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=LEAD_FIELDS)
                if write_header:
                    w.writeheader()
                for lead in bucket:
                    w.writerow(lead.as_dict())

        return added


# ---------------------------------------------------------------------------
# Google Sheets storage
# ---------------------------------------------------------------------------

class GoogleSheetStorage:
    """
    Organised Google Sheets storage.

    Tab naming:
      "With Website", "With Website 2", "With Website 3", …
      "No Website",   "No Website 2",   "No Website 3",   …

    A new overflow tab is created automatically the moment a tab would
    exceed max_rows data rows. The header row is NOT counted toward max_rows.

    Dedup is global: we scan every existing tab before deciding what's new.
    """

    # Base names for each category -- overflow tabs get a numeric suffix
    _BASE_NAMES = {
        "With Website": "With Website",
        "No Website":   "No Website",
    }

    def __init__(self, sheet_id: str, service_account_file: str, max_rows: int = MAX_ROWS_DEFAULT):
        import gspread
        self._max_rows = max(10, max_rows)
        creds = gspread.service_account(filename=service_account_file)
        self._book = creds.open_by_key(sheet_id)
        # Ensure at least the base tabs exist on first run
        for base in self._BASE_NAMES.values():
            self._get_or_create_worksheet(base)

    # ------------------------------------------------------------------
    # Worksheet management
    # ------------------------------------------------------------------

    def _existing_tab_names(self) -> list[str]:
        return [ws.title for ws in self._book.worksheets()]

    def _get_or_create_worksheet(self, title: str):
        """Return the worksheet with `title`, creating it with a header if needed."""
        import gspread
        try:
            return self._book.worksheet(title)
        except gspread.WorksheetNotFound:
            ws = self._book.add_worksheet(
                title=title,
                rows=self._max_rows + 50,   # a little headroom
                cols=len(LEAD_FIELDS) + 2,
            )
            ws.append_row(LEAD_FIELDS, value_input_option="RAW")
            return ws

    def _tabs_for_category(self, base: str) -> list:
        """
        Return all existing worksheets for a category, in order:
        ["With Website", "With Website 2", "With Website 3", ...]
        Creates the base tab if it doesn't exist yet.
        """
        existing = self._existing_tab_names()
        tabs = []
        # Base tab (no number suffix)
        if base in existing:
            tabs.append(self._book.worksheet(base))
        else:
            tabs.append(self._get_or_create_worksheet(base))
        # Numbered overflow tabs that already exist
        n = 2
        while True:
            name = f"{base} {n}"
            if name in existing:
                tabs.append(self._book.worksheet(name))
                n += 1
            else:
                break
        return tabs

    def _active_tab_for_category(self, base: str):
        """
        Return the worksheet that should receive new rows for `base`.
        If the last tab is full (>= max_rows data rows), create the next
        overflow tab and return that instead.
        """
        tabs = self._tabs_for_category(base)
        last = tabs[-1]
        # Row count includes the header row, so data rows = row_count - 1
        data_rows = max(0, last.row_count - 1)

        # Use a live count from the actual values to be accurate
        try:
            all_vals = last.get_all_values()
            # Subtract 1 for the header row (first row)
            data_rows = max(0, len(all_vals) - 1)
        except Exception:
            pass  # fall back to the estimate above

        if data_rows >= self._max_rows:
            n = len(tabs) + 1
            new_name = f"{base} {n}"
            print(f"  Sheet tab '{last.title}' reached {self._max_rows} rows -- "
                  f"creating overflow tab '{new_name}'")
            return self._get_or_create_worksheet(new_name)

        return last

    # ------------------------------------------------------------------
    # Deduplication: scan ALL tabs across ALL categories
    # ------------------------------------------------------------------

    def load_existing_keys(self) -> set:
        """
        Read every row from every tab (all categories, all overflow tabs)
        and return the set of dedup keys already stored.
        This guarantees a lead never appears twice, even across tabs.
        """
        keys: set = set()
        for base in self._BASE_NAMES.values():
            for ws in self._tabs_for_category(base):
                try:
                    records = ws.get_all_records()  # uses row 1 as headers
                except Exception:
                    continue
                for row in records:
                    try:
                        lead = Lead(**{k: str(row.get(k, "")) for k in LEAD_FIELDS})
                        keys.add(lead.dedup_key)
                    except Exception:
                        continue
        return keys

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------

    def append_new_leads(self, leads: List[Lead]) -> int:
        existing = self.load_existing_keys()
        added = 0

        # Split new leads into categories
        buckets: dict[str, list] = {"With Website": [], "No Website": []}
        for lead in leads:
            if lead.dedup_key not in existing:
                buckets[_category(lead)].append(lead)
                existing.add(lead.dedup_key)   # prevent within-batch dups
                added += 1

        for cat, bucket in buckets.items():
            if not bucket:
                continue
            base = self._BASE_NAMES[cat]
            # Write in chunks that respect the per-tab row limit
            remaining = list(bucket)
            while remaining:
                ws = self._active_tab_for_category(base)
                try:
                    all_vals = ws.get_all_values()
                    current_data_rows = max(0, len(all_vals) - 1)
                except Exception:
                    current_data_rows = 0

                slots = max(0, self._max_rows - current_data_rows)
                if slots == 0:
                    # Tab just became full mid-batch; loop will create overflow
                    continue

                chunk = remaining[:slots]
                remaining = remaining[slots:]

                rows = [
                    [lead.as_dict().get(field, "") for field in LEAD_FIELDS]
                    for lead in chunk
                ]
                ws.append_rows(rows, value_input_option="RAW")
                print(f"  +{len(chunk)} leads → '{ws.title}' "
                      f"(~{current_data_rows + len(chunk)}/{self._max_rows} rows)")

        return added


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_storage(config: dict):
    """Return Google Sheets storage if configured, else CSV fallback."""
    sheet_id    = config.get("google_sheet_id", "")
    sa_file     = config.get("google_service_account_file", "")
    max_rows    = int(config.get("sheet_max_rows", MAX_ROWS_DEFAULT))

    if sheet_id and sa_file:
        return GoogleSheetStorage(sheet_id, sa_file, max_rows=max_rows)

    print("Google Sheets not configured -- writing to local CSV files instead.")
    return CSVStorage(config.get("csv_out", "leads"))