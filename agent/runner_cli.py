"""Local supervised runner CLI; never accepts arbitrary commands or imports."""
import argparse
import json
import sys
from contracts.runner_v1 import Limits, PROBES, strict_json
from contracts.v1 import ContractError
from .runner import bounded_read, run_can, run_probe


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local synthetic Windows runner; no queued jobs or hardware access.")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Run the installed CAN comparator in a contained child.")
    for name in ("manifest", "expected", "actual", "wheel"):
        run.add_argument("--" + name, required=True)
    run.add_argument("--header-bytes", required=True, type=int)
    probe = sub.add_parser("probe", help="Fixed synthetic runner diagnostic, not a CAN/device test.")
    probe.add_argument("--scenario", choices=PROBES, required=True)
    for command in (run, probe):
        command.add_argument("--output-dir", required=True, help="New local evidence directory.")
        command.add_argument("--timeout", type=float, default=10)
        command.add_argument("--grace", type=float, default=.5)
        command.add_argument("--memory-mb", type=int, default=256)
        command.add_argument("--cpu-seconds", type=float, default=5)
        command.add_argument("--cpu-percent", type=int, default=50 if sys.platform == 'win32' else 100)
    args = parser.parse_args(argv)
    try:
        limits = Limits(wall_seconds=args.timeout, grace_seconds=args.grace, memory_mb=args.memory_mb,
                        cpu_seconds=args.cpu_seconds, cpu_percent=args.cpu_percent)
        if args.command == "run":
            manifest = strict_json(bounded_read(args.manifest, 65536))
            result = run_can(manifest, args.expected, args.actual, args.wheel, args.output_dir,
                             parameters={"header_bytes": args.header_bytes}, limits=limits)
        else:
            result = run_probe(args.scenario, args.output_dir, limits=limits)
        print(json.dumps(result, sort_keys=True))
        # A retained PASS never hides cleanup/termination uncertainty at the CLI.
        if result["quarantine_required"]:
            return 2
        return {"PASS": 0, "FAIL": 1, "ERROR": 2, "TIMEOUT": 2, "CANCELLED": 2}[result["outcome"]]
    except (ContractError, OSError, ValueError):
        print("Runner setup rejected: verify local files, policy/limits and unused output directory.", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130  # Interrupted before launch/output collection; no new worker.


if __name__ == "__main__":
    raise SystemExit(main())
