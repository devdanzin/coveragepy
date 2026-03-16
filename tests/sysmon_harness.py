# Licensed under the Apache License: http://www.apache.org/licenses/LICENSE-2.0
# For details: https://github.com/coveragepy/coveragepy/blob/main/NOTICE.txt

"""Event capture and replay harness for validating SysMonitor.

This module provides two components:

1. EventCapture: records sys.monitoring events using its own tool_id
   while coverage.py's SysMonitor runs simultaneously on a different
   tool_id.  This captures the real event sequence CPython delivers.

2. SysMonitorReplay: feeds captured events into a fresh SysMonitor
   instance via direct callback calls, then returns the collected data.

Together they enable a round-trip validation: run code under real
coverage, capture the events, replay them through SysMonitor, and
verify the replay produces the same coverage data as the live run.
"""

from __future__ import annotations

import functools
import sys
from types import CodeType
from typing import Any
from unittest.mock import MagicMock

from coverage import env
from coverage.disposition import FileDisposition
from coverage.sysmon import SysMonitor


class EventCapture:
    """Capture sys.monitoring events during a live code execution.

    Uses a separate tool_id (default 2) so it can run alongside
    coverage.py's SysMonitor (tool_id 1 or 3) without interference.

    Does NOT return DISABLE from callbacks — it captures every event,
    not just the first per code/line.
    """

    def __init__(self, tool_id: int = 2) -> None:
        if not hasattr(sys, "monitoring"):
            raise RuntimeError("sys.monitoring not available")
        self.tool_id = tool_id
        self._monitoring = sys.monitoring
        self._events_cls = sys.monitoring.events
        self._has_branch_right_left = hasattr(self._events_cls, "BRANCH_RIGHT")

        self.events: list[dict[str, Any]] = []
        self.target_filename: str | None = None

    def start(self, target_filename: str) -> None:
        """Start capturing events for the given target filename."""
        self.events = []
        self.target_filename = target_filename

        local_events = (
            self._events_cls.PY_RETURN
            | self._events_cls.PY_RESUME
            | self._events_cls.LINE
        )
        if self._has_branch_right_left:
            local_events |= (
                self._events_cls.BRANCH_RIGHT | self._events_cls.BRANCH_LEFT
            )
        self._local_events = local_events

        self._monitoring.use_tool_id(self.tool_id, "sysmon-capture")
        register = functools.partial(
            self._monitoring.register_callback, self.tool_id
        )

        self._monitoring.set_events(
            self.tool_id, self._events_cls.PY_START
        )
        register(self._events_cls.PY_START, self._on_py_start)
        register(self._events_cls.PY_RESUME, self._on_py_resume)
        register(self._events_cls.PY_RETURN, self._on_py_return)
        register(self._events_cls.LINE, self._on_line)
        if self._has_branch_right_left:
            register(self._events_cls.BRANCH_RIGHT, self._on_branch_right)
            register(self._events_cls.BRANCH_LEFT, self._on_branch_left)
        self._monitoring.restart_events()

    def stop(self) -> list[dict[str, Any]]:
        """Stop capturing and return the recorded events."""
        self._monitoring.set_events(self.tool_id, 0)
        self._monitoring.free_tool_id(self.tool_id)
        return self.events

    def _record(
        self,
        event_type: str,
        code: CodeType,
        offset: int = 0,
        line: int | None = None,
        dest: int | None = None,
    ) -> None:
        if code.co_filename != self.target_filename:
            return
        self.events.append({
            "type": event_type,
            "code_name": code.co_name,
            "code_filename": code.co_filename,
            "code_firstlineno": code.co_firstlineno,
            "offset": offset,
            "line": line,
            "dest": dest,
        })

    def _on_py_start(self, code: CodeType, offset: int) -> None:
        self._record("PY_START", code, offset=offset)
        if code.co_filename == self.target_filename:
            self._monitoring.set_local_events(
                self.tool_id, code, self._local_events
            )

    def _on_py_resume(self, code: CodeType, offset: int) -> None:
        self._record("PY_RESUME", code, offset=offset)

    def _on_py_return(self, code: CodeType, offset: int, retval: object) -> None:
        self._record("PY_RETURN", code, offset=offset)

    def _on_line(self, code: CodeType, line: int) -> None:
        self._record("LINE", code, line=line)

    def _on_branch_right(self, code: CodeType, offset: int, dest: int) -> None:
        self._record("BRANCH_RIGHT", code, offset=offset, dest=dest)

    def _on_branch_left(self, code: CodeType, offset: int, dest: int) -> None:
        self._record("BRANCH_LEFT", code, offset=offset, dest=dest)


