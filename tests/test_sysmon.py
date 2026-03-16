# Licensed under the Apache License: http://www.apache.org/licenses/LICENSE-2.0
# For details: https://github.com/coveragepy/coveragepy/blob/main/NOTICE.txt

"""Tests for SysMonitor's internal state management.

Replay validation of SysMonitor's event processing is now integrated
into every check_coverage() call via CoverageTest._validate_sysmon_replay.
When running under the sysmon core, check_coverage() captures the
monitoring events, replays them through a fresh SysMonitor, and asserts
the results match.  This means every existing test in test_arcs.py,
test_coverage.py, etc. automatically validates the replay machinery.

This file contains targeted lifecycle tests for SysMonitor's state
management that don't go through check_coverage().
"""

from __future__ import annotations

import os

import pytest

from coverage import env
from tests.sysmon_harness import EventCapture, SysMonitorReplay
from coverage.sysmon import SysMonitor


@pytest.mark.skipif(
    not env.PYBEHAVIOR.pep669, reason="sys.monitoring not available"
)
class SysMonitorLifecycleTest:
    """Test SysMonitor's internal state management."""

    def _make_replay(self, source: str = "a = 1\n") -> SysMonitorReplay:
        code = compile(source, "target.py", "exec")
        return SysMonitorReplay(
            filename="target.py", code=code, trace_arcs=False
        )

    def test_activity_flag_starts_false(self) -> None:
        replay = self._make_replay()
        assert replay.monitor.activity() is False
        replay._cleanup()

    def test_activity_flag_set_on_py_start(self) -> None:
        replay = self._make_replay()
        code = compile("a = 1\n", "target.py", "exec")
        replay.monitor.sysmon_py_start(code, 0)
        assert replay.monitor.activity() is True
        replay._cleanup()

    def test_reset_activity(self) -> None:
        replay = self._make_replay()
        replay.monitor._activity = True
        replay.monitor.reset_activity()
        assert replay.monitor.activity() is False
        replay._cleanup()

    def test_code_info_caching(self) -> None:
        """Second PY_START for same code should use cached CodeInfo."""
        replay = self._make_replay()
        code = compile("a = 1\n", "target.py", "exec")
        replay.monitor.sysmon_py_start(code, 0)
        assert id(code) in replay.monitor.code_infos
        info_before = replay.monitor.code_infos[id(code)]
        replay.monitor.sysmon_py_start(code, 0)
        info_after = replay.monitor.code_infos[id(code)]
        assert info_before is info_after
        replay._cleanup()

    def test_non_traced_file_no_data(self) -> None:
        """Files not in should_trace_cache should not be traced."""
        replay = self._make_replay()
        replay.monitor.should_trace_cache.clear()

        from coverage.disposition import FileDisposition

        def should_trace(filename, frame):
            disp = FileDisposition()
            disp.original_filename = filename
            disp.canonical_filename = filename
            disp.source_filename = None
            disp.trace = False
            disp.reason = "test"
            disp.file_tracer = None
            disp.has_dynamic_filename = False
            return disp

        replay.monitor.should_trace = should_trace
        code = compile("a = 1\n", "target.py", "exec")
        replay.monitor.sysmon_py_start(code, 0)
        assert not replay.monitor.data
        replay._cleanup()


@pytest.mark.skipif(
    not env.PYBEHAVIOR.pep669, reason="sys.monitoring not available"
)
class SysMonitorCaptureReplayTest:
    """Test that capture-and-replay produces the same results as a live run.

    These tests run code under real coverage, capture events simultaneously,
    then replay the events through a fresh SysMonitor and compare results.
    This validates the same round-trip that check_coverage() now does
    automatically, but as explicit standalone tests.
    """

    def _capture_replay_compare(
        self, source: str, branch: bool = False
    ) -> None:
        """Run source under coverage + capture, replay, compare."""
        import coverage
        import tempfile

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as f:
            f.write(source)
            tmpfile = f.name

        try:
            capture = EventCapture()
            capture.start(tmpfile)

            cov = coverage.Coverage(branch=branch)
            cov.start()
            try:
                exec(  # noqa: S102
                    compile(source, tmpfile, "exec"),
                    {"__name__": "__main__"},
                )
            finally:
                cov.stop()
                events = capture.stop()

            # Get real data
            data = cov.get_data()
            real_data: set = set()
            for measured_file in data.measured_files():
                if tmpfile in measured_file:
                    if branch:
                        arcs = data.arcs(measured_file)
                        if arcs is not None:
                            real_data = set(arcs)
                    else:
                        file_lines = data.lines(measured_file)
                        if file_lines is not None:
                            real_data = set(file_lines)
                    break

            # Replay
            code = compile(source, tmpfile, "exec")
            replay = SysMonitorReplay(
                filename=tmpfile, code=code, trace_arcs=branch
            )
            replay_data = replay.replay(events)
            replayed = replay_data.get(tmpfile, set())

            assert replayed == real_data, (
                f"Replay mismatch:\n"
                f"  extra:   {sorted(replayed - real_data)}\n"
                f"  missing: {sorted(real_data - replayed)}"
            )
        finally:
            os.unlink(tmpfile)

    def test_simple_lines(self) -> None:
        self._capture_replay_compare("a = 1\nb = 2\nc = 3\n")

    def test_if_branch_lines(self) -> None:
        self._capture_replay_compare(
            "x = 1\nif x > 0:\n    y = 3\nelse:\n    y = 5\nz = 6\n"
        )

    @pytest.mark.skipif(
        not env.PYBEHAVIOR.branch_right_left,
        reason="BRANCH_RIGHT/LEFT not available",
    )
    def test_if_branch_arcs(self) -> None:
        self._capture_replay_compare(
            "x = 1\nif x > 0:\n    y = 3\nelse:\n    y = 5\nz = 6\n",
            branch=True,
        )

    @pytest.mark.skipif(
        not env.PYBEHAVIOR.branch_right_left,
        reason="BRANCH_RIGHT/LEFT not available",
    )
    def test_for_loop_arcs(self) -> None:
        self._capture_replay_compare(
            "total = 0\nfor i in range(5):\n    total += i\nresult = total\n",
            branch=True,
        )

    @pytest.mark.skipif(
        not env.PYBEHAVIOR.branch_right_left,
        reason="BRANCH_RIGHT/LEFT not available",
    )
    def test_generator_arcs(self) -> None:
        self._capture_replay_compare(
            "def gen(n):\n    for i in range(n):\n        yield i\nlist(gen(3))\n",
            branch=True,
        )

    @pytest.mark.skipif(
        not env.PYBEHAVIOR.branch_right_left,
        reason="BRANCH_RIGHT/LEFT not available",
    )
    def test_try_except_arcs(self) -> None:
        self._capture_replay_compare(
            "try:\n    x = 1 / 0\nexcept ZeroDivisionError:\n    x = 0\ny = x\n",
            branch=True,
        )
