"""The output encoder protocol.

An encoder turns the block stream of one request (:mod:`polytope_mars.blocks`) into bytes.
Encoders are implemented structurally (no subclassing needed), e.g. ``covjsonkit.stream.CovjsonStreamEncoder``.
One encoder instance encodes exactly one request: ``begin`` once, ``encode_iter`` per block, ``end`` once.
Any of them may yield or return ``b""``.
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

    def encode_iter(self, block: Block) -> Iterator[bytes]:
        """The block's bytes in fragments whose size does not grow with the block.

        covjsonkit bounds a fragment by ``max_fragment_bytes`` (8 MiB by default), which is what keeps the
        encoder's memory independent of the request size.  The iterator must be consumed completely and in
        order before the next block is encoded: the encoder's state advances with it.
        """
        ...

    def end(self) -> bytes:
        ...
