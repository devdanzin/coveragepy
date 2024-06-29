"""
slowtests.py - Identify and classify the execution time of test files in a Python package.

This script runs the test suite of a specified Python package using coverage and pytest,
then classifies each test file as fast, medium, or slow based on their execution times.

Usage:
    python slowtests.py [options]

Options:
    -d, --directory     The directory of the Python package to run tests on. Defaults to the current directory.
    -f, --fast          Threshold for fast tests in seconds. Defaults to 45 seconds.
    -t, --timeout       Timeout for tests in seconds. Defaults to 120 seconds.

Dependencies:
    - pytest
    - coverage
    - All dependencies required by the Python package to run its test suite must be installed.

Classification thresholds:
    - Fast: Execution time less than the specified fast threshold.
    - Medium: Execution time between the fast threshold and timeout.
    - Slow: Execution time more than the timeout or times out after the specified timeout.

The script collects the execution times of the tests and prints out the classification results,
including the slowest tests per test file.
It also identifies tests that fail or raise errors during execution.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any
import optparse

import pytest


class PathCollector:
    """Records the paths of test items during pytest collection."""
    def __init__(self) -> None:
        self.paths = set()

    def pytest_collection_modifyitems(self, items: list[pytest.Item]) -> None:
        """Modify the test collection to collect paths of test items."""
        for item in items:
            self.paths.add(Path(item.path))


def collect_test_paths(directory: str) -> PathCollector:
    """Collect test file paths from the specified directory."""
    path_collector = PathCollector()
    pytest.main(["--collect-only", "-q", directory], plugins=[path_collector])
    return path_collector


def run_test(item: Path, timeout: int = 120) -> tuple[int | None, float | int, str | None]:
    """Run a single test file and returns its execution time and individual test durations."""
    start = time.perf_counter()
    try:
        result = subprocess.run(
            ["coverage", "run", "-m", "pytest", "-v", "--durations=20", str(item)],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
        runtime = time.perf_counter() - start
        output = result.stdout.decode()
        return result.returncode, runtime, output
    except subprocess.TimeoutExpired:
        return None, timeout, None


def parse_durations(output: str) -> list[dict[str, str | float]]:
    """Parse the durations of the individual tests from the pytest output."""
    durations = []
    for line in output.splitlines():
        if "s" in line and "::" in line:
            parts = line.split()
            time_str = parts[0].rstrip("s")
            try:
                duration = float(time_str)
                test_name = parts[-1]
                durations.append({"test_name": test_name, "duration": duration})
            except ValueError:
                continue
    return durations


def categorize_tests(
    paths: list[Path], fast_threshold: int = 45, timeout: int = 120
) -> dict[str, Any]:
    """Categorize test files."""
    categories = {
        "fast": {},
        "medium": {},
        "slow": [],
        "failures": [],
        "slowest_tests": {},
    }

    for item in sorted(paths):
        returncode, runtime, output = run_test(item, timeout)

        if returncode is None:
            print(f"{item} is slow.")
            categories["slow"].append(item)
        elif returncode != 0:
            print(f"Error running {item}!")
            print(output)
            categories["failures"].append(item)
        else:
            if runtime < fast_threshold:
                print(f"{item} is fast: {runtime:.3f}s.")
                categories["fast"][item] = runtime
            else:
                print(f"{item} is medium: {runtime:.3f}s.")
                categories["medium"][item] = runtime

            slowest_tests = parse_durations(output)
            if slowest_tests:
                categories["slowest_tests"][item] = slowest_tests

    return categories


def print_times(tests: dict[Path, float], label: str) -> None:
    """Print the execution times of the test files."""
    print(f"\n# {label} tests ({sum(tests.values()):.2f} seconds):")
    for path, runtime in sorted(tests.items(), key=lambda x: x[1]):
        print(f"{path.name}: {runtime:.3f}")


def print_slowest_tests(slowest_tests: dict[Path, list[dict[str, Any]]]) -> None:
    """Print the slowest test files."""
    print("\n# Slowest individual tests per file:")
    for path, tests in slowest_tests.items():
        print(f"\n{path.name}:")
        for test in sorted(tests, key=lambda x: x["duration"], reverse=True):
            print(f"  {test['test_name']}: {test['duration']:.3f}s")


def main():
    """Main function to execute the test suite and classify the test files."""
    parser = optparse.OptionParser()
    parser.add_option(
        "-d", "--directory",
        dest="directory",
        default=".",
        help="The directory of the Python package to run tests on. Defaults to the current directory."
    )
    parser.add_option(
        "-f", "--fast",
        dest="fast_threshold",
        type="int",
        default=45,
        help="Threshold for fast tests in seconds. Defaults to 45 seconds."
    )
    parser.add_option(
        "-t", "--timeout",
        dest="timeout",
        type="int",
        default=120,
        help="Timeout for tests in seconds. Defaults to 120 seconds."
    )

    options, args = parser.parse_args()

    fast_threshold = options.fast_threshold
    timeout = options.timeout

    directory = options.directory
    print(f"Collecting tests from {Path(directory).resolve()}")

    path_collector = collect_test_paths(directory)
    print(f"Found {len(path_collector.paths)} test files.")

    categories = categorize_tests(list(path_collector.paths), fast_threshold, timeout)

    if categories["fast"]:
        print_times(categories["fast"], "Fast")
    if categories["medium"]:
        print_times(categories["medium"], "Medium")
    if categories["slow"]:
        print(f"# Slow tests:\n{'\n'.join(x.name for x in categories['slow'])}")
    if categories["failures"]:
        print(f"# Tests that fail/error:\n{'\n'.join(x.name for x in categories['failures'])}")
    if categories["slowest_tests"]:
        print_slowest_tests(categories["slowest_tests"])

    if categories["fast"]:
        print("\nSelect fast tests with:")
        print(f'-k "({" or ".join(x.name for x in categories["fast"])})"')
    if categories["medium"]:
        print("\nSelect medium tests with:")
        print(f'-k "({" or ".join(x.name for x in categories["medium"])})"')
    if categories["slow"]:
        print("\nDeselect slow tests with:")
        print(f'-k "not ({" or ".join(x.name for x in categories["slow"])})"')
    if categories["failures"]:
        print("\nDeselect failing/erroring tests with:")
        print(f'-k "not ({" or ".join(x.name for x in categories["failures"])})"')


if __name__ == "__main__":
    main()
