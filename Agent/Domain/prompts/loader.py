# Agent/Domain/prompts/loader.py
from __future__ import annotations
import importlib
import logging
import pkgutil
from pathlib import Path
import re

from Agent.Domain.prompts.registry import PromptSpec, REGISTRY

_LOG = logging.getLogger(__name__)
_LOADED = False

# simple heuristic: variables are things inside {...}
_VAR_RE = re.compile(r"{([a-zA-Z_][a-zA-Z0-9_]*)}")


def _infer_required_vars(template: str) -> set[str]:
    return set(_VAR_RE.findall(template))


def load_all_prompts(
    package_name: str = "Agent.Domain.prompts.prompt_templates",
) -> None:
    """
    Recursively import all prompt template modules and register them.

    Directory convention:
      prompt_templates/<id>/<version>.py

    - <id>      = prompt id (folder name)
    - <version> = 'v1', 'v2', ... (filename without .py)

    Each module contains ONLY a top-level string literal; we use
    the module's __doc__ as the template string.
    """
    global _LOADED
    if _LOADED:
        return

    pkg = importlib.import_module(package_name)
    base_dir = Path(pkg.__file__).parent

    for module_info in pkgutil.walk_packages(pkg.__path__, pkg.__name__ + "."):
        # skip packages; we only want leaf modules (the v1.py files)
        if module_info.ispkg:
            continue

        module_name = module_info.name
        leaf = module_name.rsplit(".", 1)[-1]
        if leaf.startswith("_") or leaf in {"registry", "loader", "__init__"}:
            continue

        try:
            module = importlib.import_module(module_name)
        except Exception:
            _LOG.exception("Failed to import prompt module %s", module_name)
            continue

        # Use module docstring as template
        template = (module.__doc__ or "").strip()
        if not template:
            _LOG.warning("Prompt module %s has empty docstring; skipping", module_name)
            continue

        module_file = getattr(module, "__file__", None)
        if not module_file:
            _LOG.warning("Prompt module %s has no __file__; skipping", module_name)
            continue

        try:
            rel = Path(module_file).relative_to(base_dir)
        except ValueError:
            _LOG.warning(
                "Prompt module %s is not inside %s; skipping",
                module_name,
                base_dir,
            )
            continue

        # Expect: <id>/<version>.py  →  parts[-2] = id, stem = 'v1'
        if len(rel.parts) < 2:
            _LOG.warning(
                "Prompt module %s is not under '<id>/<version>.py'; skipping",
                module_name,
            )
            continue

        prompt_id = rel.parts[-2]
        version = rel.stem  # e.g. 'v1', 'v2', 'v3'

        spec = PromptSpec(
            id=prompt_id,
            kind="system",  # adjust if you need other kinds
            template=template,
            required_vars=_infer_required_vars(template),
            version=version,
            json_mode=False,
        )

        try:
            REGISTRY.register(spec)
        except KeyError:
            _LOG.exception(
                "Duplicate prompt %r (version %r) in module %s",
                prompt_id,
                version,
                module_name,
            )

    _LOADED = True

