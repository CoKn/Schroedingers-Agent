# Agent/Domain/prompts/registry.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, Mapping, Any, Literal, Optional

PromptKind = Literal["system", "user", "tool"]

@dataclass(frozen=True)
class PromptSpec:
    id: str
    kind: PromptKind = "system"
    template: str | Callable[[Mapping[str, Any]], str] = ""
    required_vars: set[str] = field(default_factory=set)
    version: str = "v1"
    json_mode: bool = False

    def render(self, **kwargs) -> str:
        # minimal var checking to catch formatting bugs early
        missing = self.required_vars - set(kwargs)
        if missing:
            raise KeyError(f"Missing vars for prompt '{self.id}': {sorted(missing)}")
        if callable(self.template):
            return self.template(kwargs)
        return self.template.format(**kwargs)

class PromptRegistry:
    def __init__(self):
        self._by_key: dict[tuple[str, str], PromptSpec] = {}

    def register(self, spec: PromptSpec) -> PromptSpec:
        key = (spec.id, spec.version)
        if key in self._by_key:
            raise KeyError(f"Duplicate prompt: {key}")
        self._by_key[key] = spec
        return spec
    
    def get(self, id: str, version: str = "v1") -> PromptSpec:
        return self._by_key[(id, version)]

REGISTRY = PromptRegistry()

def register_prompt(
    id: str,
    *,
    kind: PromptKind = "system",
    required_vars: set[str] | None = None,
    version: str = "v1",
    json_mode: bool = False,
):
    def decorator(template_or_func: str | Callable[[Mapping[str, Any]], str]):
        spec = PromptSpec(
            id=id,
            kind=kind,
            template=template_or_func,
            required_vars=required_vars or set(),
            version=version,
            json_mode=json_mode,
        )
        return REGISTRY.register(spec)
    return decorator
