# Copyright (C) 2026 I-Technology Inc.
# SPDX-License-Identifier: LGPL-3.0-only


"""
EventzAPI Step 7C — Crash-safe Cloud Y.

Single-writer, local-filesystem qualification prototype.
Not hardware-enforced or cloud-enforced WORM storage.
"""

import hashlib
import os
import tempfile
from pathlib import Path

from archivist_writer import ArchiveWriter, UUIDConflict


class CloudYError(Exception):
    pass


class CloudY:
    def __init__(self, directory, *, crash_hook=None):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.crash_hook = crash_hook
        self.records = {}
        self._healthy = False
        self._load()
        self._healthy = True

    def _crash(self, point):
        if self.crash_hook:
            self.crash_hook(point)

    def _fsync_directory(self):
        fd = os.open(
            self.directory,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        )
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    @staticmethod
    def _decode(data):
        try:
            text = data.decode("utf-8")
            if not text.endswith("\n"):
                raise ValueError("Missing terminator")

            values = tuple(text[:-1].split("\t"))
            values = ArchiveWriter._normalize(values)

            if ArchiveWriter._encode(values) != data:
                raise ValueError("Noncanonical encoding")

            return values
        except Exception as exc:
            raise CloudYError("Invalid tuple object") from exc

    def _load(self):
        recovered = {}

        for path in sorted(self.directory.iterdir()):
            if path.name.startswith(".pending-"):
                continue

            if not path.is_file() or path.is_symlink():
                raise CloudYError(
                    f"Unexpected archive entry: {path.name}"
                )

            if path.suffix != ".tuple":
                raise CloudYError(
                    f"Unexpected archive entry: {path.name}"
                )

            data = path.read_bytes()
            digest = hashlib.sha256(data).hexdigest()

            if path.name != digest + ".tuple":
                raise CloudYError(
                    f"Object integrity failure: {path.name}"
                )

            values = self._decode(data)
            uid = values[2]

            if uid in recovered:
                raise CloudYError(
                    f"Duplicate UUID in archive: {uid}"
                )

            recovered[uid] = values

        self.records = recovered

    def commit(self, record):
        if not self._healthy:
            raise CloudYError(
                "Writer requires recovery before further commits"
            )

        values = ArchiveWriter._normalize(record)
        uid = values[2]

        previous = self.records.get(uid)

        if previous is not None:
            if previous == values:
                return "duplicate"
            raise UUIDConflict(uid)

        data = ArchiveWriter._encode(values)
        digest = hashlib.sha256(data).hexdigest()
        destination = self.directory / (digest + ".tuple")

        fd, temp_name = tempfile.mkstemp(
            prefix=".pending-",
            dir=self.directory
        )
        temp_path = Path(temp_name)

        published = False

        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())

            self._crash("after_temp_fsync_before_publish")

            # Atomic, no-replace publication on the same filesystem.
            os.link(temp_path, destination)
            published = True

            self._fsync_directory()

            self._crash("after_publish_before_ack")

            self.records[uid] = values
            return "committed"

        except Exception:
            if published:
                # The object may already be durable.
                # Rebuild the UUID index before another operation.
                self._healthy = False
                try:
                    self._load()
                    self._healthy = True
                except Exception:
                    # Fail closed if recovery cannot be completed.
                    pass
            raise

        finally:
            temp_path.unlink(missing_ok=True)
            if published:
                try:
                    self._fsync_directory()
                except OSError:
                    self._healthy = False
                    raise

    def read(self, uid):
        return self.records.get(uid)

    def verify(self):
        self._healthy = False
        self._load()
        self._healthy = True
        return len(self.records)

    @property
    def count(self):
        return len(self.records)
