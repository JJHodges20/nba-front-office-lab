"""Storage layer: the database schema and the repositories that read and write it.

Tables are built from the domain data contracts. Other layers never write SQL; they call
a repository. May import: domain, config.
"""
