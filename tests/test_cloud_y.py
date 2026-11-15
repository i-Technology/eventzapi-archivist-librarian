# Copyright (C) 2026 I-Technology Inc.
# SPDX-License-Identifier: LGPL-3.0-only


import tempfile
import unittest
import uuid

from archivist_writer import UUIDConflict
from cloud_y import CloudY


def record(n):
    return (
        "T",
        "A",
        str(uuid.UUID(int=n + 1)),
        *(str(i) for i in range(13)),
        "payload-" + str(n)
    )


class CloudYTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = self.tmp.name

    def test_commit_and_read(self):
        y = CloudY(self.path)
        r = record(0)

        self.assertEqual(y.commit(r), "committed")
        self.assertEqual(y.read(r[2]), r)
        self.assertEqual(y.count, 1)

    def test_duplicate(self):
        y = CloudY(self.path)

        self.assertEqual(y.commit(record(0)), "committed")
        self.assertEqual(y.commit(record(0)), "duplicate")
        self.assertEqual(y.count, 1)

    def test_conflicting_uuid(self):
        y = CloudY(self.path)

        y.commit(record(0))

        changed = record(0)[:-1] + ("changed",)

        with self.assertRaises(UUIDConflict):
            y.commit(changed)

        self.assertEqual(y.count, 1)

    def test_1000_tuples_restart_and_verify(self):
        y = CloudY(self.path)

        for n in range(1000):
            self.assertEqual(
                y.commit(record(n)),
                "committed"
            )

        self.assertEqual(y.count, 1000)

        # Simulate restarting the Cloud Y process.
        recovered = CloudY(self.path)

        self.assertEqual(recovered.count, 1000)
        self.assertEqual(recovered.verify(), 1000)

        for n in range(1000):
            r = record(n)
            self.assertEqual(recovered.read(r[2]), r)


if __name__ == "__main__":
    unittest.main()
