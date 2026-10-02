"""Modeling layer: estimates fitted to the lab's own data and tested out of sample.

Analytics computes what happened. A model here says what it is *worth*, or what to
expect next, and must earn that by predicting seasons it was not shown better than a
simpler method does. Pure functions over frames, like analytics: nothing in this layer
reads a file or a database. May import: domain, analytics.
"""
