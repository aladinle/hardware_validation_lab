"""Opt-in local file demo CLI; not a runner, agent assignment or backend client."""
import argparse
import json
from pathlib import Path
import sys
from contracts.plugins import executable_manifest
from contracts.v1 import ContractError
from .can_payload_compare import MAX_INPUT_BYTES, human_report, json_report
from .registry import run, verify_wheel


def read_file(name, limit):
    path = Path(name)
    if path.is_symlink() or not path.is_file():
        raise ContractError("Input must be a regular local file.")
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ContractError("Local input exceeds its size limit.")
    return data


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local synthetic CAN file analysis; no hardware or queued jobs.")
    commands = parser.add_subparsers(dest="command", required=True)
    manifest = commands.add_parser("manifest", help="Write candidate manifest for local demo, not SQL approval.")
    manifest.add_argument("--header-bytes", type=int, required=True)
    manifest.add_argument("--output", required=True)
    compare = commands.add_parser("compare", help="Compare explicit local files using a declared manifest.")
    compare.add_argument("--manifest", required=True)
    compare.add_argument("--expected", required=True)
    compare.add_argument("--actual", required=True)
    compare.add_argument("--header-bytes", type=int, required=True)
    compare.add_argument("--output-dir", required=True, help="New directory; existing paths are preserved.")
    for command in (manifest, compare):
        command.add_argument("--wheel", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "manifest":
            content = executable_manifest(args.header_bytes, verify_wheel(args.wheel))
            with Path(args.output).open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(json_report(content))
            print("Candidate local manifest saved; this does not grant backend approval or dispatch.")
            return 0
        manifest = json.loads(read_file(args.manifest, 65536))
        result = run(manifest, {"expected": read_file(args.expected, MAX_INPUT_BYTES), "actual": read_file(args.actual, MAX_INPUT_BYTES)},
                     {"header_bytes": args.header_bytes}, wheel_path=args.wheel)
        output = Path(args.output_dir)
        output.mkdir(exist_ok=False)
        (output / "report.json").write_text(json_report(result), encoding="utf-8", newline="\n")
        (output / "report.txt").write_text(human_report(result), encoding="utf-8", newline="\n")
        print(human_report(result), end="")
        return {"PASS": 0, "FAIL": 1, "ERROR": 2}[result["outcome"]]
    except (ContractError, OSError, ValueError):
        print("Local comparison setup rejected: check manifest/policy, matching wheel, input files and unused output path.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
