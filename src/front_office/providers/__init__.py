"""Provider layer: adapters that retrieve data from external sources.

An adapter fetches and returns what the source sent, unchanged. It does no cleaning,
renaming or interpretation; that is the processing layer's job. This is the only layer
allowed to talk to the network. May import: domain, config.
"""
