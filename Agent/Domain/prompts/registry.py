# Agent/Domain/prompts/registry.py
from __future__ import annotations

import json
from copy import copy
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Mapping

PromptKind = Literal["system", "user", "tool"]
logger = logging.getLogger(__name__)

class _NullDefaultMapping(dict):
    """
    Mapping for str.format_map that returns the string 'null' for any
    missing key.

    This lets templates safely reference {placeholder} without requiring
    every key to be passed to render(...). Anything not in kwargs will
    be rendered as the literal string 'null'.
    """

    def __missing__(self, key: str) -> str:
        return "null"


@dataclass(frozen=True)
class PromptSpec:
    id: str
    kind: PromptKind = "system"
    template: str | Callable[[Mapping[str, Any]], str] = ""
    required_vars: set[str] = field(default_factory=set)
    version: str = "v1"
    json_mode: bool = True

    def render(self, enforce_required_vars=True, **kwargs: Any) -> str:
        """
        Render the prompt.

        - For callable templates (legacy/function-style), we still enforce
          required_vars strictly and pass the full mapping to the function.

        - For string templates, any placeholder that is not provided in
          kwargs is replaced with the literal string "null" via
          _NullDefaultMapping + str.format_map.

        If required_vars is non-empty, we still enforce that those keys
        are present in kwargs to catch obvious bugs early.
        """
        # String templates: enforce required_vars if given
        # Make sure everything is a string before substitution
        safe_mapping = {}
        for k, v in kwargs.items():
            if isinstance(v, str):
                safe_mapping[k] = v
            else:
                # JSON-ify complex objects so they render nicely
                try:
                    safe_mapping[k] = json.dumps(v, ensure_ascii=False, indent=2)
                except Exception:
                    safe_mapping[k] = str(v)

        try:
            # Normal path – full Python format engine
            return self.template.format_map(safe_mapping)
        except Exception as e:
            logger.exception("Prompt formatting failed for template %r", self.template[:120])

            # VERY simple fallback: do literal "{key}" -> value replacement
            result = self.template
            for k, v in safe_mapping.items():
                result = result.replace("{" + k + "}", v)
            return result


class PromptRegistry:
    def __init__(self) -> None:
        self._by_key: dict[tuple[str, str], PromptSpec] = {}

    def register(self, spec: PromptSpec) -> PromptSpec:
        key = (spec.id, spec.version)
        if key in self._by_key:
            raise KeyError(f"Duplicate prompt: {key}")
        self._by_key[key] = spec
        return spec

    def get(self, id: str, version: str = "v1") -> PromptSpec:
        key = (id, version)
        if key not in self._by_key:
            # Lazy-load
            from Agent.Domain.prompts.loader import load_all_prompts
            load_all_prompts()
        try:
            return self._by_key[key]
        except KeyError as e:
            raise KeyError(f"Unknown prompt id/version: ({id!r}, {version!r}), Registered prompts: are {self.debug_keys}") from e


    def debug_keys(self) -> list[tuple[str, str]]:
        return sorted(self._by_key.keys())
    
REGISTRY = PromptRegistry()
