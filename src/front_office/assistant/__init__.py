"""Assistant layer: the AI research assistant, on a language model running on this machine.

The outermost layer, beside ``interfaces`` (decision 0018). It turns a question into calls
to typed, allowlisted tools over the services, and answers from what they return. It may
import domain, config, services, and of providers and pipelines only the modules named in
``tests/architecture/test_layer_boundaries.py``. The workbench reaches it through
``front_office.assistant.api`` alone. Nothing here imports the package root eagerly:
``import front_office.assistant`` stays cheap.
"""
