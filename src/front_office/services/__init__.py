"""Service layer: the read-side API the workbench and CLI call.

Combines repositories with analytics and hands back display-ready results. The user
interface depends on this layer only. May import: domain, config, storage, analytics,
quality.
"""
