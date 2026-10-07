"""Output encoder registry: the request's top-level ``format`` key selects the encoder."""

from __future__ import annotations

from typing import Callable

from .base import Block, Encoder

__all__ = ["Block", "Encoder", "get_encoder", "supported_formats"]


def _covjson(config) -> Encoder:
    from covjsonkit.stream import CovjsonStreamEncoder

    return CovjsonStreamEncoder(config)


#: format name -> factory(config of that format) -> Encoder
_REGISTRY: dict[str, Callable[..., Encoder]] = {"covjson": _covjson}


def supported_formats() -> tuple[str, ...]:
    return tuple(sorted(_REGISTRY))


def _format_config(config, fmt: str):
    """The ``encoders.<fmt>`` section of a PolytopeMarsConfig (or of a plain dict), as a dict."""
    if config is None:
        return {}
    if isinstance(config, dict):
        encoders = config.get("encoders", config)
    else:
        encoders = getattr(config, "encoders", None)
        dump = getattr(encoders, "model_dump", None)
        encoders = dump() if callable(dump) else {}
    section = encoders.get(fmt) if isinstance(encoders, dict) else None
    dump = getattr(section, "model_dump", None)
    if callable(dump):
        section = dump()
    return dict(section) if isinstance(section, dict) else {}


def get_encoder(format: str, config=None) -> Encoder:
    """A new encoder for ``format`` configured from ``config`` (a PolytopeMarsConfig, its ``encoders``
    section as a dict, or None).  Unknown formats raise ``ValueError``."""
    factory = _REGISTRY.get(format) if isinstance(format, str) else None
    if factory is None:
        raise ValueError(f"Unsupported output format {format!r}; supported formats: {', '.join(supported_formats())}")
    return factory(_format_config(config, format))
