"""Module registry. Each module is a self-contained package exposing a `meta.MODULE`
descriptor; the app mounts the ones listed in EDGECUTE_ENABLED_MODULES.
"""
import importlib


def load_module(name: str) -> dict:
    """Import `modules.<name>.meta` and return its MODULE descriptor."""
    mod = importlib.import_module(f"app.api_public.modules.{name}.meta")
    return mod.MODULE
