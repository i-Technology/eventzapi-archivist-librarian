# Copyright (C) 2026 I-Technology Inc.
# SPDX-License-Identifier: LGPL-3.0-only


"""
EventzAPI Step 7D.3
Verified recovery into a separate append-only Repair Y.

Single-writer local qualification prototype.
No network canvass or real persistent F cache yet.
"""

import hashlib
from pathlib import Path

from archivist_writer import ArchiveWriter
from cloud_y import CloudY
from cloud_y_inventory import CloudYInventory


class RecoveryError(Exception):
    pass


def record_digest(record):
    values = ArchiveWriter._normalize(record)
    data = ArchiveWriter._encode(values)
    return hashlib.sha256(data).hexdigest()


class RecoveryCoordinator:
    def __init__(
        self,
        original_directory,
        checkpoint_file,
        repair_directory,
        sources,
    ):
        self.original_directory = Path(original_directory)
        self.repair_directory = Path(repair_directory)
        self.checkpoint_file = Path(checkpoint_file)

        original = self.original_directory.resolve()
        repair = self.repair_directory.resolve()

        if original == repair:
            raise RecoveryError(
                "Repair Y must be separate from original Y"
            )

        if original in repair.parents or repair in original.parents:
            raise RecoveryError(
                "Repair Y must not be nested in original Y"
            )

        self.inventory = CloudYInventory(
            original_directory,
            checkpoint_file,
        )
        self.repair = CloudY(repair_directory)
        self.sources = sources

    def _candidate(self, source, uid):
        """
        Sources may be dictionaries representing F caches,
        or CloudY instances representing surviving Ys.
        """
        if isinstance(source, dict):
            return source.get(uid)

        if isinstance(source, CloudY):
            return source.read(uid)

        raise RecoveryError(
            "Unsupported recovery source"
        )

    def _valid(self, candidate, uid, expected_digest):
        if candidate is None:
            return False

        try:
            values = ArchiveWriter._normalize(candidate)

            return (
                values[2] == uid
                and record_digest(values) == expected_digest
            )
        except (TypeError, ValueError, IndexError):
            return False

    def canvass(self, uid, expected_digest):
        """
        Search sources in order.
        Reject incorrect candidates.
        Return the first verified original tuple.
        """
        for source in self.sources:
            candidate = self._candidate(source, uid)

            if self._valid(
                candidate, uid, expected_digest
            ):
                return ArchiveWriter._normalize(candidate)

        return None

    def recover(self):
        """
        Recover missing or corrupted checkpointed tuples.

        Existing original objects are never modified.
        Verified recovered tuples are committed to Repair Y.
        """
        report = self.inventory.verify()

        recovered = []
        unavailable = []

        for request in report["recovery_requests"]:
            uid = request["uuid"]
            expected_digest = request["expected_digest"]

            # A prior repair may already exist.
            previous = self.repair.read(uid)

            if previous is not None:
                if not self._valid(
                    previous, uid, expected_digest
                ):
                    raise RecoveryError(
                        f"Invalid existing repair: {uid}"
                    )

                recovered.append(uid)
                continue

            candidate = self.canvass(
                uid, expected_digest
            )

            if candidate is None:
                unavailable.append(uid)
                continue

            result = self.repair.commit(candidate)

            if result not in ("committed", "duplicate"):
                raise RecoveryError(
                    f"Unexpected repair result: {result}"
                )

            recovered.append(uid)

        return {
            "recovered_uuids": sorted(recovered),
            "unavailable_uuids": sorted(unavailable),
            "repair_count": self.repair.count,
            "logical_complete": self.verify_logical(),
        }

    def verify_logical(self):
        """
        Check whether every checkpointed tuple is available
        either intact in original Y or verified in Repair Y.

        Does not rewrite or repair original physical objects.
        """
        report = self.inventory.verify()

        if report["complete"]:
            return True

        for request in report["recovery_requests"]:
            uid = request["uuid"]
            expected_digest = request["expected_digest"]

            repaired = self.repair.read(uid)

            if not self._valid(
                repaired, uid, expected_digest
            ):
                return False

        return True

    def read(self, uid):
        """
        Logical read of a checkpointed tuple.

        Trust a surviving original only if its content
        matches the independently retained inventory.
        Otherwise consult the verified Repair Y.
        """
        checkpoint = self.inventory.checkpoint_file

        import json

        document = json.loads(checkpoint.read_bytes())
        body = document["body"]

        # Validate checkpoint before trusting its entries.
        from cloud_y_inventory import canonical, digest

        if digest(canonical(body)) != document["digest"]:
            raise RecoveryError("Checkpoint integrity failure")

        entry = body["records"].get(uid)

        if entry is None:
            return None

        expected_digest = entry["digest"]
        path = self.original_directory / entry["filename"]

        if path.is_file() and not path.is_symlink():
            data = path.read_bytes()

            if hashlib.sha256(data).hexdigest() == expected_digest:
                try:
                    values = CloudY._decode(data)
                    if values[2] == uid:
                        return values
                except Exception:
                    pass

        repaired = self.repair.read(uid)

        if self._valid(repaired, uid, expected_digest):
            return repaired

        return None
