# EventzAPI Archivist — Ubuntu Installation

## Purpose

The EventzAPI Archivist subscribes to a RabbitMQ queue and
preserves received Eventz tuples in an append-only archive Y.

Each tuple has a canonical UUID. Duplicate deliveries are
suppressed, and previously committed tuples remain available
after container restarts.

This guide describes the Docker Compose deployment on Ubuntu.

## Prerequisites

- Ubuntu with Docker Engine installed
- Docker Compose v2
- Git
- Access to a RabbitMQ broker using AMQPS
- A RabbitMQ queue configured for the Archivist

The Archivist uses a persistent host directory for Y.

## 1. Obtain the repository

git clone https://github.com/i-Technology/eventzapi-archivist-librarian.git

cd eventzapi-archivist-librarian

## 2. Configure RabbitMQ

Copy the example configuration:

cp .env.example .env

Edit .env and supply your own RabbitMQ AMQPS connection URL.

Set EVENTZ_QUEUE to the queue this Archivist will consume.

Do not commit .env or disclose its credentials.

## 3. Start the Archivist

Run:

./start-eventzapi.sh

The launcher creates compose-Y if necessary and starts the
Archivist using Docker Compose.

The container runs using the invoking user's UID and GID.

## 4. Verify startup

Run:

sudo docker compose logs --tail=20 archivist

A successful startup reports:

Consumer ready: QUEUE_NAME; Y contains N tuples

QUEUE_NAME is the configured queue.
N is the number of tuples recovered from the archive.

## 5. Locate the archive

The persistent archive is stored at:

compose-Y/compose.tsv

The directory is mounted inside the container at /Y.

Do not delete this directory when restarting or upgrading
the Archivist.

## 6. Restart

Run:

./start-eventzapi.sh

The Archivist reopens its existing archive and reconstructs
its UUID index as necessary.

Previously committed tuples remain in Y.

## 7. Stop

Run:

sudo docker compose down

This removes the container but preserves the host archive
in compose-Y.

## 8. Delivery and durability

RabbitMQ transports tuples to the Archivist.

The Archivist commits each tuple to Y before acknowledging
the corresponding RabbitMQ delivery.

A retransmitted tuple with an existing UUID is not appended
again.

A broker confirmation of publication is not proof that a
tuple has been committed to Y. Applications requiring
end-to-end confirmation must verify the tuple's presence
in Y.

## 9. Operational considerations

- Use a dedicated queue appropriate to the deployment.
- Protect RabbitMQ credentials.
- Back up the persistent Y directory.
- Monitor archive capacity and available disk space.
- Do not run multiple independent writers against the
  same archive file.
- Qualify recovery and connectivity before production use.

## Qualification status

This installation procedure follows the Ubuntu Docker
Compose qualification performed in November 2026.

The qualification verified AMQPS connectivity to a remote
RabbitMQ broker in Ireland, non-root container execution,
persistent Y recovery, and UUID duplicate suppression.

These tests establish specific engineering properties;
they do not constitute production certification.
