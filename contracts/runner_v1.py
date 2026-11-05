"""Local runner policy. No commands, import paths or remote host paths."""
from dataclasses import asdict, dataclass
import math
from .v1 import ContractError


@dataclass(frozen=True)
class Limits:
    wall_seconds: float = 10.0
    grace_seconds: float = 0.5
    cpu_seconds: float = 5.0
    cpu_percent: int = 50
    memory_mb: int = 256
    stdout_bytes: int = 8 * 1024 * 1024
    stderr_bytes: int = 65536
    disk_bytes: int = 40 * 1024 * 1024
    processes: int = 4

    def validate(self):
        for value, minimum, maximum in ((self.wall_seconds, .1, 300), (self.grace_seconds, .1, 5), (self.cpu_seconds, .1, 300)):
            if type(value) not in (int, float) or not math.isfinite(value) or not minimum <= value <= maximum:
                raise ContractError("Invalid runner time limit.")
        for value, minimum, maximum in ((self.cpu_percent, 1, 100), (self.memory_mb, 64, 1024),
                                        (self.stdout_bytes, 512, 8 * 1024 * 1024), (self.stderr_bytes, 512, 65536),
                                        (self.disk_bytes, 1024, 64 * 1024 * 1024), (self.processes, 1, 4)):
            if type(value) is not int or not minimum <= value <= maximum:
                raise ContractError("Invalid runner resource limit.")
        return self

    def document(self):
        return asdict(self)


PROBES = ("pass", "cooperative", "ignore_cancel", "malformed", "overflow", "stderr_overflow", "crash",
          "descendant", "memory", "cpu", "disk", "cleanup_error", "prepare_error")


def strict_json(raw):
    import json

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ContractError("Duplicate JSON key.")
            result[key] = value
        return result

    def constant(value):
        raise ContractError("Nonfinite JSON value.")

    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ContractError("Malformed worker JSON.") from exc
