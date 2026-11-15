# Copyright (C) 2026 I-Technology Inc.
# SPDX-License-Identifier: LGPL-3.0-only


"""
EventzAPI Step 7D.7 — Adversarially hardened Librarian.

Local POSIX/Linux qualification prototype.

Trust inputs:
- Independently protected witness HMAC key
- Independently pinned expected witness head
- Immutable checkpoint contents once authenticated

Every read authenticates a checkpoint snapshot before
using its inventory entries.

The archive object is opened with O_NOFOLLOW and read
through the same file descriptor that was validated.
"""

import hashlib
import hmac
import json
import os
import re
import stat
from pathlib import Path

from archivist_writer import ArchiveWriter
from checkpoint_witness import (
    WitnessError,
    canonical,
    sha256,
)
from cloud_y import CloudY


class LibrarianIntegrityError(Exception):
    pass


HEX64 = re.compile(r"^[0-9a-f]{64}$")


class WitnessedLibrarian:

    def __init__(
        self,
        original_directory,
        repair_directory,
        checkpoint_file,
        witness,
        receipt_sequence,
        trusted_head,
    ):
        self.original_directory = Path(original_directory)
        self.repair_directory = Path(repair_directory)
        self.checkpoint_file = Path(checkpoint_file)

        self.witness = witness
        self.receipt_sequence = receipt_sequence
        self.trusted_head = trusted_head

        if (
            not isinstance(trusted_head, str)
            or not HEX64.fullmatch(trusted_head)
        ):
            raise ValueError("Invalid trusted head")

        if (
            not isinstance(receipt_sequence, int)
            or isinstance(receipt_sequence, bool)
            or receipt_sequence < 1
        ):
            raise ValueError("Invalid receipt sequence")

        original = self.original_directory.resolve()
        repair = self.repair_directory.resolve()

        if (
            original == repair
            or original in repair.parents
            or repair in original.parents
        ):
            raise ValueError(
                "Original Y and Repair Y must be separate"
            )

    def _inventory_records(self):
        """
        Authenticate exactly one checkpoint snapshot.

        No second read of the checkpoint occurs after
        authentication.
        """
        try:
            snapshot = self.witness.verified_checkpoint_bytes(
                self.checkpoint_file,
                self.receipt_sequence,
                self.trusted_head,
            )

            # Validate the internal inventory digest
            # using the same checkpoint snapshot.
            document = json.loads(snapshot)

            inventory_body = document["body"]
            claimed_digest = document["digest"]

            if (
                not isinstance(inventory_body, dict)
                or not isinstance(claimed_digest, str)
                or not hmac.compare_digest(
                    sha256(canonical(inventory_body)),
                    claimed_digest,
                )
            ):
                raise LibrarianIntegrityError(
                    "Invalid inventory checksum"
                )

            records = inventory_body["records"]

            if (
                not isinstance(records, dict)
                or type(inventory_body.get("count"))
                is not int
                or inventory_body["count"] != len(records)
            ):
                raise LibrarianIntegrityError(
                    "Invalid inventory structure"
                )

            return records

        except LibrarianIntegrityError:
            raise

        except (
            WitnessError,
            OSError,
            ValueError,
            KeyError,
            TypeError,
        ) as exc:
            raise LibrarianIntegrityError(
                "Checkpoint authentication failed"
            ) from exc

    @staticmethod
    def _read_verified_object(
        directory,
        uid,
        expected_digest,
    ):
        """
        Open an object without following its final
        symbolic-link component.

        Validate and read through the same descriptor.
        """
        path = directory / (
            expected_digest + ".tuple"
        )

        flags = os.O_RDONLY

        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        else:
            raise LibrarianIntegrityError(
                "O_NOFOLLOW is required"
            )

        if hasattr(os, "O_NONBLOCK"):
            flags |= os.O_NONBLOCK

        try:
            fd = os.open(str(path), flags)
        except OSError:
            return None

        try:
            with os.fdopen(fd, "rb") as stream:
                metadata = os.fstat(
                    stream.fileno()
                )

                if not stat.S_ISREG(
                    metadata.st_mode
                ):
                    return None

                data = stream.read()

            if (
                hashlib.sha256(data).hexdigest()
                != expected_digest
            ):
                return None

            values = CloudY._decode(data)
            values = ArchiveWriter._normalize(
                values
            )

            if values[2] != uid:
                return None

            if (
                hashlib.sha256(
                    ArchiveWriter._encode(values)
                ).hexdigest()
                != expected_digest
            ):
                return None

            return values

        except (
            OSError,
            ValueError,
            TypeError,
            IndexError,
        ):
            return None

    def read(self, uid):
        """
        Return a verified tuple, None for an unknown UUID,
        or raise if known information is unavailable
        or cannot be authenticated.
        """
        records = self._inventory_records()

        entry = records.get(uid)

        if entry is None:
            return None

        try:
            expected_digest = entry["digest"]
            filename = entry["filename"]

            if (
                not isinstance(expected_digest, str)
                or not HEX64.fullmatch(expected_digest)
                or filename
                != expected_digest + ".tuple"
            ):
                raise LibrarianIntegrityError(
                    "Invalid inventory entry"
                )

        except (KeyError, TypeError) as exc:
            raise LibrarianIntegrityError(
                "Malformed inventory entry"
            ) from exc

        original = self._read_verified_object(
            self.original_directory,
            uid,
            expected_digest,
        )

        if original is not None:
            return original

        repaired = self._read_verified_object(
            self.repair_directory,
            uid,
            expected_digest,
        )

        if repaired is not None:
            return repaired

        raise LibrarianIntegrityError(
            "No verified tuple available for UUID "
            + str(uid)
        )
