"""
Deterministic document chunking.

Splits on whitespace-delimited words (not raw character slicing, so we
never cut a word in half) into fixed-size, overlapping chunks. Purely
deterministic — the same input always produces the same chunks, which
matters for idempotent indexing (see app/services/rag_indexing_service.py).

Chunk size and overlap are in characters, configurable per call; a
trailing remainder shorter than MIN_CHUNK_CHARS is merged into the
previous chunk instead of becoming its own meaningless tiny chunk (unless
it's the only chunk there is).
"""
from dataclasses import dataclass

DEFAULT_CHUNK_SIZE_CHARS = 800
DEFAULT_CHUNK_OVERLAP_CHARS = 150
MIN_CHUNK_CHARS = 200


@dataclass
class Chunk:
    chunk_index: int
    content: str
    char_count: int


def chunk_text(
    text: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE_CHARS,
    overlap: int = DEFAULT_CHUNK_OVERLAP_CHARS,
) -> list[Chunk]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be non-negative and smaller than chunk_size")

    text = text.strip()
    if not text:
        return []

    words = text.split()
    if not words:
        return []

    chunks: list[str] = []
    current_words: list[str] = []
    current_len = 0

    for word in words:
        added_len = len(word) + (1 if current_words else 0)
        if current_words and current_len + added_len > chunk_size:
            chunks.append(" ".join(current_words))
            overlap_words: list[str] = []
            overlap_len = 0
            for w in reversed(current_words):
                w_len = len(w) + (1 if overlap_words else 0)
                if overlap_len + w_len > overlap:
                    break
                overlap_words.insert(0, w)
                overlap_len += w_len
            current_words = overlap_words
            current_len = overlap_len

        current_words.append(word)
        current_len += len(word) + (1 if len(current_words) > 1 else 0)

    if current_words:
        chunks.append(" ".join(current_words))

    if len(chunks) > 1 and len(chunks[-1]) < MIN_CHUNK_CHARS:
        last = chunks.pop()
        chunks[-1] = chunks[-1] + " " + last

    return [Chunk(chunk_index=i, content=c, char_count=len(c)) for i, c in enumerate(chunks)]
