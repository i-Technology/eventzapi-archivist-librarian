# Copyright (C) 2026 I-Technology Inc.
# SPDX-License-Identifier: LGPL-3.0-only


import hashlib
import json
import os
import tempfile
from pathlib import Path


class InventoryError(Exception):
    pass


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


class YInventory:
    """
    Step 7D.1: inventory of immutable Cloud Y objects.

    This version inventories .tuple objects by filename and
    content digest. It does not yet parse their UUIDs.

    The checkpoint must be stored separately from the
    objects it protects.
    """

    def __init__(self, y_directory, checkpoint_file):
        self.y_directory = Path(y_directory)
        self.checkpoint_file = Path(checkpoint_file)

        if (
            self.y_directory.resolve()
            == self.checkpoint_file.resolve()
            or self.y_directory.resolve()
            in self.checkpoint_file.resolve().parents
        ):
            raise InventoryError(
                "Checkpoint must be outside Y directory"
            )

    def _objects(self):
        result = {}

        for path in sorted(self.y_directory.glob("*.tuple")):
            if not path.is_file():
                continue

            data = path.read_bytes()
            result[path.name] = sha256(data)

        return result

    def create_checkpoint(self):
        """
        Capture the current complete object inventory.

        This is a controlled, single-writer prototype.
        Do not run concurrently with commits.
        """
        if self.checkpoint_file.exists():
            raise InventoryError(
                "Checkpoint already exists; refusing overwrite"
            )

        objects = self._objects()

        body = {
            "format": "eventz-y-inventory-v1",
            "count": len(objects),
            "objects": objects,
        }

        checkpoint = {
            "body": body,
            "digest": sha256(canonical(body)),
        }

        self.checkpoint_file.parent.mkdir(
            parents=True, exist_ok=True
        )

        fd, temp_name = tempfile.mkstemp(
            prefix=".inventory-",
            dir=str(self.checkpoint_file.parent),
        )

        try:
            with os.fdopen(fd, "wb") as output:
                output.write(canonical(checkpoint))
                output.flush()
                os.fsync(output.fileno())

            # Never replace an existing checkpoint.
            os.link(temp_name, self.checkpoint_file)

            dir_fd = os.open(
                str(self.checkpoint_file.parent),
                os.O_RDONLY,
            )
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)

        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

        return checkpoint

    def verify(self):
        """
        Compare current Y with the saved checkpoint.

        Returns missing, corrupted, and extra object names.
        """
        checkpoint = json.loads(
            self.checkpoint_file.read_bytes()
        )

        body = checkpoint["body"]
        expected_digest = checkpoint["digest"]

        if sha256(canonical(body)) != expected_digest:
            raise InventoryError(
                "Checkpoint digest mismatch"
            )

        if body["format"] != "eventz-y-inventory-v1":
            raise InventoryError(
                "Unsupported checkpoint format"
            )

        expected = body["objects"]

        if body["count"] != len(expected):
            raise InventoryError(
                "Checkpoint count mismatch"
            )

        actual = self._objects()

        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))

        corrupted = sorted(
            name
            for name in set(expected) & set(actual)
            if expected[name] != actual[name]
        )

        return {
            "complete": not (missing or corrupted),
            "expected_count": len(expected),
            "actual_count": len(actual),
            "missing": missing,
            "corrupted": corrupted,
            "extra": extra,
        }
