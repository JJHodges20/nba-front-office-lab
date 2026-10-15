"""Server layer: the lab's HTTP API, a FastAPI app (decision 0019).

It validates what comes in and formats what services return; it computes nothing, as no
interface does. May import: domain, config, pipelines, services, and the assistant through
``front_office.assistant.api`` alone.
"""
