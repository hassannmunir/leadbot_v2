import unittest

from leadbot.core.models import LEAD_FIELDS
from leadbot.storage.storage import GoogleSheetStorage


class FakeWorksheet:
    def __init__(self, headers):
        self.headers = list(headers)
        self.deleted = []
        self.updated = None

    def row_values(self, row_number):
        return list(self.headers)

    def delete_columns(self, index):
        self.deleted.append(index)
        del self.headers[index - 1]

    def update(self, cell, values, **kwargs):
        self.updated = (cell, values, kwargs)
        self.headers = list(values[0])


class StorageSchemaTests(unittest.TestCase):
    def test_duplicate_header_columns_are_removed(self):
        worksheet = FakeWorksheet(LEAD_FIELDS + ["name", "niche"])

        GoogleSheetStorage._normalize_headers(worksheet)

        self.assertEqual(worksheet.headers, LEAD_FIELDS)
        self.assertEqual(worksheet.deleted, [len(LEAD_FIELDS) + 2, len(LEAD_FIELDS) + 1])
        self.assertEqual(worksheet.updated[1], [LEAD_FIELDS])


if __name__ == "__main__":
    unittest.main()
