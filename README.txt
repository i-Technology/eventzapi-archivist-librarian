EventzAPI Step 3: RabbitMQ–Archivist qualification

Copy the three .py scripts into the SAME directory as your existing archivist_writer.py.
Do NOT replace archivist_writer.py. Do NOT run against a production archive.

Requires: pip install pika (if not already installed in your venv)
Requires: RabbitMQ reachable on localhost:5672 with guest/guest, or set:
  EVENTZ_RMQ_HOST, EVENTZ_RMQ_PORT, EVENTZ_RMQ_VHOST,
  EVENTZ_RMQ_USER, EVENTZ_RMQ_PASSWORD

Run from the directory containing archivist_writer.py:
  python3 integration_qualification.py

The script creates a uniquely named durable RabbitMQ queue and a temporary Y,
forces the consumer to exit after fsync but before ACK, restarts the consumer,
verifies redelivery does not duplicate Y, and cleans up its own queue.

NOTE: This is a controlled process-crash test, NOT a physical power-loss test.
It does not verify the separate publisher-side pending cache or archival proof.
The archive writer currently assumes one active writer and no external mutations.
