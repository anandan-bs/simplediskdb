"""Command-line interface for simplediskdb."""

import argparse
from logging import getLogger

from .db import load_example_data, delete_example_data
from .viewer import main as viewer_main

logger = getLogger(__name__)

def main():
    """Run the command-line interface."""
    parser = argparse.ArgumentParser(
        description='Simple disk database - MongoDB-style disk-based database')
    subparsers = parser.add_subparsers(dest='command', help='Commands')

    # Example data commands
    example_parser = subparsers.add_parser('example', help='Manage example data')
    example_parser.add_argument('action', choices=['load', 'delete'],
                              help='Action to perform with example data')

    # Viewer command
    viewer_parser = subparsers.add_parser('viewer', help='Start the web viewer')
    viewer_parser.add_argument('--host', default='127.0.0.1',
                             help='Host to bind the server to')
    viewer_parser.add_argument('--port', type=int, default=5000,
                             help='Port to run the server on')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    if args.command == 'example':
        if args.action == 'load':
            load_example_data()
        else:  # delete
            delete_example_data()
    elif args.command == 'viewer':
        viewer_main(host=args.host, port=args.port)

if __name__ == "__main__":
    main()
