# EventzAPI Archivist and Librarian — Architecture

**Status:** Step 7D.8 local qualification baseline, 10 November 2026. This document describes the tested design and its trust assumptions; it is not a production deployment specification.

## 1. Computational model

The Eventz Law is **`y = F(Y, e)`**: a pure Function `F` evaluates an event `e` in the context of immutable information `Y` and produces an immutable result tuple `y`. Business Functions do not own independent persistent databases. **Y is the authoritative data persistence**; indexes and caches are derived and should be reconstructible.

## 2. Component responsibilities

### Archivist and message transport

RabbitMQ/AMQP transports messages. The Archivist's responsibility is durable persistence of the resulting tuples, not merely broker acknowledgement. UUIDs provide an identity for idempotent retransmission; a repeated identical tuple must not create a second logical record, while a conflicting tuple for the same UUID must be rejected. The local writer and consumer qualification exercises process termination after durable commit but before acknowledgement, followed by redelivery.

The tests do not establish protection against every physical power-loss scenario, and the qualified local writer assumes a single active writer and no unauthorized external mutation.

### Y storage and volume management

The repository contains a local append-only writer and a content-addressed Cloud Y implementation. Qualification covers restart, duplicate detection, integrity checks, inventory creation, capacity thresholds, volume rollover, and retention of sealed volumes for reading. The volume manifest and derived indexes have explicit recovery behavior. These modules should not be assumed to constitute a fully integrated production storage tier.

### Inventory and checkpoint

A checkpoint records an expected inventory of tuple identifiers and digests. This provides a basis for detecting missing or corrupted objects that ordinary inspection of the surviving objects cannot establish. A checkpoint must itself be authenticated: otherwise an attacker or storage fault could alter both the objects and the inventory used to check them.

### Independent Checkpoint Witness

The Witness issues hash-chained, HMAC-SHA256-authenticated receipts for checkpoints. Verification checks receipt continuity, authentication, checkpoint contents, and an **externally pinned trusted head**. The independent head is essential: a locally consistent but rolled-back chain cannot establish its own completeness.

Step 7D.8 adds a verified checkpoint-bytes interface backed by an authenticated receipt snapshot. Its purpose is to avoid trusting a receipt reopened after the chain was verified. The qualification suite includes substitution, deletion, interrupted-publication, restart, sequence-validation, and checkpoint-modification cases.

### Witnessed Librarian and Repair Y

The Librarian validates checkpoint and witness evidence before treating an inventory as authoritative. It verifies retrieved tuple bytes and expected UUID/digest, rather than trusting a pathname or an index alone. Qualification includes rejection of a symlinked object, forged receipt, incorrect UUID mapping, and corrupted repair object. When an original object is unavailable or corrupt, a separately verified object in **Repair Y** may satisfy the read without silently modifying the damaged original.

## 3. Trust boundaries and failure assumptions

- **Witness secret:** the HMAC key must be protected outside the archive under inspection.
- **Pinned head:** the expected witness head must be retained independently and protected against rollback or replacement.
- **Single writer:** local receipt publication and archive writing rely on stated single-writer assumptions unless a separate coordination mechanism is introduced.
- **Filesystem:** durability tests exercise specified POSIX operations and controlled crashes; they do not constitute exhaustive storage-hardware or power-loss qualification.
- **Untrusted storage:** content-addressed names and index entries are not sufficient evidence by themselves; actual object bytes must be verified.
- **Recovery sources:** an alternate Y or publisher cache is useful only when its offered tuple is checked against trusted expected evidence.
- **Transport:** RabbitMQ delivery semantics and Archivist persistence semantics are distinct; the complete end-to-end protocol needs explicit integration qualification.

## 4. Qualification record

The reported Step 7D.8 full suite ran **98 tests, 0 failures, in 21.379 seconds**. The version-control reference is commit `e15acad`, tagged `v0.1.0-qualification`.

Test families include writer, capacity, volume policy/transition, Cloud Y, process-crash, inventory, recovery, Witness, Librarian, adversarial retrieval, and atomic Witness tests. Some tests intentionally demonstrate known limitations; a passing result means the expected behavior was observed, not that the limitation was eliminated.

Run the tests from the repository root:

```bash
PYTHONPATH=. python3 -m unittest discover -s tests -v
```

See `docs/step3-rabbitmq.txt` for the separate RabbitMQ–Archivist integration procedure and its stated limitations.

## 5. Not yet established by this baseline

This qualification snapshot does not, by itself, demonstrate production deployment, multi-writer coordination, independent key management, complete authorization controls, hardware power-loss tolerance, end-to-end operational monitoring, or performance under enterprise workload. Those require explicit requirements and additional evidence.

## 6. Legacy provenance

The original Archivist and Librarian were distributed in an Eventz Docker image approximately five years before the present qualification work. The legacy image is historical evidence, not a substitute for source-controlled and tested current implementations. Changes between the legacy implementation and this baseline should be recorded as they are established.
