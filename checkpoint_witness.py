
"""
EventzAPI Step 7D.5 — Independent checkpoint witness.

Local qualification prototype:
- HMAC-SHA256 authenticated receipts
- Append-only receipt files
- Hash-chained receipt history
- Explicit externally pinned head for rollback detection

Assumptions:
- One witness writer
- Trusted HMAC key outside Y
- Trusted expected head held independently
- Local POSIX filesystem with fsync and hard links
"""

import hashlib
import hmac
import json
import os
import tempfile
from pathlib import Path


class WitnessError(Exception):
    pass


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def sync_directory(directory):
    fd = os.open(str(directory), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class CheckpointWitness:

    FORMAT = "eventz-checkpoint-witness-v1"
    GENESIS = "0" * 64

    def __init__(self, directory, key):
        self.directory = Path(directory)

        if not isinstance(key, bytes) or len(key) < 32:
            raise ValueError(
                "Witness key must contain at least 32 bytes"
            )

        self.key = key
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, sequence):
        return self.directory / f"{sequence:012d}.receipt"

    def _mac(self, body):
        return hmac.new(
            self.key,
            canonical(body),
            hashlib.sha256,
        ).hexdigest()

    def _receipt_digest(self, receipt):
        return sha256(canonical(receipt))

    def _write_new(self, path, data):
        """
        Durable no-overwrite publication.

        The temporary file is fsynced before linking.
        The directory is fsynced after publication.
        """
        fd, temporary = tempfile.mkstemp(
            prefix=".pending-",
            dir=str(self.directory),
        )

        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())

            try:
                os.link(temporary, path)
            except FileExistsError as exc:
                raise WitnessError(
                    f"Receipt already exists: {path.name}"
                ) from exc

            sync_directory(self.directory)

        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _receipt_paths(self):
        paths = sorted(self.directory.glob("*.receipt"))

        for path in paths:
            if not path.name[:-8].isdigit():
                raise WitnessError(
                    f"Invalid receipt filename: {path.name}"
                )

        return paths

    def _verified_chain_snapshot(self, expected_head=None):
        """Authenticate a chain and retain its receipts from one read pass.

        The selected receipt is never reopened after verification.
        An independently pinned expected_head is required for secure reads.
        """
        paths = self._receipt_paths()
        previous = self.GENESIS
        receipts = {}
        for sequence, path in enumerate(paths, start=1):
            if path != self._path(sequence):
                raise WitnessError("Missing or out-of-order receipt")
            try:
                receipt = json.loads(path.read_bytes())
                body = receipt["body"]
                mac = receipt["mac"]
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise WitnessError("Unreadable receipt") from exc
            if not isinstance(body, dict):
                raise WitnessError("Invalid receipt body")
            if body.get("format") != self.FORMAT:
                raise WitnessError("Unknown receipt format")
            if type(body.get("sequence")) is not int or body["sequence"] != sequence:
                raise WitnessError("Invalid receipt sequence")
            if body.get("previous") != previous:
                raise WitnessError("Broken receipt chain")
            if not isinstance(mac, str) or not hmac.compare_digest(
                self._mac(body), mac
            ):
                raise WitnessError("Receipt authentication failed")
            previous = self._receipt_digest(receipt)
            receipts[sequence] = receipt
        if expected_head is not None:
            if not isinstance(expected_head, str) or not hmac.compare_digest(
                previous, expected_head
            ):
                raise WitnessError("Witness rollback or head mismatch")
        return {"count": len(receipts), "head": previous, "receipts": receipts}

    def verify_chain(self, expected_head=None):
        snapshot = self._verified_chain_snapshot(expected_head)
        return {"count": snapshot["count"], "head": snapshot["head"]}

    def verified_checkpoint_bytes(self, checkpoint_file, sequence, expected_head):
        """Return only bytes authenticated by the selected receipt snapshot."""
        if type(sequence) is not int or sequence < 1:
            raise WitnessError("Invalid receipt sequence")
        if not isinstance(expected_head, str) or len(expected_head) != 64:
            raise WitnessError("Trusted witness head is required")
        try:
            data = Path(checkpoint_file).read_bytes()
        except OSError as exc:
            raise WitnessError("Checkpoint unavailable") from exc
        # Preserve the established verify_chain hook and independently
        # authenticate the receipt snapshot used below.
        self.verify_chain(expected_head=expected_head)
        chain = self._verified_chain_snapshot(expected_head)
        receipt = chain["receipts"].get(sequence)
        if receipt is None:
            raise WitnessError("Referenced receipt unavailable")
        expected_digest = receipt["body"].get("checkpoint_sha256")
        if not isinstance(expected_digest, str) or len(expected_digest) != 64:
            raise WitnessError("Invalid witnessed checkpoint digest")
        self._verify_checkpoint_document(data)
        if not hmac.compare_digest(sha256(data), expected_digest):
            raise WitnessError("Checkpoint differs from witnessed version")
        return data

    def attest(self, checkpoint_file):
        """
        Append a receipt for the exact checkpoint bytes.

        The caller must ensure the checkpoint has already
        been finalized and cannot change during attestation.
        """
        checkpoint_file = Path(checkpoint_file)

        state = self.verify_chain()

        checkpoint_bytes = checkpoint_file.read_bytes()

        # Verify the inventory's own internal digest too.
        self._verify_checkpoint_document(checkpoint_bytes)

        body = {
            "format": self.FORMAT,
            "sequence": state["count"] + 1,
            "previous": state["head"],
            "checkpoint_sha256": sha256(checkpoint_bytes),
        }

        receipt = {
            "body": body,
            "mac": self._mac(body),
        }

        self._write_new(
            self._path(body["sequence"]),
            canonical(receipt),
        )

        return {
            "sequence": body["sequence"],
            "head": self._receipt_digest(receipt),
            "checkpoint_sha256": body["checkpoint_sha256"],
        }

    @staticmethod
    def _verify_checkpoint_document(data):
        try:
            document = json.loads(data)
            body = document["body"]
            claimed_digest = document["digest"]
        except (ValueError, KeyError, TypeError) as exc:
            raise WitnessError(
                "Invalid inventory checkpoint"
            ) from exc

        if not isinstance(body, dict):
            raise WitnessError("Invalid checkpoint body")

        if not isinstance(claimed_digest, str):
            raise WitnessError("Invalid checkpoint digest")

        if not hmac.compare_digest(
            sha256(canonical(body)),
            claimed_digest,
        ):
            raise WitnessError(
                "Inventory checkpoint digest mismatch"
            )

    def verify_checkpoint(self, checkpoint_file, sequence, expected_head):
        self.verified_checkpoint_bytes(checkpoint_file, sequence, expected_head)
        return True
