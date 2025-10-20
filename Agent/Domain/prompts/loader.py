# Agent/Domain/prompts/loader.py
from __future__ import annotations
import importlib
import logging
import pkgutil
from types import ModuleType

_LOG = logging.getLogger(__name__)
_LOADED = False

def load_all_prompts(package_name: str = "Agent.Domain.prompts.prompt_templates") -> None:
    global _LOADED
    if _LOADED:
        return
    pkg = importlib.import_module(package_name)
    # Walk leaf modules only; skip private and the registry/loader modules
    for m in pkgutil.walk_packages(pkg.__path__, pkg.__name__ + "."):
        name = m.name
        base = name.rsplit(".", 1)[-1]
        if m.ispkg or base.startswith("_") or base in {"registry", "loader", "__init__"}:
            continue
        try:
            importlib.import_module(name)  # triggers register_prompt side effects
        except Exception as e:
            _LOG.exception("Failed to import prompt module %s: %s", name, e)
    _LOADED = True
