"""Call objectives — pluggable definitions of what a call is trying to achieve.

Importing this package registers all built-in objectives so the registry is
populated by a single ``import server.objectives``.
"""

from server.objectives import claim_status  # noqa: F401  (registers objective)
from server.objectives.base import CallObjective, ToolResult
from server.objectives.registry import (
    available_objectives,
    get_objective,
    register_objective,
)

__all__ = [
    "CallObjective",
    "ToolResult",
    "available_objectives",
    "get_objective",
    "register_objective",
]
