# Copyright (C) 2026 I-Technology Inc.
# SPDX-License-Identifier: LGPL-3.0-only

import tempfile
import unittest
import uuid
from pathlib import Path
from volume_archive import VolumeArchive, VolumeError
from archivist_writer import UUIDConflict, ArchiveCorruption


def tuple_record(key=None, suffix='data'):
    return tuple(['1', 'action', key or str(uuid.uuid4())] + ['meta'] * 13 + [suffix])


class VolumeTransitionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'Y'
        self.archive = VolumeArchive.initialize(self.path, ('Y1', 'Y2', 'Y3'))

    def test_initial_and_restart(self):
        r = tuple_record()
        self.assertEqual(self.archive.append(r), 'committed')
        reopened = VolumeArchive(self.path)
        self.assertEqual(reopened.active, 'Y1')
        self.assertEqual(reopened.count, 1)
        self.assertEqual(reopened.append(r), 'duplicate')

    def test_transition_retains_old_online(self):
        a, b = tuple_record(), tuple_record()
        self.archive.append(a)
        self.assertEqual(self.archive.activate_next(), 'Y2')
        self.archive.append(b)
        reopened = VolumeArchive(self.path)
        self.assertEqual(reopened.active, 'Y2')
        self.assertEqual(reopened.count, 2)
        self.assertEqual(reopened.append(a), 'duplicate')
        self.assertEqual(reopened.writers['Y1'].count, 1)
        self.assertEqual(reopened.writers['Y2'].count, 1)

    def test_crash_before_manifest_replace_keeps_old_active(self):
        def crash(point):
            if point == 'before_manifest_replace':
                raise RuntimeError('simulated crash')
        self.archive.crash_hook = crash
        with self.assertRaises(RuntimeError):
            self.archive.activate_next()
        reopened = VolumeArchive(self.path)
        self.assertEqual(reopened.active, 'Y1')
        self.assertEqual(reopened.append(tuple_record()), 'committed')

    def test_crash_after_manifest_replace_selects_new(self):
        def crash(point):
            if point == 'after_manifest_replace':
                raise RuntimeError('simulated crash')
        self.archive.crash_hook = crash
        with self.assertRaises(RuntimeError):
            self.archive.activate_next()
        reopened = VolumeArchive(self.path)
        self.assertEqual(reopened.active, 'Y2')
        self.assertEqual(reopened.append(tuple_record()), 'committed')

    def test_crash_after_commit_before_ack_redelivery(self):
        r = tuple_record()
        self.archive.activate_next()
        def crash(point):
            if point == 'after_archive_fsync_before_ack':
                raise RuntimeError('simulated crash')
        self.archive.crash_hook = crash
        with self.assertRaises(RuntimeError):
            self.archive.append(r)
        reopened = VolumeArchive(self.path)
        self.assertEqual(reopened.count, 1)
        self.assertEqual(reopened.append(r), 'duplicate')
        self.assertEqual(reopened.count, 1)

    def test_conflicting_uuid_across_volumes(self):
        r = tuple_record()
        self.archive.append(r)
        self.archive.activate_next()
        with self.assertRaises(UUIDConflict):
            self.archive.append(tuple_record(r[2], 'different'))

    def test_no_successor(self):
        self.archive.activate_next()
        self.archive.activate_next()
        with self.assertRaises(VolumeError):
            self.archive.activate_next()

    def test_tampered_manifest_fails_closed(self):
        (self.path / 'volumes.json').write_text('{invalid', encoding='utf-8')
        with self.assertRaises(VolumeError):
            VolumeArchive(self.path)

    def test_cross_volume_duplicate_detected_on_restart(self):
        r = tuple_record()
        self.archive.append(r)
        self.archive.activate_next()
        self.archive.writers['Y2'].append(r)  # simulate unauthorized corruption
        with self.assertRaises(ArchiveCorruption):
            VolumeArchive(self.path)

    def test_initialize_rejects_existing_directory(self):
        with self.assertRaises(VolumeError):
            VolumeArchive.initialize(self.path)


if __name__ == '__main__':
    unittest.main()
