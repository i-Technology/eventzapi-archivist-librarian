"""Standalone, single-process Eventz archive writer (initial qualification build).

Y is authoritative. The UUID index is reconstructed from Y on startup.
No broker acknowledgments are issued by this module.
"""
import csv
import io
import os
import uuid
from pathlib import Path


class ArchiveError(Exception):
    pass


class InvalidTuple(ArchiveError):
    pass


class UUIDConflict(ArchiveError):
    pass


class ArchiveCorruption(ArchiveError):
    pass


class ArchiveWriter:
    """Single-writer archive. No concurrent writers or external file mutation."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._records = {}
        self.rebuild_index()

    @staticmethod
    def _normalize(record):
        if not isinstance(record, (tuple, list)) or len(record) < 16:
            raise InvalidTuple('Expected at least 16 Eventz metadata fields')
        values = tuple(str(v) for v in record)
        try:
            record_uuid = str(uuid.UUID(values[2]))
        except (ValueError, AttributeError, TypeError) as exc:
            raise InvalidTuple('Invalid recordId UUID at field 2') from exc
        if record_uuid != values[2]:
            raise InvalidTuple('recordId must be a canonical lowercase UUID')
        if any('\r' in v or '\n' in v or '\t' in v for v in values):
            raise InvalidTuple('Embedded tab or newline is unsupported in initial writer')
        return values

    @staticmethod
    def _encode(values):
        output = io.StringIO(newline='')
        csv.writer(output, delimiter='\t', lineterminator='\n').writerow(values)
        return output.getvalue().encode('utf-8')

    def rebuild_index(self):
        """Rebuild from Y; reject truncated/malformed or contradictory rows."""
        records = {}
        if not self.path.exists():
            self._records = records
            return len(records)
        with self.path.open('rb') as file:
            for number, raw in enumerate(file, 1):
                if not raw.endswith(b'\n'):
                    raise ArchiveCorruption(f'Incomplete final row at line {number}')
                try:
                    line = raw.decode('utf-8')
                    row = next(csv.reader([line], delimiter='\t', strict=True))
                    values = self._normalize(row)
                except (UnicodeError, csv.Error, InvalidTuple) as exc:
                    raise ArchiveCorruption(f'Invalid row at line {number}: {exc}') from exc
                key = values[2]
                if key in records:
                    raise ArchiveCorruption(f'Duplicate UUID in Y at line {number}: {key}')
                records[key] = values
        self._records = records
        return len(records)

    def append(self, record):
        """Return 'committed' or 'duplicate'. Raise on failure; never acknowledge broker."""
        values = self._normalize(record)
        key = values[2]
        previous = self._records.get(key)
        if previous is not None:
            if previous == values:
                return 'duplicate'
            raise UUIDConflict(f'Conflicting contents for UUID {key}')
        payload = self._encode(values)
        # O_APPEND; one process only. On a write/sync error, index is not updated.
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            with os.fdopen(fd, 'wb', closefd=True) as file:
                written = file.write(payload)
                if written != len(payload):
                    raise OSError('Short archive write')
                file.flush()
                os.fsync(file.fileno())
        except BaseException:
            # A partial write may exist; require explicit inspection/recovery.
            raise
        self._records[key] = values
        return 'committed'

    @property
    def count(self):
        return len(self._records)
