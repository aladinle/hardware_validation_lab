"""Fixed child worker. Imported only after the parent grants its launch gate."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from contracts.runner_v1 import PROBES, strict_json
from contracts.v1 import exact_keys


def main():
    request = strict_json(sys.stdin.buffer.raw.readline(65537))
    exact_keys(request, {"schema_version", "manifest", "parameters", "probe", "limits"})
    if request["schema_version"] != 1:
        raise ValueError("Unsupported worker protocol.")
    if sys.platform.startswith('linux'):
        import resource
        import math
        from contracts.runner_v1 import Limits
        limits = Limits(**request['limits']).validate()
        cpu = math.ceil(limits.cpu_seconds)
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
        memory = limits.memory_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
        resource.setrlimit(resource.RLIMIT_FSIZE, (limits.disk_bytes, limits.disk_bytes))
    cancelled = threading.Event()

    def listen():
        if sys.stdin.buffer.raw.readline(16) == b"CANCEL\n":
            cancelled.set()

    threading.Thread(target=listen, daemon=True).start()
    probe = request["probe"]
    if probe is not None:
        if probe not in PROBES:
            raise ValueError("Unknown diagnostic fixture.")
        if probe == "cooperative":
            cancelled.wait(300)
            print(json.dumps({"schema_version": 1, "outcome": "CANCELLED", "evaluation_status": "NOT_EVALUATED"}), flush=True)
            return
        if probe == "ignore_cancel":
            time.sleep(300)
        if probe == "malformed":
            print('{"outcome":"PASS","outcome":"FAIL"}', flush=True)
            return
        if probe in {"overflow", "stderr_overflow"}:
            stream = sys.stdout.buffer if probe == "overflow" else sys.stderr.buffer
            while True:
                stream.write(b"x" * 65536)
                stream.flush()
        if probe == "crash":
            os._exit(17)
        if probe == "descendant":
            child = subprocess.Popen([sys.executable, "-I", "-B", "-c", "import time; time.sleep(300)"],
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            Path("fixture.tmp").write_text(str(child.pid), encoding="ascii")
            time.sleep(300)
        if probe == "memory":
            blocks = []
            while True:
                blocks.append(bytearray(1024 * 1024))
        if probe == "cpu":
            while True:
                pass
        if probe == "disk":
            with Path("fixture.tmp").open("xb") as stream:
                while True:
                    stream.write(b"x" * 65536)
                    stream.flush()
                    time.sleep(.02)
        from workloads.can_payload_compare import compare
        report = compare(b"AA", b"AA", header_bytes=0)
        report["source"] = "runner_probe"
        if probe == "cleanup_error":
            # Owned test file only; Windows read-only attribute makes unlink fail.
            Path("fixture.tmp").write_bytes(b"owned cleanup diagnostic")
            os.chmod("fixture.tmp", 0o400)
    else:
        from workloads.registry import run
        from workloads.can_payload_compare import MAX_INPUT_BYTES
        inputs = {}
        for role in ("expected", "actual"):
            with Path(role + ".hex").open("rb") as stream:
                inputs[role] = stream.read(MAX_INPUT_BYTES + 1)
        report = run(request["manifest"], inputs, request["parameters"], wheel_path="plugin.whl")
    print(json.dumps(report, sort_keys=True, separators=(",", ":")), flush=True)


if __name__ == "__main__":
    main()
