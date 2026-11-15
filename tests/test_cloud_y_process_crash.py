# Copyright (C) 2026 I-Technology Inc.
# SPDX-License-Identifier: LGPL-3.0-only


"""
Step 7C: actual process termination qualification.

Linux/POSIX only. Uses SIGKILL and subprocesses.
"""

import os
import signal
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

from cloud_y import CloudY


def record(n):
    return (
        "T",
        "A",
        str(uuid.UUID(int=n + 1)),
        *(str(i) for i in range(13)),
        "payload-" + str(n)
    )


WORKER = r'''
import os
import signal
import sys
import uuid

from cloud_y import CloudY

directory = sys.argv[1]
crash_point = sys.argv[2]

record = (
    "T",
    "A",
    str(uuid.UUID(int=1)),
    *(str(i) for i in range(13)),
    "payload-0"
)

def hook(point):
    if point == crash_point:
        os.kill(os.getpid(), signal.SIGKILL)

y = CloudY(directory, crash_hook=hook)
y.commit(record)
'''


class CloudYProcessCrashTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

        self.path = Path(self.tmp.name) / "cloud_y"
        self.path.mkdir()

    def kill_worker_at(self, point):
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                WORKER,
                str(self.path),
                point
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
            env=os.environ.copy()
        )

        self.assertEqual(
            result.returncode,
            -signal.SIGKILL,
            msg=result.stderr
        )

    def test_real_kill_before_publication(self):
        self.kill_worker_at(
            "after_temp_fsync_before_publish"
        )

        recovered = CloudY(self.path)

        self.assertEqual(recovered.count, 0)

        self.assertEqual(
            recovered.commit(record(0)),
            "committed"
        )

        self.assertEqual(recovered.count, 1)

    def test_real_kill_after_publication(self):
        self.kill_worker_at(
            "after_publish_before_ack"
        )

        recovered = CloudY(self.path)

        self.assertEqual(recovered.count, 1)

        self.assertEqual(
            recovered.read(record(0)[2]),
            record(0)
        )

        self.assertEqual(
            recovered.commit(record(0)),
            "duplicate"
        )

    def test_real_kill_then_1000_tuple_recovery(self):
        self.kill_worker_at(
            "after_publish_before_ack"
        )

        recovered = CloudY(self.path)

        self.assertEqual(
            recovered.commit(record(0)),
            "duplicate"
        )

        for n in range(1, 1000):
            self.assertEqual(
                recovered.commit(record(n)),
                "committed"
            )

        restarted = CloudY(self.path)

        self.assertEqual(restarted.count, 1000)
        self.assertEqual(restarted.verify(), 1000)

        for n in range(1000):
            self.assertEqual(
                restarted.read(record(n)[2]),
                record(n)
            )

    def test_same_process_recovers_after_exception(self):
        class SimulatedFailure(Exception):
            pass

        triggered = False

        def hook(point):
            nonlocal triggered
            if (
                point == "after_publish_before_ack"
                and not triggered
            ):
                triggered = True
                raise SimulatedFailure()

        y = CloudY(self.path, crash_hook=hook)

        with self.assertRaises(SimulatedFailure):
            y.commit(record(0))

        # The writer must have reconciled its index.
        self.assertEqual(y.count, 1)

        self.assertEqual(
            y.commit(record(0)),
            "duplicate"
        )

        self.assertEqual(
            y.commit(record(1)),
            "committed"
        )

        self.assertEqual(y.count, 2)


if __name__ == "__main__":
    unittest.main()
