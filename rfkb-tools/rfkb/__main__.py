import argparse
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description="Local RF knowledge workbench")
    commands = parser.add_subparsers(dest="command", required=True)
    base = Path(__file__).resolve().parents[1] / "data"
    for name in ("serve", "mcp", "demo", "backup"):
        command = commands.add_parser(name)
        command.add_argument("--data", type=Path, default=base / ("demo" if name == "demo" else "production"))
        if name == "serve":
            command.add_argument("--port", type=int, default=8765)
        if name == "backup":
            command.add_argument("--output", type=Path, required=True)
    restore = commands.add_parser("restore")
    restore.add_argument("archive", type=Path)
    restore.add_argument("--target", type=Path, required=True)
    args = parser.parse_args()
    from .store import KBError, KnowledgeStore
    try:
        if args.command == "serve":
            import uvicorn
            from .web import create_app
            uvicorn.run(create_app(args.data), host="127.0.0.1", port=args.port)
        elif args.command == "mcp":
            from .mcp_server import create_server
            create_server(args.data).run(transport="stdio")
        elif args.command == "demo":
            from .demo import initialize
            print(json.dumps(initialize(args.data), ensure_ascii=False))
        elif args.command == "backup":
            from .backup import create_backup
            print(create_backup(KnowledgeStore(args.data), args.output))
        elif args.command == "restore":
            from .backup import restore_backup
            print(restore_backup(args.archive, args.target))
    except KBError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
