"""Publish a durable test tuple to a dedicated qualification queue."""
import argparse
import uuid
import pika
from archivist_consumer import connection

ZERO = '00000000-0000-0000-0000-000000000000'


def make_record(number, record_uuid=None):
    return ('100.00', 0, record_uuid or str(uuid.uuid4()), ZERO, ZERO, 'qualification',
            '2026-11-05T00:00:00', ZERO, ZERO, False, ZERO,
            '', '', '', '', '', f'test-{number}', number)


def publish(ch, queue, record):
    return ch.basic_publish(exchange='', routing_key=queue, body=str(record).encode('utf-8'),
                            mandatory=True, properties=pika.BasicProperties(delivery_mode=2))


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--queue', required=True)
    p.add_argument('--count', type=int, default=10)
    p.add_argument('--uuid', default=None,
                   help='Reuse this UUID for a single-message test')
    args = p.parse_args()
    if args.count < 1:
        p.error('--count must be at least 1')
    if args.uuid:
        uuid.UUID(args.uuid)
        if args.count != 1:
            p.error('--uuid requires --count 1')
    with connection() as conn:
        ch = conn.channel()
        ch.queue_declare(queue=args.queue, durable=True)
        ch.confirm_delivery()
        for i in range(args.count):
            record = make_record(i, args.uuid)
            publish(ch, args.queue, record)
            print(record[2])
    print(f'Published {args.count} persistent messages (broker confirmed; NOT Y-confirmed)')


if __name__ == '__main__':
    main()
