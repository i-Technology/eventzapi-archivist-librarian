"""Qualification-only RabbitMQ consumer. Not the production Archivist."""
import argparse
import ast
import os
from pathlib import Path
import pika
from archivist_writer import ArchiveWriter, ArchiveError

def connection():
    url = os.getenv('EVENTZ_RMQ_URL')

    if url:
        if not url.startswith('amqps://'):
            raise ValueError(
                'EVENTZ_RMQ_URL must use amqps://'
            )
        parameters = pika.URLParameters(url)
    else:
        parameters = pika.ConnectionParameters(
            host=os.getenv('EVENTZ_RMQ_HOST', 'localhost'),
            port=int(os.getenv('EVENTZ_RMQ_PORT', '5672')),
            virtual_host=os.getenv('EVENTZ_RMQ_VHOST', '/'),
            credentials=pika.PlainCredentials(
                os.getenv('EVENTZ_RMQ_USER', 'guest'),
                os.getenv('EVENTZ_RMQ_PASSWORD', 'guest')
            ),
            heartbeat=60,
            blocked_connection_timeout=30
        )

    return pika.BlockingConnection(parameters)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--queue', required=True)
    parser.add_argument('--archive', required=True)
    parser.add_argument('--crash-marker', help='Crash once after first durable commit, before ACK')
    args = parser.parse_args()
    writer = ArchiveWriter(args.archive)  # fail closed if Y is damaged
    conn = connection()
    ch = conn.channel()
    ch.queue_declare(queue=args.queue, durable=True)
    ch.basic_qos(prefetch_count=1)
    print(f'Consumer ready: {args.queue}; Y contains {writer.count} tuples', flush=True)

    def callback(channel, method, properties, body):
        try:
            record = ast.literal_eval(body.decode('utf-8'))
            outcome = writer.append(record)
        except (ValueError, SyntaxError, UnicodeError, ArchiveError, TypeError) as exc:
            print(f'FAIL CLOSED: invalid/conflicting tuple: {exc}', flush=True)
            # Leave message unacknowledged and stop; avoid a requeue spin.
            channel.stop_consuming()
            return
        except OSError as exc:
            print(f'FAIL CLOSED: archive I/O failure: {exc}', flush=True)
            channel.stop_consuming()
            return
        print(f'{outcome}: {record[2]} redelivered={method.redelivered}', flush=True)
        if outcome == 'committed' and args.crash_marker and not Path(args.crash_marker).exists():
            # marker is outside Y; only a test control, not a persistence index.
            Path(args.crash_marker).write_text('crashed after fsync, before ACK')
            print('INJECTED CRASH after fsync and before ACK', flush=True)
            os._exit(73)
        channel.basic_ack(delivery_tag=method.delivery_tag)

    ch.basic_consume(queue=args.queue, on_message_callback=callback, auto_ack=False)
    try:
        ch.start_consuming()
    finally:
        if conn.is_open:
            conn.close()


if __name__ == '__main__':
    main()
