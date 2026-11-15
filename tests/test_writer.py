# Copyright (C) 2026 I-Technology Inc.
# SPDX-License-Identifier: LGPL-3.0-only

import tempfile
import unittest
import uuid
from pathlib import Path
from archivist_writer import ArchiveWriter, UUIDConflict, ArchiveCorruption


def make_record(record_id=None, payload='example'):
    return ('100.00', 0, record_id or str(uuid.uuid4()),
            '00000000-0000-0000-0000-000000000000',
            '00000000-0000-0000-0000-000000000000', 'tester',
            '2026-11-04T00:00:00', 'app', '', False, '', '', '', '', '', '', payload)


class WriterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'Y.tsv'
        self.writer = ArchiveWriter(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_commit_duplicate_and_restart(self):
        r = make_record()
        self.assertEqual(self.writer.append(r), 'committed')
        self.assertEqual(self.writer.append(r), 'duplicate')
        restarted = ArchiveWriter(self.path)
        self.assertEqual(restarted.count, 1)
        self.assertEqual(restarted.append(r), 'duplicate')

    def test_conflicting_uuid(self):
        r = make_record()
        self.writer.append(r)
        with self.assertRaises(UUIDConflict):
            self.writer.append((*r[:-1], 'different'))

    def test_incomplete_last_record_detected(self):
        self.writer.append(make_record())
        with self.path.open('ab') as file:
            file.write(b'incomplete')
        with self.assertRaises(ArchiveCorruption):
            ArchiveWriter(self.path)

    def test_1000_records_and_rebuild(self):
        records = [make_record() for _ in range(1000)]
        for r in records:
            self.writer.append(r)
        self.assertEqual(self.writer.count, 1000)
        restarted = ArchiveWriter(self.path)
        self.assertEqual(restarted.count, 1000)
        for r in records:
            self.assertEqual(restarted.append(r), 'duplicate')
        self.assertEqual(restarted.count, 1000)


if __name__ == '__main__':
    unittest.main()
