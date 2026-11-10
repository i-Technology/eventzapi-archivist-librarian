# EventzAPI Step 5: durable volume handoff (isolated prototype)

This prototype depends only on Python's standard library. It includes an unchanged
copy of the Step 1 `archivist_writer.py` for stand-alone execution.

Run from the extracted `eventz-step5` directory:

    python3 -m unittest -v test_volume_archive.py

All tests use TemporaryDirectory and do not access RabbitMQ or existing archives.

Design:
- `volumes.json` identifies the current active volume and ordered volume names.
- Transition uses fsync(temp manifest), os.replace, fsync(parent directory).
- The previous volume remains readable; new writes target the successor.
- UUID index is rebuilt from all volumes and rejects cross-volume duplication.
- Crash injection tests simulate exceptions at transition and append boundaries.

IMPORTANT LIMITATIONS:
- This is not yet wired to Step 4 capacity policy or Step 3 RabbitMQ consumer.
- This is a single-process, single-writer prototype; no locking, hot swapping,
  multiple disks, distributed storage, or physical power-cut qualification.
- Volume files are in ONE directory for testing, not actually on separate drives.
- The `ArchiveWriter` does not fsync the parent directory when a new TSV is created.
  Therefore first-create durability is not yet qualified under sudden power loss.
- An existing/stray archive file not named in the manifest is not detected here.
  Production implementation must fail closed on unknown files, validate physical
  volume identity/mount points, and ensure sealed volumes are never modified.
- The manifest update is crash-safe under assumed POSIX local filesystem semantics;
  actual power-loss durability needs hardware/filesystem fault injection.
- Do not point this prototype at production archives.
