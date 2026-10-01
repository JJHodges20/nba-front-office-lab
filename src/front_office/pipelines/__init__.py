"""Pipeline layer: orchestration of provider -> raw store -> processing -> storage.

The only layer that sees the whole ingestion path. May import: domain, config,
providers, rawstore, processing, storage, quality.
"""
