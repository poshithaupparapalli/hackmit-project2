"""Workflow modules, auto-discovered and registered on server startup.

Each module exposes a `register()` that adds its workflowKey to
`agent.runner.WORKFLOWS`. See `agent.runner.discover_workflows()`.
"""
