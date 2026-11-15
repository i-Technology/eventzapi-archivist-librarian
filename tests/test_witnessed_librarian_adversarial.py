# Copyright (C) 2026 I-Technology Inc.
# SPDX-License-Identifier: LGPL-3.0-only


"""
EventzAPI Step 7D.7 adversarial tests.

87 - Forged receipt rejected
88 - Wrong UUID mapping rejected
89 - Symlink object rejected
90 - Checkpoint substitution after snapshot
91 - Unknown UUID returns None
92 - Corrupt original, valid repair succeeds
"""

import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

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
BAD_KEY = b"X" * 32


def record(n):
    return (
        "T",
        "A",
        str(uuid.UUID(int=n + 1)),
        *(str(i) for i in range(13)),
        "payload-" + str(n),
    )


class WitnessedLibrarianAdversarialTests(
    unittest.TestCase
):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

        self.root = Path(self.tmp.name)
        self.original_path = self.root / "original"
        self.repair_path = self.root / "repair"
        self.checkpoint = self.root / "inventory.json"
        self.witness_path = self.root / "witness"

        self.original = CloudY(
            self.original_path
        )

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

    def librarian(self):
        return WitnessedLibrarian(
            self.original_path,
            self.repair_path,
            self.checkpoint,
            self.witness,
            self.attestation["sequence"],
            self.attestation["head"],
        )

    def original_file(self, n):
        return self.original_path / (
            record_digest(record(n)) + ".tuple"
        )

    def repair_file(self, n):
        return self.repair_path / (
            record_digest(record(n)) + ".tuple"
        )

    def test_87_forged_receipt_rejected(self):
        receipt_path = (
            self.witness_path
            / "000000000001.receipt"
        )

        document = json.loads(
            receipt_path.read_bytes()
        )

        bad_witness = CheckpointWitness(
            self.root / "attacker",
            BAD_KEY,
        )

        # Forge a MAC using the wrong key.
        document["mac"] = bad_witness._mac(
            document["body"]
        )

        receipt_path.write_bytes(
            canonical(document)
        )

        with self.assertRaises(
            LibrarianIntegrityError
        ):
            self.librarian().read(
                record(0)[2]
            )

    def test_88_wrong_uuid_mapping_rejected(self):
        # Create a checkpoint with an internally valid
        # digest, but a UUID entry pointing to another
        # tuple's valid content digest.
        altered = self.root / "altered.json"

        document = json.loads(
            self.checkpoint.read_bytes()
        )

        uid0 = record(0)[2]
        uid1 = record(1)[2]

        document["body"]["records"][uid0] = dict(
            document["body"]["records"][uid1]
        )

        document["digest"] = sha256(
            canonical(document["body"])
        )

        altered.write_bytes(
            canonical(document)
        )

        # Simulate an authenticated but semantically
        # inconsistent checkpoint. This test is about
        # the Librarian's UUID/content verification.
        new_receipt = self.witness.attest(
            altered
        )

        librarian = WitnessedLibrarian(
            self.original_path,
            self.repair_path,
            altered,
            self.witness,
            new_receipt["sequence"],
            new_receipt["head"],
        )

        with self.assertRaises(
            LibrarianIntegrityError
        ):
            librarian.read(uid0)

    def test_89_symlink_object_rejected(self):
        path = self.original_file(3)

        # Preserve the genuine bytes elsewhere.
        saved = self.root / "saved-object"
        saved.write_bytes(path.read_bytes())

        path.unlink()
        path.symlink_to(saved)

        with self.assertRaises(
            LibrarianIntegrityError
        ):
            self.librarian().read(
                record(3)[2]
            )

    def test_90_checkpoint_swap_after_snapshot(self):
        librarian = self.librarian()

        original_verify = (
            self.witness.verify_chain
        )

        swapped = [False]

        def swap_after_snapshot(*args, **kwargs):
            if not swapped[0]:
                swapped[0] = True

                # The checkpoint is replaced after the
                # Librarian captured its bytes.
                self.checkpoint.write_bytes(
                    b"attacker replacement"
                )

            return original_verify(
                *args, **kwargs
            )

        with patch.object(
            self.witness,
            "verify_chain",
            side_effect=swap_after_snapshot,
        ):
            result = librarian.read(
                record(2)[2]
            )

        self.assertTrue(swapped[0])

        # The authenticated snapshot remains valid,
        # even though the on-disk checkpoint changed.
        self.assertEqual(
            result,
            record(2),
        )

        # A subsequent read must reject the replacement.
        with self.assertRaises(
            LibrarianIntegrityError
        ):
            librarian.read(record(2)[2])

    def test_91_unknown_uuid_returns_none(self):
        librarian = self.librarian()

        self.assertIsNone(
            librarian.read(
                str(uuid.uuid4())
            )
        )

    def test_92_corrupt_original_valid_repair(self):
        uid = record(5)[2]

        # Damage the original object.
        self.original_file(5).write_bytes(
            b"corrupted original"
        )

        # An independent source supplies a valid copy
        # into the separate Repair Y.
        repair = CloudY(self.repair_path)
        repair.commit(record(5))

        librarian = self.librarian()

        self.assertEqual(
            librarian.read(uid),
            record(5),
        )

        # The original remains damaged. The Librarian
        # has not silently modified Original Y.
        self.assertEqual(
            self.original_file(5).read_bytes(),
            b"corrupted original",
        )


if __name__ == "__main__":
    unittest.main()
