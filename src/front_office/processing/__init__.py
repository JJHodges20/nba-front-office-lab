"""Processing layer: cleaning and normalisation.

Pure functions that turn raw provider payloads into frames satisfying a data contract.
No network, no database, no configuration lookups: anything a normaliser needs is passed
in as an argument. May import: domain.
"""
