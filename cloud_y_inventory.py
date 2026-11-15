# Copyright (C) 2026 I-Technology Inc.
# SPDX-License-Identifier: LGPL-3.0-only


"""
EventzAPI Step 7D.2
UUID-aware inventory for Cloud Y.

Single-writer qualification prototype.
Create checkpoints only while Cloud Y commits are paused.
"""

import hashlib
import json
import os
import tempfile
from pathlib import Path

from cloud_y import CloudY, CloudYError


class CloudYInventoryError(Exception):
    pass


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def digest(data):
    return hashlib.sha256(data).hexdigest()


class CloudYInventory:

    def __init__(self, y_directory, checkpoint_file):
        self.y_directory = Path(y_directory)
        self.checkpoint_file = Path(checkpoint_file)

        y_path = self.y_directory.resolve()
        checkpoint_path = self.checkpoint_file.resolve()

        if y_path == checkpoint_path or y_path in checkpoint_path.parents:
            raise CloudYInventoryError(
                "Checkpoint must be outside Y"
            )

    def _scan(self):
        records = {}

        if not self.y_directory.is_dir():
            raise CloudYInventoryError(
                "Y directory is unavailable"
            )

        for path in sorted(self.y_directory.iterdir()):
            if path.name.startswith(".pending-"):
                continue

            if not path.is_file() or path.is_symlink():
                raise CloudYInventoryError(
                    f"Unexpected archive entry: {path.name}"
                )

            if path.suffix != ".tuple":
                raise CloudYInventoryError(
                    f"Unexpected archive entry: {path.name}"
                )

            data = path.read_bytes()
            object_digest = digest(data)

            if path.name != object_digest + ".tuple":
                raise CloudYInventoryError(
                    f"Corrupted object: {path.name}"
                )

            try:
                values = CloudY._decode(data)
            except CloudYError as exc:
                raise CloudYInventoryError(
                    f"Invalid object: {path.name}"
                ) from exc

            uid = values[2]

            if uid in records:
                raise CloudYInventoryError(
                    f"Duplicate UUID: {uid}"
                )

            records[uid] = {
                "digest": object_digest,
                "filename": path.name,
            }

        return records

    def create_checkpoint(self):
        if self.checkpoint_file.exists():
            raise CloudYInventoryError(
                "Checkpoint already exists"
            )

        records = self._scan()

        body = {
            "format": "eventz-cloud-y-inventory-v1",
            "count": len(records),
            "records": records,
        }

        checkpoint = {
            "body": body,
            "digest": digest(canonical(body)),
        }

        self.checkpoint_file.parent.mkdir(
            parents=True, exist_ok=True
        )

        fd, temp_name = tempfile.mkstemp(
            prefix=".inventory-",
            dir=self.checkpoint_file.parent,
        )

        try:
            with os.fdopen(fd, "wb") as output:
                output.write(canonical(checkpoint))
                output.flush()
                os.fsync(output.fileno())

            os.link(temp_name, self.checkpoint_file)

            dir_fd = os.open(
                self.checkpoint_file.parent,
                os.O_RDONLY,
            )
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)

        finally:
            Path(temp_name).unlink(missing_ok=True)

        return checkpoint

    def verify(self):
        try:
            checkpoint = json.loads(
                self.checkpoint_file.read_bytes()
            )
            body = checkpoint["body"]

            if digest(canonical(body)) != checkpoint["digest"]:
                raise CloudYInventoryError(
                    "Checkpoint digest mismatch"
                )

            if body["format"] != "eventz-cloud-y-inventory-v1":
                raise CloudYInventoryError(
                    "Unsupported inventory format"
                )

            expected = body["records"]

            if body["count"] != len(expected):
                raise CloudYInventoryError(
                    "Inventory count mismatch"
                )

            if not isinstance(expected, dict):
                raise CloudYInventoryError(
                    "Invalid inventory records"
                )

        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise CloudYInventoryError(
                "Invalid or unavailable checkpoint"
            ) from exc

        # Inspect objects individually so that a damaged object
        # can be reported without aborting the entire verification.
        missing = []
        corrupted = []
        recovered = set()

        for uid, entry in expected.items():
            filename = entry["filename"]
            expected_digest = entry["digest"]

            if filename != expected_digest + ".tuple":
                raise CloudYInventoryError(
                    f"Invalid inventory entry: {uid}"
                )

            path = self.y_directory / filename

            if not path.exists():
                missing.append(uid)
                continue

            if not path.is_file() or path.is_symlink():
                corrupted.append(uid)
                continue

            data = path.read_bytes()

            if digest(data) != expected_digest:
                corrupted.append(uid)
                continue

            try:
                values = CloudY._decode(data)
            except CloudYError:
                corrupted.append(uid)
                continue

            if values[2] != uid:
                corrupted.append(uid)
                continue

            recovered.add(uid)

        extra = sorted(
            path.name
            for path in self.y_directory.glob("*.tuple")
            if path.name not in {
                entry["filename"]
                for entry in expected.values()
            }
        )

        return {
            "complete": not missing and not corrupted,
            "expected_count": len(expected),
            "verified_count": len(recovered),
            "missing_uuids": sorted(missing),
            "corrupted_uuids": sorted(corrupted),
            "extra_objects": extra,
            "recovery_requests": [
                {
                    "uuid": uid,
                    "expected_digest": expected[uid]["digest"],
                }
                for uid in sorted(missing + corrupted)
            ],
        }
