"""Exploration helpers for the Analytics Lab.

The workbench may not import analytics, and must not compute a statistic itself. What it
needs to describe a chart - how strongly two metrics move together - it asks for here.
"""

from __future__ import annotations

from front_office.analytics.relationships import MIN_SAMPLE, Relationship, relationship

__all__ = ["MIN_SAMPLE", "Relationship", "relationship"]
