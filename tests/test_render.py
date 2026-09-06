"""Unmeasured paid rows stay the literal «не измерено», never a number."""

from __future__ import annotations

import unittest

from bench.report.coverage import CoverageRow
from bench.report.render import render_markdown


class RenderTests(unittest.TestCase):
    def test_table_headers(self) -> None:
        md = render_markdown(
            [CoverageRow("curl", solved=2, incremental=2, unique=0, total_cells=5)]
        )
        self.assertIn("Провайдер", md)
        self.assertIn("Взял", md)
        self.assertIn("Incremental", md)
        self.assertIn("Unique", md)
        self.assertIn("Решение", md)
        self.assertIn("curl", md)

    def test_unmeasured_row_is_literal_not_a_number(self) -> None:
        rendered = render_markdown(
            [CoverageRow("curl", solved=1, incremental=1, unique=0, total_cells=1)],
            unmeasured=["zenrows"],
        )
        self.assertIn("не измерено", rendered)
        for line in rendered.splitlines():
            if "zenrows" in line:
                self.assertIn("не измерено", line)
                self.assertNotRegex(line, r"\d")

    def test_render_markdown_forwards_threshold(self) -> None:
        row = CoverageRow("x", solved=1, incremental=1, unique=0, total_cells=100)
        kept = render_markdown([row], threshold=0.01)
        self.assertIn("оставить", kept)
        dropped = render_markdown([row], threshold=0.05)
        self.assertIn("исключить", dropped)
        defaulted = render_markdown([row])
        self.assertIn("исключить", defaulted)


if __name__ == "__main__":
    unittest.main()
