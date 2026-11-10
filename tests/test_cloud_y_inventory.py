
"""
EventzAPI Step 7D.2 tests.

UUID-aware inventory and recovery-request qualification
using actual CloudY commits.
"""

import hashlib
import tempfile
import unittest
import uuid
from pathlib import Path

from archivist_writer import ArchiveWriter
from cloud_y import CloudY
from cloud_y_inventory import (
    CloudYInventory,
    CloudYInventoryError,
)


def record(n):
    return (
        "T",
        "A",
        str(uuid.UUID(int=n + 1)),
        *(str(i) for i in range(13)),
        "payload-" + str(n),
    )


def record_digest(value):
    return hashlib.sha256(
        ArchiveWriter._encode(
            ArchiveWriter._normalize(value)
        )
    ).hexdigest()


class CloudYInventoryTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

        self.root = Path(self.tmp.name)
        self.y_path = self.root / "cloud_y"
        self.checkpoint = (
            self.root / "checkpoints" / "inventory.json"
        )

        self.y = CloudY(self.y_path)
        self.inventory = CloudYInventory(
            self.y_path,
            self.checkpoint,
        )

    def populate(self, count=100):
        for n in range(count):
            self.assertEqual(
                self.y.commit(record(n)),
                "committed",
            )

    def delete_record(self, n):
        object_name = record_digest(record(n)) + ".tuple"
        path = self.y_path / object_name
        self.assertTrue(path.exists())
        path.unlink()

    def test_100_real_tuples_complete(self):
        self.populate()
        self.inventory.create_checkpoint()

        result = self.inventory.verify()

        self.assertTrue(result["complete"])
        self.assertEqual(result["expected_count"], 100)
        self.assertEqual(result["verified_count"], 100)
        self.assertEqual(result["recovery_requests"], [])

    def test_missing_tuple_identified_by_uuid(self):
        self.populate()
        self.inventory.create_checkpoint()

        missing = record(42)
        self.delete_record(42)

        result = self.inventory.verify()

        self.assertFalse(result["complete"])
        self.assertEqual(
            result["missing_uuids"],
            [missing[2]],
        )

    def test_recovery_request_has_expected_digest(self):
        self.populate()
        self.inventory.create_checkpoint()

        missing = record(42)
        self.delete_record(42)

        result = self.inventory.verify()

        self.assertEqual(
            result["recovery_requests"],
            [{
                "uuid": missing[2],
                "expected_digest": record_digest(missing),
            }],
        )

    def test_publisher_cache_matches_recovery_request(self):
        # Simulated persistent publisher cache.
        # This is not yet the actual F cache implementation.
        publisher_cache = {
            record(n)[2]: record(n)
            for n in range(100)
        }

        self.populate()
        self.inventory.create_checkpoint()
        self.delete_record(42)

        result = self.inventory.verify()
        request = result["recovery_requests"][0]

        cached = publisher_cache[request["uuid"]]

        self.assertEqual(
            cached[2],
            request["uuid"],
        )
        self.assertEqual(
            record_digest(cached),
            request["expected_digest"],
        )

    def test_corruption_identifies_uuid(self):
        self.populate()
        self.inventory.create_checkpoint()

        object_name = record_digest(record(42)) + ".tuple"

        (self.y_path / object_name).write_bytes(
            b"corrupted object"
        )

        result = self.inventory.verify()

        self.assertFalse(result["complete"])
        self.assertEqual(
            result["corrupted_uuids"],
            [record(42)[2]],
        )

    def test_new_commit_after_checkpoint(self):
        self.populate(10)
        self.inventory.create_checkpoint()

        self.assertEqual(
            self.y.commit(record(10)),
            "committed",
        )

        result = self.inventory.verify()

        self.assertTrue(result["complete"])
        self.assertEqual(result["expected_count"], 10)
        self.assertEqual(result["verified_count"], 10)
        self.assertEqual(len(result["extra_objects"]), 1)

    def test_checkpoint_cannot_be_overwritten(self):
        self.populate(10)
        self.inventory.create_checkpoint()

        with self.assertRaises(CloudYInventoryError):
            self.inventory.create_checkpoint()

    def test_cloud_y_restart_detects_missing_object_limit(self):
        self.populate(10)
        self.inventory.create_checkpoint()
        self.delete_record(4)

        # Existing CloudY cannot independently know
        # that an entire object has disappeared.
        restarted = CloudY(self.y_path)
        self.assertEqual(restarted.count, 9)

        # The independent checkpoint exposes the loss.
        result = self.inventory.verify()

        self.assertEqual(
            result["missing_uuids"],
            [record(4)[2]],
        )


if __name__ == "__main__":
    unittest.main()
