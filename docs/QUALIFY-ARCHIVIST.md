# EventzAPI Archivist — Newcomer Qualification

## Objective

Verify that a fresh EventzAPI installation can:

1. Connect to RabbitMQ using AMQPS.
2. Receive a published tuple.
3. Commit the tuple to persistent Y.
4. Recover Y after restarting.
5. Suppress duplicate UUIDs.

These are functional qualification tests, not production certification.

## Prerequisites

Complete the [Ubuntu installation procedure](INSTALL-UBUNTU.md).

The Archivist must be running.

The .env file must contain EVENTZ_RMQ_URL and EVENTZ_QUEUE.

Run all commands from the repository root.

## 1. Verify the Archivist

sudo docker compose ps

sudo docker compose logs --tail=10 archivist

Confirm that the container is running and the consumer is ready.

## 2. Publish one tuple

Run:

sudo docker compose run --rm --no-deps \
  --entrypoint python \
  -v "$PWD/qualification_publisher.py:/eventzapi/qualification_publisher.py:ro" \
  archivist \
  qualification_publisher.py \
  --queue "$(grep '^EVENTZ_QUEUE=' .env | cut -d= -f2-)" \
  --count 1

Record the UUID printed by the publisher.

Broker confirmation does not establish commitment to Y.

## 3. Verify Y

Replace UUID_HERE with the published UUID:

grep -c 'UUID_HERE' compose-Y/compose.tsv

Expected result: 1

## 4. Verify recovery

sudo docker compose restart archivist

sudo docker compose logs --tail=10 archivist

Confirm that the Archivist reports the recovered tuple count.

## 5. Verify duplicate suppression

Publish the same UUID again using the complete command below.
Replace UUID_HERE with the UUID recorded in Step 2:

sudo docker compose run --rm --no-deps \
  --entrypoint python \
  -v "$PWD/qualification_publisher.py:/eventzapi/qualification_publisher.py:ro" \
  archivist \
  qualification_publisher.py \
  --queue "$(grep '^EVENTZ_QUEUE=' .env | cut -d= -f2-)" \
  --count 1 \
  --uuid UUID_HERE

The publisher should report broker confirmation.

The Archivist should recognize the UUID as a duplicate
and leave Y unchanged.

Verify:

grep -c 'UUID_HERE' compose-Y/compose.tsv

Expected result: 1

Inspect the Archivist log:

sudo docker compose logs --tail=20 archivist

Look for a duplicate message containing the UUID.

## Interpretation

A successful qualification demonstrates that:

- RabbitMQ accepted the published tuple.
- The Archivist committed the tuple to Y.
- Y survived container restart.
- Repeated publication of the same UUID did not
  create another archived tuple.

The test does not establish complete production readiness.

## AI-assisted qualification

Developers are encouraged to ask their AI assistant to:

- Examine the EventzAPI source code.
- Explain the Eventz Law and the role of Y.
- Review the Archivist's durability guarantees.
- Reproduce the qualification tests.
- Identify potential failure modes.
- Propose additional tests.

The objective is independent understanding and verification.
