"""Pure, non-destructive Eventz archive capacity policy (qualification prototype)."""
from dataclasses import dataclass
from enum import Enum

class VolumeState(str, Enum):
    ACTIVE = 'active'
    SEALED = 'sealed'
    STANDBY = 'standby'

@dataclass(frozen=True)
class Volume:
    name: str
    total_bytes: int
    used_bytes: int
    state: VolumeState

    def __post_init__(self):
        if self.total_bytes <= 0 or not 0 <= self.used_bytes <= self.total_bytes:
            raise ValueError('Invalid capacity')

    @property
    def utilization(self):
        return self.used_bytes / self.total_bytes

@dataclass(frozen=True)
class Policy:
    provision_at: float = 0.80
    seal_at: float = 0.95
    reserve_bytes: int = 0

    def __post_init__(self):
        if not 0 < self.provision_at < self.seal_at < 1 or self.reserve_bytes < 0:
            raise ValueError('Invalid thresholds')

@dataclass(frozen=True)
class Decision:
    may_append: bool
    request_new_volume: bool
    seal_volume: bool
    reason: str


def evaluate(volume: Volume, incoming_bytes: int, policy: Policy = Policy()) -> Decision:
    """Decide BEFORE an append; no filesystem changes or notifications."""
    if incoming_bytes < 0:
        raise ValueError('Negative append size')
    if volume.state != VolumeState.ACTIVE:
        return Decision(False, False, False, 'Volume is not active')
    request = volume.utilization >= policy.provision_at or (volume.used_bytes + incoming_bytes) / volume.total_bytes >= policy.provision_at
    max_used = min(int(volume.total_bytes * policy.seal_at), volume.total_bytes - policy.reserve_bytes)
    if volume.used_bytes >= max_used:
        return Decision(False, True, True, 'Volume at seal threshold')
    if volume.used_bytes + incoming_bytes > max_used:
        return Decision(False, True, True, 'Append would exceed seal threshold or reserve')
    return Decision(True, request, False, 'Append within active volume headroom')


def choose_successor(volumes: list[Volume], policy: Policy = Policy()) -> Volume | None:
    """Return a suitable standby candidate; does NOT activate it."""
    candidates = [v for v in volumes if v.state == VolumeState.STANDBY and
                  v.used_bytes < min(int(v.total_bytes * policy.seal_at), v.total_bytes - policy.reserve_bytes)]
    return candidates[0] if candidates else None
