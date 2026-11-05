"""Actual clean-installed wheel CLI checks from outside the checkout import path."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", required=True)
    parser.add_argument("--wheel", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    python, wheel = str(Path(args.python).resolve()), str(Path(args.wheel).resolve())
    output = Path(tempfile.mkdtemp(prefix="b2-evidence-", dir=root / ".local"))

    def invoke(arguments, expected):
        result = subprocess.run([python, *arguments], cwd=output, capture_output=True, text=True, timeout=20)
        assert result.returncode == expected, f"Unexpected exit {result.returncode}: {result.stdout} {result.stderr}"
        return result

    invoke(["-c", "import importlib.util,workloads; assert importlib.util.find_spec('django') is None; "
            "assert 'site-packages' in workloads.__file__"], 0)
    manifest = output / "manifest.json"
    invoke(["-m", "workloads", "manifest", "--wheel", wheel, "--header-bytes", "2", "--output", str(manifest)], 0)
    digest = hashlib.sha256(Path(wheel).read_bytes()).hexdigest()
    assert json.loads(manifest.read_text())["plugin_package_sha256"] == digest
    fixtures = [("pass", "actual-pass.hex", 0, "PASS"), ("mismatch", "actual-mismatch.hex", 1, "FAIL"),
                ("missing", "actual-missing.hex", 1, "FAIL"), ("extra", "actual-extra.hex", 1, "FAIL"),
                ("insertion", "actual-leading-insertion.hex", 1, "FAIL"), ("invalid", "actual-invalid.hex", 2, "ERROR"),
                ("empty", "actual-empty.hex", 2, "ERROR")]
    reports = {}
    for name, actual, exit_code, outcome in fixtures:
        arguments = ["-m", "workloads", "compare", "--manifest", str(manifest), "--wheel", wheel,
                     "--expected", str(root / "examples/can/expected-header.hex"),
                     "--actual", str(root / "examples/can" / actual), "--header-bytes", "2", "--output-dir", str(output / name)]
        invoke(arguments, exit_code)
        report = json.loads((output / name / "report.json").read_text())
        assert report["outcome"] == outcome
        assert report["plugin_package_sha256"] == digest
        assert (output / name / "report.txt").read_text().startswith(outcome)
        reports[name] = report
        if name == "pass":
            before = (output / name / "report.json").read_bytes()
            invoke(arguments, 2)  # Existing directory must remain untouched.
            assert (output / name / "report.json").read_bytes() == before
            arguments[-1] = str(output / "pass-repeat")
            invoke(arguments, 0)
            assert (output / "pass-repeat/report.json").read_bytes() == before
            arguments[arguments.index("--header-bytes") + 1] = "0"
            arguments[-1] = str(output / "forbidden-header")
            invoke(arguments, 2)
            assert not (output / "forbidden-header").exists()
        print(f"PASS actual installed CLI: {name} -> {outcome}, exit {exit_code}")
    assert reports["mismatch"]["details"][0]["offset"] == 2
    assert reports["missing"]["summary"]["missing_bytes"] == 1
    assert reports["extra"]["summary"]["extra_bytes"] == 1
    assert reports["insertion"]["summary"]["overlap_mismatches"] == 4
    assert reports["insertion"]["summary"]["extra_bytes"] == 1
    print("PASS Django-free installed imports; matching artifact; byte-identical report replay; existing-output preservation; header-override denial.")
    print(f"Actual wheel SHA-256: {digest}")
    print(f"Reports retained privately under: {output.name}")


if __name__ == "__main__":
    main()
