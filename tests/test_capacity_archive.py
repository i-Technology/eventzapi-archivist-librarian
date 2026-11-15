# Copyright (C) 2026 I-Technology Inc.
# SPDX-License-Identifier: LGPL-3.0-only


import tempfile
import unittest
import uuid
from pathlib import Path

from archivist_writer import ArchiveWriter, UUIDConflict
from volume_archive import VolumeError
from volume_policy import Policy
from capacity_archive import CapacityArchive


def record(n):
    """Construct a valid Eventz tuple with a deterministic UUID."""
    return (
        'T',
        'A',
        str(uuid.UUID(int=n + 1)),
        *(str(i) for i in range(13)),
        'payload-' + str(n)
    )


def size(n):
    """Actual encoded byte length of a tuple in Y."""
    values = ArchiveWriter._normalize(record(n))
    return len(ArchiveWriter._encode(values))


def one_record_capacity():
    """
    Return a capacity that permits record 0 but not records 0 and 1
    together, under the 95% utilization policy.
    """
    first = size(0)
    second = size(1)

    # Smallest total capacity whose 95% allowance fits record 0.
    capacity = (first * 100 + 94) // 95

    # Verify the fixture's intended boundary conditions.
    usable = int(capacity * 0.95)

    assert usable >= first
    assert usable < first + second

    return capacity


class CapacityArchiveTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

        self.path = Path(self.tmp.name) / 'Y'
        self.policy = Policy(
            provision_at=0.80,
            seal_at=0.95
        )

    def make(self, capacities):
        return CapacityArchive.initialize(
            self.path,
            capacities,
            self.policy
        )

    def test_append_without_rollover(self):
        a = self.make({
            'Y1': 10000,
            'Y2': 10000
        })

        self.assertEqual(
            a.append(record(0)),
            'committed'
        )

        self.assertEqual(
            (a.active, a.count),
            ('Y1', 1)
        )

    def test_rollover_before_overflow(self):
        a = self.make({
            'Y1': one_record_capacity(),
            'Y2': 10000
        })

        self.assertEqual(
            a.append(record(0)),
            'committed'
        )

        self.assertEqual(a.active, 'Y1')

        self.assertEqual(
            a.append(record(1)),
            'committed'
        )

        self.assertEqual(
            (a.active, a.count),
            ('Y2', 2)
        )

        self.assertEqual(
            (self.path / 'Y1.tsv').stat().st_size,
            size(0)
        )

        self.assertEqual(
            (self.path / 'Y2.tsv').stat().st_size,
            size(1)
        )

    def test_duplicate_does_not_rollover(self):
        a = self.make({
            'Y1': one_record_capacity(),
            'Y2': 10000
        })

        self.assertEqual(
            a.append(record(0)),
            'committed'
        )

        self.assertEqual(a.active, 'Y1')

        self.assertEqual(
            a.append(record(0)),
            'duplicate'
        )

        self.assertEqual(a.active, 'Y1')
        self.assertEqual(a.count, 1)

        self.assertFalse(
            (self.path / 'Y2.tsv').exists()
        )

    def test_conflicting_uuid_does_not_rollover(self):
        a = self.make({
            'Y1': one_record_capacity(),
            'Y2': 10000
        })

        self.assertEqual(
            a.append(record(0)),
            'committed'
        )

        bad = record(0)[:-1] + ('changed',)

        with self.assertRaises(UUIDConflict):
            a.append(bad)

        self.assertEqual(a.active, 'Y1')
        self.assertEqual(a.count, 1)

        self.assertFalse(
            (self.path / 'Y2.tsv').exists()
        )

    def test_no_successor_fails_closed(self):
        a = self.make({
            'Y1': one_record_capacity()
        })

        self.assertEqual(
            a.append(record(0)),
            'committed'
        )

        with self.assertRaises(VolumeError):
            a.append(record(1))

        self.assertEqual(a.active, 'Y1')
        self.assertEqual(a.count, 1)

        self.assertEqual(
            (self.path / 'Y1.tsv').stat().st_size,
            size(0)
        )

    def test_successor_too_small_fails_before_switch(self):
        a = self.make({
            'Y1': one_record_capacity(),
            'Y2': 20
        })

        self.assertEqual(
            a.append(record(0)),
            'committed'
        )

        with self.assertRaises(VolumeError):
            a.append(record(1))

        self.assertEqual(a.active, 'Y1')
        self.assertEqual(a.count, 1)

        self.assertFalse(
            (self.path / 'Y2.tsv').exists()
        )

    def test_restart_and_cross_volume_dedup(self):
        capacities = {
            'Y1': one_record_capacity(),
            'Y2': 10000
        }

        a = self.make(capacities)

        self.assertEqual(
            a.append(record(0)),
            'committed'
        )

        self.assertEqual(
            a.append(record(1)),
            'committed'
        )

        self.assertEqual(a.active, 'Y2')

        # Reconstruct archive state from the persistent Y files.
        b = CapacityArchive(
            self.path,
            capacities,
            self.policy
        )

        self.assertEqual(
            (b.active, b.count),
            ('Y2', 2)
        )

        self.assertEqual(
            b.append(record(0)),
            'duplicate'
        )

        self.assertEqual(b.active, 'Y2')
        self.assertEqual(b.count, 2)

    def test_reserve_triggers_rollover(self):
        # Configure the reserve so Y1 can hold exactly one tuple.
        # Y2 has the same capacity and reserve.
        reserve = 1000 - size(0)

        a = CapacityArchive.initialize(
            self.path,
            {
                'Y1': 1000,
                'Y2': 1000
            },
            Policy(reserve_bytes=reserve)
        )

        self.assertEqual(
            a.append(record(0)),
            'committed'
        )

        self.assertEqual(a.active, 'Y1')

        # The next tuple cannot fit in Y1, so switch to Y2.
        self.assertEqual(
            a.append(record(1)),
            'committed'
        )

        self.assertEqual(a.active, 'Y2')
        self.assertEqual(a.count, 2)

        # Neither volume can accommodate another tuple.
        with self.assertRaises(VolumeError):
            a.append(record(2))

        self.assertEqual(a.active, 'Y2')
        self.assertEqual(a.count, 2)

        self.assertEqual(
            (self.path / 'Y1.tsv').stat().st_size,
            size(0)
        )

        self.assertEqual(
            (self.path / 'Y2.tsv').stat().st_size,
            size(1)
        )


if __name__ == '__main__':
    unittest.main()
