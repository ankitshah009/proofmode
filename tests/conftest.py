"""Shared fixtures for the ProofMode test suite.

Everything here is function-scoped or pure, so tests stay independent under pytest-xdist.
"""

import struct
import zlib

import pytest

from proofmode.models import Source

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

# Official facts of the fictional organisation used by the built-in example.
EXAMPLE_FACTS = (
    "Tidewater Cloud credits do not expire.",
    "Tidewater Cloud never charges a reactivation fee.",
    "Payments are accepted by card or bank transfer only; gift cards are never accepted.",
    "Official messages are sent only from tidewater.example and link only to tidewater.example.",
    "Support is available 24 hours a day, 7 days a week.",
)


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(tag + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)


def make_png(width: int = 1, height: int = 1) -> bytes:
    """Build a valid solid-red RGB PNG using only the standard library."""
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    scanline = b"\x00" + b"\xff\x00\x00" * width
    raw = scanline * height
    return (
        PNG_SIGNATURE
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(raw))
        + _png_chunk(b"IEND", b"")
    )


@pytest.fixture
def png_bytes() -> bytes:
    return make_png()


@pytest.fixture
def example_sources() -> list[Source]:
    return [Source(id=f"S{index}", text=text) for index, text in enumerate(EXAMPLE_FACTS, start=1)]


@pytest.fixture(autouse=True)
def _isolate_model_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep every test away from the real API unless it opts in explicitly."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("PROOFMODE_MOCK", raising=False)
    monkeypatch.delenv("PROOFMODE_MODEL", raising=False)
    monkeypatch.delenv("PROOFMODE_USER_ID", raising=False)
