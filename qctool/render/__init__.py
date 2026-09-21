"""Chặng render: testcase IR → file theo template của team."""

from .excel import COLUMNS, render
from .results import fill_results

__all__ = ["COLUMNS", "render", "fill_results"]
