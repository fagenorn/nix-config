"""Command line entry point. Library modules never print; the CLI owns all I/O."""

import argparse
import sys

from .model import DONE
from .store import Store

DEFAULT_PATH = "tasks.json"


def format_task(task):
    """One task per line, tab separated — scripts parse this, so the shape is stable."""
    return "%d\t%s\t%s" % (task.id, task.state, task.title)


def build_parser():
    parser = argparse.ArgumentParser(prog="tinytask", description="A very small backlog.")
    parser.add_argument("--file", default=DEFAULT_PATH, help="path to the task file")
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="add a task to the backlog")
    add.add_argument("title")

    listing = sub.add_parser("list", help="list tasks")
    listing.add_argument("--all", action="store_true", help="include done tasks")

    done = sub.add_parser("done", help="mark a task done")
    done.add_argument("id", type=int)

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    store = Store(args.file)

    if args.command == "add":
        print(format_task(store.add(args.title)))
        return 0

    if args.command == "list":
        tasks = store.load()
        if not args.all:
            tasks = [task for task in tasks if task.state != DONE]
        for task in tasks:
            print(format_task(task))
        return 0

    if args.command == "done":
        task = store.complete(args.id)
        if task is None:
            print("no such task: %d" % args.id, file=sys.stderr)
            return 1
        print(format_task(task))
        return 0

    return 2
