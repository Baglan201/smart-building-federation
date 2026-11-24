"""Explicit commissioning and loopback-only service startup."""

import argparse
from pathlib import Path
from urllib.parse import urlsplit

import uvicorn

from building_federation.api import create_app
from building_federation.provision import NODES, provision
from building_federation.settings import Settings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    setup = commands.add_parser("provision", help="Create a NEW trusted three-node federation")
    setup.add_argument("--root", type=Path, default=Path("runtime"))
    setup.add_argument("--base-port", type=int, default=8101)
    serve = commands.add_parser("serve", help="Run one provisioned controller on loopback")
    serve.add_argument("--root", type=Path, default=Path("runtime"))
    serve.add_argument("--node", choices=NODES, required=True)
    args = parser.parse_args()
    if args.command == "provision":
        try:
            provision(args.root, args.base_port)
        except (ValueError, FileExistsError) as error:
            parser.error(f"Cannot provision: {error}. Use a new --root directory.")
        print(f"Created hvac, lighting, access in {args.root.resolve()}")
        return
    directory = args.root / args.node
    settings = Settings.load(directory)
    if settings.node_id != args.node:
        parser.error("Node directory and configured identity do not match")
    port = urlsplit(settings.members[args.node].url).port
    uvicorn.run(create_app(directory), host="127.0.0.1", port=port, access_log=False)
