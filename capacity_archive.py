# Copyright (C) 2026 I-Technology Inc.
# SPDX-License-Identifier: LGPL-3.0-only

"""Step 6 qualification adapter: simulated per-volume capacity, not disk monitoring.

Single writer. Does not change the existing ArchiveWriter or VolumeArchive.
"""
from pathlib import Path
from archivist_writer import ArchiveWriter, UUIDConflict
from volume_archive import VolumeArchive, VolumeError
from volume_policy import Volume, VolumeState, Policy, evaluate


class CapacityArchive:
    def __init__(self, directory, capacities, policy=Policy(), *, crash_hook=None):
        self.archive = VolumeArchive(directory, crash_hook=crash_hook)
        self.capacities = dict(capacities)
        self.policy = policy
        if set(self.capacities) != set(self.archive.names):
            raise ValueError('Capacities must cover exactly the manifest volumes')
        if any(not isinstance(v, int) or isinstance(v, bool) or v <= 0 for v in self.capacities.values()):
            raise ValueError('Capacities must be positive integer bytes')
        self._validate_existing()

    @classmethod
    def initialize(cls, directory, capacities, policy=Policy(), *, crash_hook=None):
        names = tuple(capacities)
        VolumeArchive.initialize(directory, names=names)
        return cls(directory, capacities, policy, crash_hook=crash_hook)

    def _used(self, name):
        path = self.archive.directory / f'{name}.tsv'
        return path.stat().st_size if path.exists() else 0

    def _validate_existing(self):
        for name in self.archive.names:
            used = self._used(name)
            if used > self.capacities[name]:
                raise VolumeError(f'Existing {name} exceeds configured capacity')

    def _volume(self, name):
        active_idx = self.archive.names.index(self.archive.active)
        idx = self.archive.names.index(name)
        state = (VolumeState.SEALED if idx < active_idx else
                 VolumeState.ACTIVE if idx == active_idx else VolumeState.STANDBY)
        return Volume(name, self.capacities[name], self._used(name), state)

    def append(self, record):
        values = ArchiveWriter._normalize(record)
        previous = self.archive.uuid_index.get(values[2])
        if previous is not None:
            if previous[1] == values:
                return 'duplicate'
            raise UUIDConflict(f'Conflicting UUID {values[2]} across volumes')
        incoming = len(ArchiveWriter._encode(values))
        active = self.archive.active
        decision = evaluate(self._volume(active), incoming, self.policy)
        if not decision.may_append:
            idx = self.archive.names.index(active)
            if idx + 1 >= len(self.archive.names):
                raise VolumeError('No successor; tuple not appended')
            successor = self.archive.names[idx + 1]
            candidate = self._volume(successor)
            if self._used(successor):
                raise VolumeError('Successor not empty; tuple not appended')
            if not evaluate(Volume(successor, candidate.total_bytes, candidate.used_bytes,
                                   VolumeState.ACTIVE), incoming, self.policy).may_append:
                raise VolumeError('Successor lacks capacity; tuple not appended')
            self.archive.activate_next()  # durable manifest switch, before append
        return self.archive.append(values)

    @property
    def active(self):
        return self.archive.active

    @property
    def count(self):
        return self.archive.count
