# Licensed under the Apache License: http://www.apache.org/licenses/LICENSE-2.0
# For details: https://github.com/nedbat/coveragepy/blob/master/NOTICE.txt

"""Json reporting for coverage.py"""

from __future__ import annotations

import datetime
import json
import sys

from typing import Any, IO, Iterable, TYPE_CHECKING

from coverage import __version__
from coverage.report_core import get_analysis_to_report
from coverage.results import Analysis, Numbers
from coverage.types import TMorf, TLineNo

if TYPE_CHECKING:
    from coverage import Coverage
    from coverage.data import CoverageData
    from coverage.plugin import FileReporter


# "Version 1" had no format number at all.
# 2: add the meta.format field.
FORMAT_VERSION = 2

class JsonReporter:
    """A reporter for writing JSON coverage results."""

    report_type = "JSON report"

    def __init__(self, coverage: Coverage) -> None:
        self.coverage = coverage
        self.config = self.coverage.config
        self.total = Numbers(self.config.precision)
        self.report_data: dict[str, Any] = {}

    def report(self, morfs: Iterable[TMorf] | None, outfile: IO[str]) -> float:
        """Generate a json report for `morfs`.

        `morfs` is a list of modules or file names.

        `outfile` is a file object to write the json to.

        """
        outfile = outfile or sys.stdout
        coverage_data = self.coverage.get_data()
        coverage_data.set_query_contexts(self.config.report_contexts)
        self.report_data["meta"] = {
            "format": FORMAT_VERSION,
            "version": __version__,
            "timestamp": datetime.datetime.now().isoformat(),
            "branch_coverage": coverage_data.has_arcs(),
            "show_contexts": self.config.json_show_contexts,
        }

        measured_files = {}
        for file_reporter, analysis in get_analysis_to_report(self.coverage, morfs):
            measured_files[file_reporter.relative_filename()] = self.report_one_file(
                coverage_data,
                analysis,
                file_reporter,
            )

        self.report_data["files"] = measured_files

        self.report_data["totals"] = {
            "covered_lines": self.total.n_executed,
            "num_statements": self.total.n_statements,
            "percent_covered": self.total.pc_covered,
            "percent_covered_display": self.total.pc_covered_str,
            "missing_lines": self.total.n_missing,
            "excluded_lines": self.total.n_excluded,
        }

        if coverage_data.has_arcs():
            self.report_data["totals"].update({
                "num_branches": self.total.n_branches,
                "num_partial_branches": self.total.n_partial_branches,
                "covered_branches": self.total.n_executed_branches,
                "missing_branches": self.total.n_missing_branches,
            })

        json.dump(
            self.report_data,
            outfile,
            indent=(4 if self.config.json_pretty_print else None),
        )

        return self.total.n_statements and self.total.pc_covered

    def report_one_file(
        self, coverage_data: CoverageData, analysis: Analysis, file_reporter: FileReporter
    ) -> dict[str, Any]:
        """Extract the relevant report data for a single file."""
        nums = analysis.numbers
        self.total += nums
        summary = {
            "covered_lines": nums.n_executed,
            "num_statements": nums.n_statements,
            "percent_covered": nums.pc_covered,
            "percent_covered_display": nums.pc_covered_str,
            "missing_lines": nums.n_missing,
            "excluded_lines": nums.n_excluded,
        }
        reported_file: dict[str, Any] = {
            "executed_lines": sorted(analysis.executed),
            "summary": summary,
            "missing_lines": sorted(analysis.missing),
            "excluded_lines": sorted(analysis.excluded),
        }
        if self.config.json_show_contexts:
            reported_file["contexts"] = coverage_data.contexts_by_lineno(analysis.filename)
        if coverage_data.has_arcs():
            summary.update({
                "num_branches": nums.n_branches,
                "num_partial_branches": nums.n_partial_branches,
                "covered_branches": nums.n_executed_branches,
                "missing_branches": nums.n_missing_branches,
            })
            reported_file["executed_branches"] = list(
                _convert_branch_arcs(analysis.executed_branch_arcs()),
            )
            reported_file["missing_branches"] = list(
                _convert_branch_arcs(analysis.missing_branch_arcs()),
            )
        report_on = {"class": self.config.json_classes, "function": self.config.json_functions}
        if not any(report_on.values()):
            return reported_file

        for region in file_reporter.code_regions():
            if not report_on[region.kind]:
                continue
            elif region.kind not in reported_file:
                reported_file[region.kind] = {}
            num_lines = len(file_reporter.source().splitlines())
            outside_lines = set(range(1, num_lines + 1))
            outside_lines -= region.lines
            narrowed_analysis = analysis.narrow(region.lines)
            narrowed_nums = narrowed_analysis.numbers
            narrowed_summary = {
                "covered_lines": narrowed_nums.n_executed,
                "num_statements": narrowed_nums.n_statements,
                "percent_covered": narrowed_nums.pc_covered,
                "percent_covered_display": narrowed_nums.pc_covered_str,
                "missing_lines": narrowed_nums.n_missing,
                "excluded_lines": narrowed_nums.n_excluded,
            }
            reported_file[region.kind][region.name] = {
                "executed_lines": sorted(narrowed_analysis.executed),
                "summary": narrowed_summary,
                "missing_lines": sorted(narrowed_analysis.missing),
                "excluded_lines": sorted(narrowed_analysis.excluded),
            }
            if self.config.json_show_contexts:
                contexts = coverage_data.contexts_by_lineno(narrowed_analysis.filename)
                reported_file[region.kind][region.name]["contexts"] = contexts
            if coverage_data.has_arcs():
                narrowed_summary.update({
                    "num_branches": narrowed_nums.n_branches,
                    "num_partial_branches": narrowed_nums.n_partial_branches,
                    "covered_branches": narrowed_nums.n_executed_branches,
                    "missing_branches": narrowed_nums.n_missing_branches,
                })
                reported_file[region.kind][region.name]["executed_branches"] = list(
                    _convert_branch_arcs(narrowed_analysis.executed_branch_arcs()),
                )
                reported_file[region.kind][region.name]["missing_branches"] = list(
                    _convert_branch_arcs(narrowed_analysis.missing_branch_arcs()),
                )
        return reported_file


def _convert_branch_arcs(
    branch_arcs: dict[TLineNo, list[TLineNo]],
) -> Iterable[tuple[TLineNo, TLineNo]]:
    """Convert branch arcs to a list of two-element tuples."""
    for source, targets in branch_arcs.items():
        for target in targets:
            yield source, target
