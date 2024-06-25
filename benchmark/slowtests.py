from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

FAST = 45
TIMEOUT = 120


class PathCollector:
    def __init__(self) -> None:
        self.paths = set()

    def pytest_collection_modifyitems(self, items: list[pytest.Item]) -> None:
        for item in items:
            self.paths.add(item.path)


def print_times(tests: dict[Path, float]) -> None:
    for path, runtime in sorted(tests.items(), key=lambda x: x[1]):
        print(f"{path.name}: {runtime:.3f}")


def main():
    path_collector = PathCollector()
    directory = sys.argv[1] if len(sys.argv) > 1 else "."
    print(f"Collecting tests from {Path(directory).resolve()}")
    pytest.main(["--collect-only", "-q", directory], plugins=[path_collector])
    slow = []
    medium = {}
    fast = {}
    failing_error = []
    print(f"Found {len(path_collector.paths)} test files.")
    for item in sorted(path_collector.paths):
        start = time.perf_counter()
        try:
            result = subprocess.run(
                f"coverage run -m pytest -v --durations=20 {item}".split(), check=False,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=TIMEOUT
            )
            if result.returncode != 0:
                print(f"Error running {item}!")
                print(result.stdout.decode())
                failing_error.append(item)
                continue
            runtime = time.perf_counter() - start
            if runtime < FAST:
                print(f"{item} is fast: {runtime}s.")
                fast[item] = runtime
            else:
                print(f"{item} is medium: {runtime}s.")
                medium[item] = runtime
        except subprocess.TimeoutExpired:
            print(f"{item} is slow.")
            slow.append(item)

    if fast:
        print(f"# Fast tests ({sum(fast.values())} seconds):")
        print_times(fast)
    if medium:
        print(f"\n# Medium tests ({sum(medium.values())} seconds):")
        print_times(medium)
    if slow:
        print(f"# Slow tests:\n{'\n'.join(x.name for x in slow)}")
    if failing_error:
        print(f"# Tests that fail/error:\n{'\n'.join(x.name for x in failing_error)}")

    if fast:
        print("\nSelect fast tests with:")
        print(f'-k "({' or '.join(x.name for x in fast)})"')
    if medium:
        print("\nSelect medium tests with:")
        print(f'-k "({' or '.join(x.name for x in medium)})"')
    if slow:
        print("\nDeselect slow tests with:")
        print(f'-k "not ({' or '.join(x.name for x in slow)})"')
    if failing_error:
        print("\nDeselect failing/erroring tests with:")
        print(f'-k "not ({' or '.join(x.name for x in failing_error)})"')


if __name__ == "__main__":
    main()
