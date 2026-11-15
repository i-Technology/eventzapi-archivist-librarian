# Copyright (C) 2026 I-Technology Inc.
# SPDX-License-Identifier: LGPL-3.0-only


"""EventzAPI Step 7D.8: six witness snapshot qualification tests."""
import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from checkpoint_witness import CheckpointWitness, WitnessError, canonical, sha256
from cloud_y import CloudY
from cloud_y_inventory import CloudYInventory
from witnessed_librarian import WitnessedLibrarian, LibrarianIntegrityError

KEY = bytes(range(32))


def record(n):
    return ("T", "A", str(uuid.UUID(int=n + 1)),
            *(str(i) for i in range(13)), "payload-" + str(n))


class AtomicWitnessTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.original = self.root / "original"
        self.repair = self.root / "repair"
        self.checkpoint = self.root / "inventory.json"
        self.witness_dir = self.root / "witness"
        y = CloudY(self.original)
        for n in range(3):
            y.commit(record(n))
        CloudYInventory(self.original, self.checkpoint).create_checkpoint()
        self.witness = CheckpointWitness(self.witness_dir, KEY)
        self.att = self.witness.attest(self.checkpoint)

    def librarian(self, witness=None):
        return WitnessedLibrarian(
            self.original, self.repair, self.checkpoint,
            witness or self.witness, self.att["sequence"], self.att["head"]
        )

    def test_93_receipt_substitution_after_verification(self):
        # Replace the selected receipt after the verified snapshot is captured.
        # The current read must use the snapshot, never reopen the receipt.
        original = self.witness._verified_chain_snapshot
        swapped = [False]
        calls = [0]

        def substitute(*args, **kwargs):
            snapshot = original(*args, **kwargs)
            calls[0] += 1
            if calls[0] == 2:
                swapped[0] = True
                self.witness._path(1).write_bytes(b"forged receipt")
            return snapshot

        with patch.object(
            self.witness,
            "_verified_chain_snapshot",
            side_effect=substitute,
        ):
            self.assertEqual(
                self.librarian().read(record(0)[2]),
                record(0),
            )

        self.assertTrue(swapped[0])

        with self.assertRaises(LibrarianIntegrityError):
            self.librarian().read(record(0)[2])

    def test_94_receipt_deletion_rejected(self):
        self.witness._path(1).unlink()

        with self.assertRaises(LibrarianIntegrityError):
            self.librarian().read(record(0)[2])

    def test_95_interrupted_receipt_publication(self):
        # Simulates a crash after temporary fsync but before publication.
        # A .pending-* file must not count as an authenticated receipt.
        (self.witness_dir / ".pending-interrupted").write_bytes(
            b"incomplete"
        )

        self.assertEqual(
            self.librarian().read(record(0)[2]),
            record(0),
        )

        # A missing published receipt cannot be replaced by that temp file.
        self.witness._path(1).unlink()

        with self.assertRaises(LibrarianIntegrityError):
            self.librarian().read(record(0)[2])

    def test_96_restart_verifies_same_witness(self):
        restarted = CheckpointWitness(self.witness_dir, KEY)

        self.assertEqual(
            self.librarian(restarted).read(record(1)[2]),
            record(1),
        )

        self.assertEqual(
            restarted.verify_chain(self.att["head"])["head"],
            self.att["head"],
        )

    def test_97_invalid_receipt_sequence_rejected(self):
        for bad in (0, -1, True, "1", 2):
            with self.subTest(sequence=bad):
                with self.assertRaises(WitnessError):
                    self.witness.verified_checkpoint_bytes(
                        self.checkpoint,
                        bad,
                        self.att["head"],
                    )

    def test_98_changed_checkpoint_rejected(self):
        document = json.loads(self.checkpoint.read_bytes())

        document["body"]["records"].pop(record(2)[2])
        document["body"]["count"] = 2
        document["digest"] = sha256(
            canonical(document["body"])
        )

        self.checkpoint.write_bytes(canonical(document))

        with self.assertRaises(LibrarianIntegrityError):
            self.librarian().read(record(0)[2])


if __name__ == "__main__":
    unittest.main()
