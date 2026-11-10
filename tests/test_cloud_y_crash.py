
import hashlib
import tempfile
import unittest
import uuid
from pathlib import Path

from archivist_writer import ArchiveWriter
from cloud_y import CloudY, CloudYError


def record(n):
    return (
        "T",
        "A",
        str(uuid.UUID(int=n + 1)),
        *(str(i) for i in range(13)),
        "payload-" + str(n)
    )


class SimulatedCrash(Exception):
    pass


def crash_at(target):
    def hook(point):
        if point == target:
            raise SimulatedCrash(point)
    return hook


class CloudYCrashTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "cloud_y"

    def test_crash_before_publish(self):
        y = CloudY(
            self.path,
            crash_hook=crash_at(
                "after_temp_fsync_before_publish"
            )
        )

        with self.assertRaises(SimulatedCrash):
            y.commit(record(0))

        recovered = CloudY(self.path)

        self.assertEqual(recovered.count, 0)
        self.assertEqual(recovered.read(record(0)[2]), None)

        self.assertEqual(
            recovered.commit(record(0)),
            "committed"
        )
        self.assertEqual(recovered.count, 1)

    def test_crash_after_publish_before_ack(self):
        y = CloudY(
            self.path,
            crash_hook=crash_at(
                "after_publish_before_ack"
            )
        )

        with self.assertRaises(SimulatedCrash):
            y.commit(record(0))

        recovered = CloudY(self.path)

        self.assertEqual(recovered.count, 1)
        self.assertEqual(
            recovered.commit(record(0)),
            "duplicate"
        )

    def test_abandoned_temporary_object(self):
        y = CloudY(self.path)

        abandoned = self.path / ".pending-interrupted"
        abandoned.write_bytes(b"incomplete-data")

        recovered = CloudY(self.path)

        self.assertEqual(recovered.count, 0)
        self.assertEqual(
            recovered.commit(record(0)),
            "committed"
        )
        self.assertEqual(recovered.verify(), 1)

    def test_tampered_object_detected(self):
        y = CloudY(self.path)
        y.commit(record(0))

        objects = list(self.path.glob("*.tuple"))
        self.assertEqual(len(objects), 1)

        # Simulate an attacker bypassing the Cloud Y interface.
        objects[0].write_bytes(b"tampered")

        with self.assertRaises(CloudYError):
            CloudY(self.path)

    def test_truncated_object_detected(self):
        y = CloudY(self.path)
        y.commit(record(0))

        path = next(self.path.glob("*.tuple"))
        data = path.read_bytes()

        path.write_bytes(data[:len(data) // 2])

        with self.assertRaises(CloudYError):
            CloudY(self.path)

    def test_missing_object_detection_limit(self):
        """
        Demonstrates a known limitation.

        Without an external manifest or expected object count,
        deleting a complete object cannot be detected by simply
        scanning the remaining directory.
        """
        y = CloudY(self.path)
        y.commit(record(0))
        y.commit(record(1))

        path = next(self.path.glob("*.tuple"))
        path.unlink()

        recovered = CloudY(self.path)

        self.assertEqual(recovered.count, 1)

    def test_1000_tuples_crash_safe_restart(self):
        y = CloudY(self.path)

        for n in range(1000):
            self.assertEqual(
                y.commit(record(n)),
                "committed"
            )

        recovered = CloudY(self.path)

        self.assertEqual(recovered.count, 1000)
        self.assertEqual(recovered.verify(), 1000)

        for n in range(1000):
            r = record(n)
            self.assertEqual(recovered.read(r[2]), r)

        # No temporary files should remain after normal commits.
        self.assertEqual(
            list(self.path.glob(".pending-*")),
            []
        )


if __name__ == "__main__":
    unittest.main()
