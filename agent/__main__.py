import argparse
import json
import sys
import time
from . import __version__
from .client import contact_once, enroll_client, replace_credential
from .transport import AgentError


def main(argv=None):
    parser = argparse.ArgumentParser(description="Hardware Validation Lab native identity/heartbeat client. No workloads in M2B.1.")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    enrollment = commands.add_parser("enroll")
    enrollment.add_argument("--server", required=True)
    enrollment.add_argument("--invitation-file", required=True)
    enrollment.add_argument("--state-file", required=True)
    contact = commands.add_parser("heartbeat")
    contact.add_argument("--state-file", required=True)
    contact.add_argument("--count", type=int, default=1)
    contact.add_argument("--interval", type=int, default=5)
    replacement = commands.add_parser("install-credential")
    replacement.add_argument("--state-file", required=True)
    replacement.add_argument("--credential-file", required=True)
    replacement.add_argument("--output-file", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "enroll":
            print(json.dumps(enroll_client(args.server, args.invitation_file, args.state_file)))
        elif args.command == "heartbeat":
            if not 1 <= args.count <= 1000 or not 1 <= args.interval <= 300:
                raise AgentError("Use count 1-1000 and interval 1-300 seconds.")
            for index in range(args.count):
                print(json.dumps(contact_once(args.state_file)), flush=True)
                if index + 1 < args.count:
                    time.sleep(args.interval)
        else:
            print(json.dumps(replace_credential(args.state_file, args.credential_file, args.output_file)))
        return 0
    except AgentError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
