#!/usr/bin/env python3
"""
StockOS — QA Master Test Runner
Usage:
    python tests/run_all.py            # run all tests
    python tests/run_all.py unit       # only unit tests
    python tests/run_all.py integration
    python tests/run_all.py frontend
    python tests/run_all.py -v         # verbose mode
    python tests/run_all.py -x         # stop on first failure
"""
import sys
import os
import subprocess
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SUITES = {
    "unit":        os.path.join(ROOT, "tests", "unit"),
    "integration": os.path.join(ROOT, "tests", "integration"),
    "frontend":    os.path.join(ROOT, "tests", "frontend"),
}

COLORS = {
    "green":  "\033[92m",
    "red":    "\033[91m",
    "yellow": "\033[93m",
    "cyan":   "\033[96m",
    "bold":   "\033[1m",
    "reset":  "\033[0m",
}


def c(color, text):
    return COLORS[color] + str(text) + COLORS["reset"]


def run_suite(name, path, extra_args):
    print(f"\n{c('bold', '─' * 60)}")
    print(f"{c('cyan', f'  Suite: {name.upper()}')}  →  {path}")
    print(c('bold', '─' * 60))

    cmd = [
        sys.executable, "-m", "pytest",
        path,
        "--tb=short",
        "-q",
    ] + extra_args

    env = os.environ.copy()
    env["PYTHONPATH"] = ROOT
    env["FLASK_ENV"] = "testing"
    env.pop("DATABASE_URL", None)
    env.pop("DATABASE", None)

    t0 = time.time()
    result = subprocess.run(cmd, cwd=ROOT, env=env)
    elapsed = time.time() - t0

    status = c("green", "PASSED") if result.returncode == 0 else c("red", "FAILED")
    print(f"\n  {c('bold', name.upper())} → {status}  ({elapsed:.1f}s)")
    return result.returncode


def main():
    args = sys.argv[1:]
    verbose = "-v" in args
    stop_on_fail = "-x" in args
    extra_args = []
    if verbose:
        extra_args.append("-v")
    if stop_on_fail:
        extra_args.append("-x")

    # Determine which suites to run
    suite_keys = [a for a in args if a in SUITES]
    if not suite_keys:
        suite_keys = list(SUITES.keys())

    print(f"\n{c('bold', '=' * 60)}")
    print(f"{c('bold', '  StockOS — QA Test Runner')}")
    print(f"{c('bold', '=' * 60)}")
    print(f"  Suites : {', '.join(suite_keys)}")
    print(f"  Root   : {ROOT}")

    # Check pytest is available
    try:
        subprocess.run([sys.executable, "-m", "pytest", "--version"],
                       capture_output=True, check=True)
    except subprocess.CalledProcessError:
        print(c("red", "\npytest not found — run: pip install pytest --break-system-packages"))
        sys.exit(1)

    results = {}
    total_start = time.time()
    for key in suite_keys:
        rc = run_suite(key, SUITES[key], extra_args)
        results[key] = rc
        if stop_on_fail and rc != 0:
            break

    total_elapsed = time.time() - total_start

    print(f"\n{c('bold', '=' * 60)}")
    print(f"{c('bold', '  RESULTS')}")
    print(c('bold', '─' * 60))
    all_passed = True
    for key, rc in results.items():
        status = c("green", "✓ PASSED") if rc == 0 else c("red", "✗ FAILED")
        print(f"  {key:<15} {status}")
        if rc != 0:
            all_passed = False

    print(c('bold', '─' * 60))
    overall = c("green", "ALL SUITES PASSED") if all_passed else c("red", "SOME SUITES FAILED")
    print(f"  Overall: {overall}  ({total_elapsed:.1f}s)")
    print(c('bold', '=' * 60) + "\n")

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
