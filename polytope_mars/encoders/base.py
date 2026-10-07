"""The output encoder protocol.

An encoder turns the block stream of one request (:mod:`polytope_mars.blocks`) into bytes.
Encoders are implemented structurally (no subclassing needed), e.g. ``covjsonkit.stream.CovjsonStreamEncoder``.
One encoder instance encodes exactly one request: ``begin`` once, ``encode`` per block, ``end`` once.
Any of the three may return ``b""``.
"""

from __future__ import annotations

from typing import Protocol, Union, runtime_checkable

from ..blocks import CoordsBlock, GroupEnd, RequestHeader, ValuesBlock

__all__ = ["Block", "Encoder"]

Block = Union[CoordsBlock, ValuesBlock, GroupEnd]


@runtime_checkable
class Encoder(Protocol):
    #: MIME type of the produced document, e.g. "application/prs.coverage+json"
    content_type: str
    #: file extension without the dot, e.g. "covjson"
    file_extension: str

    def begin(self, header: RequestHeader) -> bytes:
        ...

    def encode(self, block: Block) -> bytes:
        ...

    def end(self) -> bytes:
        ...
