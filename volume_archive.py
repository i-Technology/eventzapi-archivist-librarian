"""Step 5 prototype: crash-safe logical Y across immutable/sealed volume files.

Single writer, local POSIX filesystem, no external mutation. Not production storage.
"""
import json
import os
from pathlib import Path

from archivist_writer import ArchiveWriter, ArchiveCorruption, UUIDConflict


class VolumeError(Exception):
    pass


class VolumeArchive:
    def __init__(self, directory, *, crash_hook=None):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.manifest = self.directory / 'volumes.json'
        self.crash_hook = crash_hook
        if not self.manifest.exists():
            raise VolumeError('No manifest: call initialize() for a NEW, empty directory')
        self._load()

    @classmethod
    def initialize(cls, directory, names=('Y1', 'Y2'), *, crash_hook=None):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        if any(directory.iterdir()):
            raise VolumeError('Initialization requires an empty directory')
        names = list(names)
        if not names or len(set(names)) != len(names) or any(not cls._valid_name(n) for n in names):
            raise VolumeError('Invalid volume names')
        obj = cls.__new__(cls)
        obj.directory, obj.manifest, obj.crash_hook = directory, directory / 'volumes.json', crash_hook
        obj._atomic_manifest({'version': 1, 'active': names[0], 'volumes': names})
        obj._load()
        return obj

    @staticmethod
    def _valid_name(name):
        return isinstance(name, str) and name.isascii() and name.isalnum() and name.startswith('Y')

    def _atomic_manifest(self, data):
        tmp = self.directory / 'volumes.json.tmp'
        payload = (json.dumps(data, sort_keys=True) + '\n').encode()
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, 'wb') as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            if self.crash_hook:
                self.crash_hook('before_manifest_replace')
            os.replace(tmp, self.manifest)
            self._fsync_directory()
            if self.crash_hook:
                self.crash_hook('after_manifest_replace')
        finally:
            # If an injected crash is an exception, clean staging file; real SIGKILL
            # may leave it, and startup deliberately ignores it.
            tmp.unlink(missing_ok=True)

    def _fsync_directory(self):
        fd = os.open(self.directory, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def _load(self):
        try:
            data = json.loads(self.manifest.read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            raise VolumeError('Manifest missing or invalid; fail closed') from exc
        names = data.get('volumes')
        if (data.get('version') != 1 or not isinstance(names, list) or not names or
            len(set(names)) != len(names) or any(not self._valid_name(n) for n in names) or
            data.get('active') not in names):
            raise VolumeError('Invalid manifest contents')
        self.names = names
        self.active = data['active']
        self.writers = {name: ArchiveWriter(self.directory / f'{name}.tsv') for name in names}
        self.uuid_index = {}
        for name, writer in self.writers.items():
            for key, values in writer._records.items():
                if key in self.uuid_index:
                    raise ArchiveCorruption(f'UUID {key} found in multiple volumes')
                self.uuid_index[key] = (name, values)
        # Only the last activated volume may be active; earlier volumes are sealed.
        if self.names.index(self.active) < 0:
            raise VolumeError('Invalid active volume')

    def append(self, record):
        values = ArchiveWriter._normalize(record)
        previous = self.uuid_index.get(values[2])
        if previous is not None:
            if previous[1] == values:
                return 'duplicate'
            raise UUIDConflict(f'Conflicting UUID {values[2]} across volumes')
        status = self.writers[self.active].append(values)
        if self.crash_hook:
            self.crash_hook('after_archive_fsync_before_ack')
        self.uuid_index[values[2]] = (self.active, values)
        return status

    def activate_next(self):
        i = self.names.index(self.active)
        if i + 1 >= len(self.names):
            raise VolumeError('No standby volume')
        successor = self.names[i + 1]
        if self.writers[successor].count:
            raise VolumeError('Successor is not empty')
        self._atomic_manifest({'version': 1, 'active': successor, 'volumes': self.names})
        self.active = successor
        return successor

    @property
    def count(self):
        return len(self.uuid_index)
