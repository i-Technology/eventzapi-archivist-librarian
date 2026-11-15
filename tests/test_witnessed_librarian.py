# Copyright (C) 2026 I-Technology Inc.
# SPDX-License-Identifier: LGPL-3.0-only


"""
EventzAPI Step 7D.6 qualification.

81 - Valid witnessed read
82 - Modified checkpoint rejected
83 - Witness rollback rejected
84 - Missing witness rejected
85 - Verified Repair Y read
86 - Corrupted repair rejected
"""

import json
import tempfile
import unittest
import uuid
from pathlib import Path

from checkpoint_witness import (
    CheckpointWitness,
    canonical,
    sha256,
)
from cloud_y import CloudY
from cloud_y_inventory import CloudYInventory
from cloud_y_recovery import record_digest
from witnessed_librarian import (
    WitnessedLibrarian,
    LibrarianIntegrityError,
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


class WitnessedLibrarianTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

        self.root = Path(self.tmp.name)
        self.original_path = self.root / "original"
        self.repair_path = self.root / "repair"
        self.checkpoint = self.root / "inventory.json"
        self.witness_path = self.root / "witness"

        self.original = CloudY(self.original_path)

        for n in range(10):
            self.original.commit(record(n))

        CloudYInventory(
            self.original_path,
            self.checkpoint,
        ).create_checkpoint()

        self.witness = CheckpointWitness(
            self.witness_path,
            KEY,
        )

        self.attestation = self.witness.attest(
            self.checkpoint
        )

    def librarian(self, head=None):
        if head is None:
            head = self.attestation["head"]

        return WitnessedLibrarian(
            self.original_path,
            self.repair_path,
            self.checkpoint,
            self.witness,
            self.attestation["sequence"],
            head,
        )

    def original_file(self, n):
        return (
            self.original_path
            / (record_digest(record(n)) + ".tuple")
        )

    def repair_file(self, n):
        return (
            self.repair_path
            / (record_digest(record(n)) + ".tuple")
        )

    def test_81_valid_witnessed_read(self):
        librarian = self.librarian()

        for n in range(10):
            self.assertEqual(
                librarian.read(record(n)[2]),
                record(n),
            )

        self.assertIsNone(
            librarian.read(str(uuid.uuid4()))
        )

    def test_82_modified_checkpoint_rejected(self):
        librarian = self.librarian()

        document = json.loads(
            self.checkpoint.read_bytes()
        )

        records = document["body"]["records"]
        uid = record(3)[2]

        del records[uid]
        document["body"]["count"] = len(records)

        # Attacker recalculates ordinary checksum.
        document["digest"] = sha256(
            canonical(document["body"])
        )

        self.checkpoint.write_bytes(
            canonical(document)
        )

        with self.assertRaises(
            LibrarianIntegrityError
        ):
            librarian.read(record(0)[2])

    def test_83_witness_rollback_rejected(self):
        # Establish a second receipt and pin its head.
        second = self.witness.attest(
            self.checkpoint
        )

        librarian = WitnessedLibrarian(
            self.original_path,
            self.repair_path,
            self.checkpoint,
            self.witness,
            second["sequence"],
            second["head"],
        )

        # Remove the latest receipt.
        latest = (
            self.witness_path
            / "000000000002.receipt"
        )
        latest.unlink()

        with self.assertRaises(
            LibrarianIntegrityError
        ):
            librarian.read(record(0)[2])

    def test_84_missing_witness_rejected(self):
        librarian = self.librarian()

        receipt = (
            self.witness_path
            / "000000000001.receipt"
        )
        receipt.unlink()

        with self.assertRaises(
            LibrarianIntegrityError
        ):
            librarian.read(record(0)[2])

    def test_85_verified_repair_y_read(self):
        uid = record(4)[2]

        # The original tuple disappears.
        self.original_file(4).unlink()

        # An independent surviving cache supplies
        # the original tuple to Repair Y.
        repair = CloudY(self.repair_path)
        repair.commit(record(4))

        librarian = self.librarian()

        self.assertEqual(
            librarian.read(uid),
            record(4),
        )

        # Recovery did not rewrite the original Y.
        self.assertFalse(
            self.original_file(4).exists()
        )

    def test_86_corrupted_repair_rejected(self):
        uid = record(4)[2]

        self.original_file(4).unlink()

        repair = CloudY(self.repair_path)
        repair.commit(record(4))

        # Corrupt the stored repair object after commit.
        self.repair_file(4).write_bytes(
            b"malicious replacement"
        )

        librarian = self.librarian()

        with self.assertRaises(
            LibrarianIntegrityError
        ):
            librarian.read(uid)

        self.assertFalse(
            self.original_file(4).exists()
        )


if __name__ == "__main__":
    unittest.main()
