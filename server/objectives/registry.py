"""Objective registry.

A tiny registry decouples callers ("give me the claim_status objective") from
concrete classes, so new objectives self-register via ``@register_objective``.
"""

from __future__ import annotations

from server.objectives.base import CallObjective

_REGISTRY: dict[str, type[CallObjective]] = {}


def register_objective(cls: type[CallObjective]) -> type[CallObjective]:
    """Class decorator that registers an objective under ``cls.name``."""
    if not getattr(cls, "name", None) or cls.name == "base":
        raise ValueError(f"Objective {cls!r} must define a unique 'name'.")
    _REGISTRY[cls.name] = cls
    return cls


def get_objective(name: str) -> CallObjective:
    if name not in _REGISTRY:
        raise KeyError(
            f"Unknown objective {name!r}. Available: {sorted(_REGISTRY)}"
        )
    return _REGISTRY[name]()


def available_objectives() -> list[str]:
    return sorted(_REGISTRY)
