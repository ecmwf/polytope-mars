"""The output encoder protocol.

An encoder turns the block stream of one request (:mod:`polytope_mars.blocks`) into bytes.
Encoders are implemented structurally (no subclassing needed), e.g. ``covjsonkit.stream.CovjsonStreamEncoder``.
One encoder instance encodes exactly one request: ``begin`` once, ``encode`` per block, ``end`` once.
Any of the three may return ``b""``.
"""

from __future__ import annotations

from typing import Iterator, Protocol, Union, runtime_checkable

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


@runtime_checkable
class FragmentingEncoder(Encoder, Protocol):
    """An :class:`Encoder` that can hand a block's bytes over in bounded fragments.

    ``encode_iter(block)`` yields the same bytes as ``encode(block)`` would return, split into pieces whose size
    does not grow with the block (covjsonkit: ``max_fragment_bytes``, default 8 MiB). The extractor prefers it
    when present; the iterator must be consumed completely and in order before the next block is encoded.
    """

    def encode_iter(self, block: Block) -> Iterator[bytes]:
        ...