class SysMonitorReplay:
    """Replay captured events through a fresh SysMonitor instance.

    Creates a SysMonitor with stubbed external dependencies, feeds
    events into its callback methods, and returns the collected data.
    The result can be compared against real coverage data to verify
    that replaying produces the same output as a live run.
    """

    def __init__(
        self,
        filename: str,
        code: CodeType,
        trace_arcs: bool = False,
    ) -> None:
        self.filename = filename
        self.trace_arcs = trace_arcs

        # Build code object map from the compiled code
        self.code_map = self._build_code_map(code)

        # Create a SysMonitor with stubs
        self.monitor = SysMonitor(tool_id=1)
        self.monitor.data = {}
        self.monitor.trace_arcs = trace_arcs
        self.monitor.should_trace_cache = {
            filename: self._make_disposition(filename)
        }
        self.monitor.lock_data = lambda: None
        self.monitor.unlock_data = lambda: None
        self.monitor.warn = lambda msg, slug="", once=False: None

        # Patch sys_monitoring to no-ops during replay
        import coverage.sysmon as sysmon_module

        self._orig_sys_monitoring = sysmon_module.sys_monitoring
        mock_monitoring = MagicMock()
        mock_monitoring.DISABLE = None
        sysmon_module.sys_monitoring = mock_monitoring

    def replay(self, events: list[dict[str, Any]]) -> dict[str, set[Any]]:
        """Feed events into SysMonitor's callbacks, return collected data."""
        arc_only_types = {"PY_RETURN", "BRANCH_RIGHT", "BRANCH_LEFT"}

        try:
            for ev in events:
                code = self._resolve_code(ev)
                if code is None:
                    continue

                event_type = ev["type"]

                if not self.trace_arcs and event_type in arc_only_types:
                    continue

                if event_type == "PY_START":
                    self.monitor.sysmon_py_start(code, ev["offset"])
                elif event_type == "LINE":
                    if self.trace_arcs:
                        self.monitor.sysmon_line_arcs(code, ev["line"])
                    else:
                        self.monitor.sysmon_line_lines(code, ev["line"])
                elif event_type == "PY_RETURN":
                    self.monitor.sysmon_py_return(
                        code, ev["offset"], None
                    )
                elif event_type in ("BRANCH_RIGHT", "BRANCH_LEFT"):
                    self.monitor.sysmon_branch_either(
                        code, ev["offset"], ev["dest"]
                    )
        finally:
            self._cleanup()

        return self.monitor.data

    def _cleanup(self) -> None:
        """Restore the original sys_monitoring reference."""
        import coverage.sysmon as sysmon_module

        sysmon_module.sys_monitoring = self._orig_sys_monitoring

    def _build_code_map(self, code: CodeType) -> dict[str, CodeType]:
        """Build a map of (name:firstlineno) -> CodeType."""
        code_map: dict[str, CodeType] = {}
        stack = [code]
        while stack:
            c = stack.pop()
            key = f"{c.co_name}:{c.co_firstlineno}"
            code_map[key] = c
            for const in c.co_consts:
                if isinstance(const, CodeType):
                    stack.append(const)
        return code_map

    def _resolve_code(self, ev: dict[str, Any]) -> CodeType | None:
        """Find the code object matching an event."""
        key = f"{ev['code_name']}:{ev['code_firstlineno']}"
        return self.code_map.get(key)

    @staticmethod
    def _make_disposition(filename: str) -> FileDisposition:
        """Create a FileDisposition that says 'trace this file'."""
        disp = FileDisposition()
        disp.original_filename = filename
        disp.canonical_filename = filename
        disp.source_filename = filename
        disp.trace = True
        disp.reason = ""
        disp.file_tracer = None
        disp.has_dynamic_filename = False
        return disp
