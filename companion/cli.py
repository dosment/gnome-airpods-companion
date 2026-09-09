"""CLI entry point. Mutation commands are always explicit."""
import argparse
import json
from .backend import Backend


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command",required=True)
    sub.add_parser("status")
    mode = sub.add_parser("mode")
    mode.add_argument("value",choices=("music","meeting"))
    sub.add_parser("connect")
    sub.add_parser("disconnect")
    vox = sub.add_parser("voxtype")
    vox.add_argument("routing",choices=("default","pin"))
    vox.add_argument("source",nargs="?")
    policy = sub.add_parser("policy")
    policy.add_argument("value",choices=("enable","disable"))
    watch = sub.add_parser("watch")
    watch.add_argument("--iterations",type=int)
    watch.add_argument("--interval",type=float,default=2.0)
    apple = sub.add_parser("apple")
    apple.add_argument("verb")
    select = sub.add_parser("select-device")
    select.add_argument("address")
    sub.add_parser("voxtype-run")
    args = parser.parse_args(argv)
    app = Backend()
    try:
        if args.command == "status":
            return dispatch(args, app, parser)
        lock_name = "watch" if args.command == "watch" else "voxtype" if args.command == "voxtype-run" else "mutation"
        with app.exclusive(lock_name):
            return dispatch(args, app, parser)
    except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"schema_version":1,"error":str(exc)}))
        return 1


def dispatch(args, app, parser):
    if args.command == "voxtype-run":
        return app.run_voxtype()
    if args.command == "mode":
        result = app.mode(args.value)
    elif args.command in ("connect","disconnect"):
        result = app.connection(args.command == "connect")
    elif args.command == "voxtype":
        if (args.routing == "pin") != (args.source is not None):
            parser.error("pin requires NODE_NAME; default accepts no source")
        result = app.voxtype(args.source)
    elif args.command == "policy":
        result = app.policy(args.value == "enable")
    elif args.command == "watch":
        result = app.watch(iterations=args.iterations, interval=args.interval)
    elif args.command == "apple":
        result = app.apple(args.verb)
    elif args.command == "select-device":
        result = app.select_device(args.address)
    else:
        result = app.status()
    print(json.dumps(result))
    return 0 if not result.get("error") else 1
