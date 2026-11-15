# EventzAPI — Archivist and Librarian

**Qualification baseline:** Step 7D.8 · **98 automated tests passed** (10 November 2026) · **Pre-production engineering**

EventzAPI provides archival, integrity-verification, and recovery components for systems implementing **The Eventz Law**:

\[
y = F(Y,e)
\]

Here, `e` is a new event, `F` is a pure Function, `y` is its immutable result tuple, and `Y` is an append-only tuple space. In the Eventz model, **Y is the authoritative data persistence**; indexes and other derived structures must be reconstructible rather than independent sources of truth.

## Quick Start

EventzAPI Archivist can run on Ubuntu using Docker Compose.

1. Clone this repository.
2. Copy `.env.example` to `.env`.
3. Configure your RabbitMQ AMQPS connection and queue.
4. Run `./start-eventzapi.sh`.
5. Verify startup using `sudo docker compose logs --tail=20 archivist`.

The Archivist runs as a non-root user and preserves its
append-only Y archive in `compose-Y/`.

**Installation instructions:**
[Ubuntu Docker installation guide](docs/INSTALL-UBUNTU.md)

**Newcomer qualification:**
[Verify Archivist operation](docs/QUALIFY-ARCHIVIST.md)

After installation, use the qualification guide to publish a
test tuple, verify its persistence in Y, restart the Archivist,
and demonstrate UUID duplicate suppression.

**Important:** Use your own RabbitMQ credentials. Never commit
`.env` or delete the persistent Y archive during upgrades.

## Architecture at a glance

```text
Business Functions F ── immutable tuples y ──> RabbitMQ / AMQP
                                                |
                                                v
                                           Archivist
                                                |
                                                v
                                     Y: immutable tuple archive
                                                |
                           +--------------------+-------------------+
                           |                                        |
                     Inventory / checkpoint                       Librarian
                           |                                        |
                     Checkpoint Witness                    verified tuple reads
                     authenticated receipts                 from Y or Repair Y
```

This diagram is conceptual. The repository contains several qualification prototypes and test paths; it does **not** establish that all components have been deployed as one production service.

- **Archivist:** durable tuple commits, UUID-based idempotence, and capacity/volume management.
- **Cloud Y:** content-addressed tuple storage with inventory and recovery mechanisms.
- **Checkpoint Witness:** hash-chained, HMAC-authenticated checkpoint receipts, checked against an independently trusted expected head.
- **Librarian:** verifies inventory evidence and tuple contents before returning a record; can consult a separate Repair Y when the original is damaged.
- **RabbitMQ:** AMQP transport used in the Archivist integration qualification. Message delivery and durable storage are separate responsibilities.

See [Architecture and trust boundaries](docs/ARCHITECTURE.md) for component contracts, recovery behavior, and limitations.

## Qualification evidence

The latest reported full regression run completed **98 tests in 21.379 seconds**, with no failures. It covered:

- Durable commits, duplicate UUID handling, and restart/rebuild behavior
- Volume rollover, capacity policy, and cross-volume integrity
- Content-addressed storage, inventories, missing/corrupted tuples, and recovery
- Controlled process-crash and redelivery scenarios
- Witness receipt authentication, pinned-head checks, and adversarial Librarian reads
- Step 7D.8 atomic witness snapshot tests (tests 93–98)

The qualified source snapshot is tagged **`v0.1.0-qualification`** (commit `e15acad`). These are **local qualification results**, not a production certification, penetration test, or proof of resilience to every failure mode. Some tests explicitly document known limitations.

## Run the unit-test suite

From the repository root, with a suitable Python environment:

```bash
PYTHONPATH=. python3 -m unittest discover -s tests -v
```

The suite includes subprocess crash tests. Run it in a development environment, **not against production archives**. RabbitMQ integration qualification is documented separately in [Step 3](docs/step3-rabbitmq.txt) and requires `pika` and a reachable broker.

## Repository contents

| Area | Purpose |
| --- | --- |
| `archivist_writer.py`, `archivist_consumer.py` | Local durable writer and consumer components |
| `capacity_archive.py`, `volume_archive.py`, `volume_policy.py` | Capacity and volume transitions |
| `cloud_y.py`, `cloud_y_inventory.py`, `cloud_y_recovery.py` | Content-addressed Y, inventory, recovery |
| `checkpoint_witness.py` | Independent checkpoint receipts and verification |
| `witnessed_librarian.py` | Witness-backed, integrity-checked retrieval |
| `tests/` | Automated qualification tests |
| `docs/` | Engineering notes and architecture |

## History and scope

Archivist and Librarian originated in an earlier Eventz implementation distributed through Docker approximately five years before this qualification effort. This repository captures the **newly qualified engineering baseline** rather than claiming that the historical Docker image and current modules are interchangeable.

This project is separate from the established [EventzAPI repository](https://github.com/i-Technology/eventzAPI). No production readiness, licensing terms, or integration release should be inferred solely from the qualification tag.

## Licence

Copyright (C) 2026 I-Technology Inc.

EventzAPI Archivist and Librarian is licensed under the
GNU Lesser General Public License, version 3 only.

SPDX-License-Identifier: LGPL-3.0-only

See [LICENSE](LICENSE) and [COPYING.GPL3](COPYING.GPL3)
for the complete licence terms.

Commercial use is permitted under the terms of the licence.
Independent business Functions (F) may remain proprietary,
subject to applicable licence conditions.
