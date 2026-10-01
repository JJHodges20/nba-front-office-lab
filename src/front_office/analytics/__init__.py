"""Analytics layer: every calculation the lab performs.

Pure functions over frames. This layer owns the formulas: the user interface displays
results and later stages (value, fit, optimisation) consume them, but none of them
re-derive a metric. May import: domain.
"""
