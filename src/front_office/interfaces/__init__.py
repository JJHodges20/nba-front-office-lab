"""Interface layer: command-line entry points.

Thin by design: parse arguments, call a pipeline or a service, print the result.
May import: domain, config, pipelines, services.
"""
