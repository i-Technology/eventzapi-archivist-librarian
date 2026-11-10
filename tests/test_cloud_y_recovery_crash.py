
import os
import signal
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

from cloud_y import CloudY
from cloud_y_inventory import CloudYInventory
from cloud_y_recovery import (
    RecoveryCoordinator,
    RecoveryError,
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


# Executed in a separate Python interpreter.
# The recovery source is a simulated persistent F cache,
# reconstructed from deterministic test records.
CHILD_PROGRAM = r'''
import os
import signal
import sys
import uuid

from cloud_y import CloudY
from cloud_y_recovery import RecoveryCoordinator


def record(n):
    return (
        "T", "A", str(uuid.UUID(int=n + 1)),
        *(str(i) for i in range(13)),
        "payload-" + str(n),
    )


original, checkpoint, repair, mode, count = sys.argv[1:]
count = int(count)

cache = {
    record(n)[2]: record(n)
    for n in range(count)
}

original_commit = CloudY.commit
commits = 0


def intercepted_commit(self, value):
    global commits

    # Kill before the first repair is published.
    if mode == "before" and commits == 0:
        os.kill(os.getpid(), signal.SIGKILL)

    result = original_commit(self, value)
    commits += 1

    # Kill after a durable publication but before
    # RecoveryCoordinator receives the acknowledgment.
    if mode == "after" and commits == 1:
        os.kill(os.getpid(), signal.SIGKILL)

    # Kill after 50 of 100 repairs.
    if mode == "halfway" and commits == 50:
        os.kill(os.getpid(), signal.SIGKILL)

    return result


CloudY.commit = intercepted_commit

coordinator = RecoveryCoordinator(
    original,
    checkpoint,
    repair,
    [cache],
)

coordinator.recover()
'''


class CloudYRecoveryCrashTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

        self.root = Path(self.tmp.name)
        self.original_path = self.root / "original"
        self.repair_path = self.root / "repair"
        self.checkpoint = self.root / "inventory.json"

        self.original = CloudY(self.original_path)

    def prepare(self, count):
        self.cache = {}

        for n in range(count):
            value = record(n)
            self.original.commit(value)
            self.cache[value[2]] = value

        CloudYInventory(
            self.original_path,
            self.checkpoint,
        ).create_checkpoint()

        for n in range(count):
            path = (
                self.original_path
                / (record_digest(record(n)) + ".tuple")
            )
            path.unlink()

        # Snapshot the damaged original Y before recovery.
        self.original_snapshot = self.snapshot_original()

    def snapshot_original(self):
        return {
            p.name: p.read_bytes()
            for p in self.original_path.iterdir()
            if p.is_file()
        }

    def assert_original_unchanged(self):
        self.assertEqual(
            self.snapshot_original(),
            self.original_snapshot,
        )

    def coordinator(self, sources=None):
        if sources is None:
            sources = [self.cache]

        return RecoveryCoordinator(
            self.original_path,
            self.checkpoint,
            self.repair_path,
            sources,
        )

    def kill_recovery(self, mode, count):
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                CHILD_PROGRAM,
                str(self.original_path),
                str(self.checkpoint),
                str(self.repair_path),
                mode,
                str(count),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )

        self.assertEqual(
            result.returncode,
            -signal.SIGKILL,
            msg=(
                "Recovery process was not killed as expected.\n"
                + result.stderr
            ),
        )

    def test_70_kill_before_repair_publication(self):
        self.prepare(1)

        self.kill_recovery("before", 1)

        recovery = self.coordinator()
        result = recovery.recover()

        self.assertTrue(result["logical_complete"])
        self.assertEqual(result["repair_count"], 1)
        self.assertEqual(
            recovery.read(record(0)[2]),
            record(0),
        )
        self.assert_original_unchanged()

    def test_71_kill_after_publication_before_ack(self):
        self.prepare(1)

        self.kill_recovery("after", 1)

        # Restart with no available recovery sources.
        # The already committed repair must be sufficient.
        recovery = self.coordinator(sources=[])

        self.assertEqual(recovery.repair.count, 1)

        result = recovery.recover()

        self.assertTrue(result["logical_complete"])
        self.assertEqual(result["repair_count"], 1)
        self.assertEqual(
            recovery.read(record(0)[2]),
            record(0),
        )
        self.assert_original_unchanged()

    def test_72_kill_halfway_through_100_repairs(self):
        self.prepare(100)

        self.kill_recovery("halfway", 100)

        recovery = self.coordinator()

        self.assertEqual(recovery.repair.count, 50)

        result = recovery.recover()

        self.assertTrue(result["logical_complete"])
        self.assertEqual(result["repair_count"], 100)
        self.assertEqual(
            len(result["unavailable_uuids"]),
            0,
        )

        for n in range(100):
            self.assertEqual(
                recovery.read(record(n)[2]),
                record(n),
            )

        self.assert_original_unchanged()

    def test_73_recovery_source_disappears(self):
        self.prepare(1)

        # The source no longer holds the missing tuple.
        empty_cache = {}

        recovery = self.coordinator([empty_cache])
        result = recovery.recover()

        self.assertFalse(result["logical_complete"])
        self.assertEqual(result["repair_count"], 0)
        self.assertEqual(
            result["unavailable_uuids"],
            [record(0)[2]],
        )

        # Source returns later; recovery must succeed.
        restarted = self.coordinator()
        result = restarted.recover()

        self.assertTrue(result["logical_complete"])
        self.assertEqual(result["repair_count"], 1)
        self.assert_original_unchanged()

    def test_74_conflicting_repair_fails_closed(self):
        self.prepare(1)

        # Insert a tuple with the correct UUID but
        # incorrect contents into the separate Repair Y.
        bad = record(0)[:-1] + ("malicious-content",)

        repair = CloudY(self.repair_path)
        repair.commit(bad)

        recovery = self.coordinator()

        with self.assertRaises(RecoveryError):
            recovery.recover()

        # No correct tuple may be served from the
        # untrusted conflicting repair.
        self.assertIsNone(
            recovery.read(record(0)[2])
        )

        self.assertEqual(recovery.repair.count, 1)
        self.assert_original_unchanged()


if __name__ == "__main__":
    unittest.main()
