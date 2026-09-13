"""
Where leads end up: a Google Sheet (or a local CSV if Sheets isn't set up
yet), accumulating across every run instead of being overwritten.

WHY THIS FILE EXISTS:
The old main.py opened its output file with mode "w" every single run --
each run replaced the previous one entirely. This file's whole job is to
fix that: read what's already there, work out which new leads aren't
already present (using Lead.dedup_key from models.py), and add ONLY the
new ones. Existing rows -- including anything a teammate has manually
edited, like an "outreach status" column -- are never touched or wiped.

Google Sheets setup (free, no credit card):
1. Go to console.cloud.google.com, create a project (free).
2. Enable the "Google Sheets API" and "Google Drive API" for it.
3. Create a Service Account, then a JSON key for it -- download the file.
4. Open your Google Sheet, click Share, and share it with the service
   account's email address (looks like ...@...iam.gserviceaccount.com)
   as an Editor.
5. Put the JSON key's path in .env as GOOGLE_SERVICE_ACCOUNT_FILE, and
   the sheet's ID (from its URL) as GOOGLE_SHEET_ID.
"""

from __future__ import annotations

import csv
from pathlib import Path

from .models import Lead, LEAD_FIELDS


class CSVStorage:
    """Fallback storage: a local CSV file, same accumulate-don't-overwrite behavior."""

    def __init__(self, path="leads.csv"):
        self.path = Path(path)

    def load_existing_keys(self) -> set:
        if not self.path.exists():
            return set()
        with self.path.open(newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        keys = set()
        for row in rows:
            lead = Lead(**{k: row.get(k, "") for k in LEAD_FIELDS})
            keys.add(lead.dedup_key)
        return keys

    def append_new_leads(self, leads: list[Lead]) -> int:
        existing_keys = self.load_existing_keys()
        new_leads = [l for l in leads if l.dedup_key not in existing_keys]
        if not new_leads:
            return 0

        write_header = not self.path.exists()
        with self.path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=LEAD_FIELDS)
            if write_header:
                writer.writeheader()
            for lead in new_leads:
                writer.writerow(lead.as_dict())
        return len(new_leads)


class GoogleSheetStorage:
    """
    Real storage for the 4-person shared use case. Requires `gspread` and
    `google-auth` (see requirements.txt) and the one-time setup described
    in this file's module docstring.
    """

    def __init__(self, sheet_id: str, service_account_file: str, worksheet_name: str = "Leads"):
        import gspread  # imported here so CSV-only users don't need the package installed

        credentials = gspread.service_account(filename=service_account_file)
        self._book = credentials.open_by_key(sheet_id)
        try:
            self._sheet = self._book.worksheet(worksheet_name)
        except gspread.WorksheetNotFound:
            self._sheet = self._book.add_worksheet(title=worksheet_name, rows=1000, cols=len(LEAD_FIELDS))
            self._sheet.append_row(LEAD_FIELDS)

    def load_existing_keys(self) -> set:
        rows = self._sheet.get_all_records()  # uses row 1 as headers
        keys = set()
        for row in rows:
            lead = Lead(**{k: str(row.get(k, "")) for k in LEAD_FIELDS})
            keys.add(lead.dedup_key)
        if not rows:
            # Sheet might be completely empty (no header yet).
            header = self._sheet.row_values(1)
            if not header:
                self._sheet.append_row(LEAD_FIELDS)
        return keys

    def append_new_leads(self, leads: list[Lead]) -> int:
        existing_keys = self.load_existing_keys()
        new_leads = [l for l in leads if l.dedup_key not in existing_keys]
        if not new_leads:
            return 0
        rows = [[lead.as_dict().get(field, "") for field in LEAD_FIELDS] for lead in new_leads]
        self._sheet.append_rows(rows, value_input_option="RAW")
        return len(new_leads)


def get_storage(config: dict):
    """Pick Google Sheets if configured, otherwise fall back to local CSV."""
    sheet_id = config.get("google_sheet_id")
    service_account_file = config.get("google_service_account_file")
    if sheet_id and service_account_file:
        return GoogleSheetStorage(sheet_id, service_account_file)
    print("Google Sheets not configured (google_sheet_id / google_service_account_file missing) "
          "-- writing to local leads.csv instead.")
    return CSVStorage(config.get("csv_out", "leads.csv"))
