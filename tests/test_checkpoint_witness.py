
"""
EventzAPI Step 7D.5 tests.

Six tests:
75 - Valid checkpoint attestation
76 - Checkpoint replacement rejected
77 - Receipt tampering rejected
78 - Missing intermediate receipt rejected
79 - Witness rollback detected by pinned head
80 - Successive checkpoints form a valid chain
"""

import json
import tempfile
import unittest
import uuid
from pathlib import Path

from cloud_y import CloudY
from cloud_y_inventory import CloudYInventory
from checkpoint_witness import (
    CheckpointWitness,
    WitnessError,
    canonical,
    sha256,
)


KEY = bytes(range(32))


def record(n):
    return (
        "T",
        "A",
        str(uuid.UUID(int=n + 1)),
        *(str(i) for i in range(13)),
        "payload-" + str(n),
    )


class CheckpointWitnessTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

        self.root = Path(self.tmp.name)
        self.y_path = self.root / "y"
        self.witness_path = self.root / "witness"
        self.checkpoint_path = self.root / "checkpoint.json"

        self.y = CloudY(self.y_path)

        for n in range(10):
            self.y.commit(record(n))

        CloudYInventory(
            self.y_path,
            self.checkpoint_path,
        ).create_checkpoint()

        self.witness = CheckpointWitness(
            self.witness_path,
            KEY,
        )

    def attest(self):
        return self.witness.attest(
            self.checkpoint_path
        )

    def test_75_valid_checkpoint_attestation(self):
        receipt = self.attest()

        self.assertEqual(receipt["sequence"], 1)

        self.assertTrue(
            self.witness.verify_checkpoint(
                self.checkpoint_path,
                1,
                receipt["head"],
            )
        )

    def test_76_checkpoint_replacement_rejected(self):
        receipt = self.attest()

        document = json.loads(
            self.checkpoint_path.read_bytes()
        )

        # Simulate an attacker rewriting the inventory
        # and recomputing its ordinary SHA-256 digest.
        records = document["body"]["records"]
        first_uid = next(iter(records))
        del records[first_uid]

        document["body"]["count"] = len(records)
        document["digest"] = sha256(
            canonical(document["body"])
        )

        self.checkpoint_path.write_bytes(
            canonical(document)
        )

        with self.assertRaises(WitnessError):
            self.witness.verify_checkpoint(
                self.checkpoint_path,
                1,
                receipt["head"],
            )

    def test_77_receipt_tampering_rejected(self):
        receipt = self.attest()

        path = self.witness_path / "000000000001.receipt"
        document = json.loads(path.read_bytes())

        document["body"]["checkpoint_sha256"] = "f" * 64
        path.write_bytes(canonical(document))

        with self.assertRaises(WitnessError):
            self.witness.verify_chain(
                expected_head=receipt["head"]
            )

    def test_78_missing_intermediate_receipt_rejected(self):
        self.attest()
        second = self.attest()
        self.attest()

        path = self.witness_path / "000000000002.receipt"
        path.unlink()

        with self.assertRaises(WitnessError):
            self.witness.verify_chain()

        self.assertEqual(second["sequence"], 2)

    def test_79_rollback_detected_by_pinned_head(self):
        self.attest()
        second = self.attest()

        # Attacker deletes the latest receipt.
        path = self.witness_path / "000000000002.receipt"
        path.unlink()

        # The remaining prefix is internally valid.
        self.assertEqual(
            self.witness.verify_chain()["count"],
            1,
        )

        # The independently retained head exposes
        # the rollback.
        with self.assertRaises(WitnessError):
            self.witness.verify_chain(
                expected_head=second["head"]
            )

    def test_80_successive_checkpoints_form_chain(self):
        first = self.attest()

        # Add a new tuple and make a NEW checkpoint.
        self.y.commit(record(100))

        second_checkpoint = (
            self.root / "checkpoint-2.json"
        )

        CloudYInventory(
            self.y_path,
            second_checkpoint,
        ).create_checkpoint()

        second = self.witness.attest(
            second_checkpoint
        )

        self.assertEqual(first["sequence"], 1)
        self.assertEqual(second["sequence"], 2)

        state = self.witness.verify_chain(
            expected_head=second["head"]
        )

        self.assertEqual(state["count"], 2)

        self.assertTrue(
            self.witness.verify_checkpoint(
                self.checkpoint_path,
                1,
                second["head"],
            )
        )

        self.assertTrue(
            self.witness.verify_checkpoint(
                second_checkpoint,
                2,
                second["head"],
            )
        )


if __name__ == "__main__":
    unittest.main()
