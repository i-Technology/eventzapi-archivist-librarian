
"""
EventzAPI Step 7D.3 tests.
Recovery canvass and append-only logical repair.
"""

import tempfile
import unittest
import uuid
from pathlib import Path

from archivist_writer import ArchiveWriter
from cloud_y import CloudY
from cloud_y_inventory import CloudYInventory
from cloud_y_recovery import (
    RecoveryCoordinator,
    record_digest,
)


def record(n):
    return (
        "T",
        "A",
        str(uuid.UUID(int=n + 1)),
        *(str(i) for i in range(13)),
        "payload-" + str(n),
    )


class CloudYRecoveryTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

        self.root = Path(self.tmp.name)
        self.original_path = self.root / "original_y"
        self.repair_path = self.root / "repair_y"
        self.checkpoint = (
            self.root / "checkpoints" / "inventory.json"
        )

        self.original = CloudY(self.original_path)

        # Simulated F cache.
        self.cache = {}

        for n in range(100):
            r = record(n)
            self.original.commit(r)
            self.cache[r[2]] = r

        self.inventory = CloudYInventory(
            self.original_path,
            self.checkpoint,
        )
        self.inventory.create_checkpoint()

    def delete(self, n):
        path = (
            self.original_path
            / (record_digest(record(n)) + ".tuple")
        )
        self.assertTrue(path.exists())
        path.unlink()

    def coordinator(self, sources=None):
        if sources is None:
            sources = [self.cache]

        return RecoveryCoordinator(
            self.original_path,
            self.checkpoint,
            self.repair_path,
            sources,
        )

    def test_recover_one_missing_tuple(self):
        self.delete(42)

        recovery = self.coordinator()
        result = recovery.recover()

        self.assertTrue(result["logical_complete"])
        self.assertEqual(result["repair_count"], 1)
        self.assertEqual(
            result["recovered_uuids"],
            [record(42)[2]],
        )
        self.assertEqual(
            recovery.read(record(42)[2]),
            record(42),
        )

    def test_original_y_remains_damaged(self):
        self.delete(42)

        recovery = self.coordinator()
        recovery.recover()

        original_file = (
            self.original_path
            / (record_digest(record(42)) + ".tuple")
        )

        self.assertFalse(original_file.exists())
        self.assertTrue(recovery.verify_logical())

    def test_recover_three_missing_tuples(self):
        for n in (10, 20, 30):
            self.delete(n)

        recovery = self.coordinator()
        result = recovery.recover()

        self.assertTrue(result["logical_complete"])
        self.assertEqual(result["repair_count"], 3)

        for n in (10, 20, 30):
            self.assertEqual(
                recovery.read(record(n)[2]),
                record(n),
            )

    def test_reject_incorrect_cached_tuple(self):
        self.delete(42)

        bad_cache = dict(self.cache)
        bad_cache[record(42)[2]] = (
            record(42)[:-1] + ("malicious",)
        )

        recovery = self.coordinator([bad_cache])
        result = recovery.recover()

        self.assertFalse(result["logical_complete"])
        self.assertEqual(result["repair_count"], 0)
        self.assertEqual(
            result["unavailable_uuids"],
            [record(42)[2]],
        )

    def test_canvass_second_source(self):
        self.delete(42)

        bad_cache = dict(self.cache)
        bad_cache[record(42)[2]] = (
            record(42)[:-1] + ("incorrect",)
        )

        good_cache = {record(42)[2]: record(42)}

        recovery = self.coordinator(
            [bad_cache, good_cache]
        )

        result = recovery.recover()

        self.assertTrue(result["logical_complete"])
        self.assertEqual(result["repair_count"], 1)

    def test_recovery_survives_restart(self):
        self.delete(42)

        first = self.coordinator()
        first.recover()

        # Simulate restarting the recovery process.
        second = self.coordinator(sources=[])

        self.assertTrue(second.verify_logical())
        self.assertEqual(
            second.read(record(42)[2]),
            record(42),
        )

        result = second.recover()

        self.assertTrue(result["logical_complete"])
        self.assertEqual(result["repair_count"], 1)

    def test_recover_from_another_y(self):
        surviving_path = self.root / "surviving_y"
        surviving = CloudY(surviving_path)

        surviving.commit(record(42))

        self.delete(42)

        recovery = self.coordinator([surviving])
        result = recovery.recover()

        self.assertTrue(result["logical_complete"])
        self.assertEqual(
            recovery.read(record(42)[2]),
            record(42),
        )


if __name__ == "__main__":
    unittest.main()
