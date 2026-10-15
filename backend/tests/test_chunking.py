"""
Pure unit tests for document chunking — no DB, no network.
"""
import pytest

from app.rag.chunking import MIN_CHUNK_CHARS, chunk_text


# ---------- 1. Document chunking ----------


def test_short_text_produces_a_single_chunk():
    chunks = chunk_text("This is a short abstract about metformin.", chunk_size=800, overlap=150)
    assert len(chunks) == 1
    assert chunks[0].content == "This is a short abstract about metformin."


def test_long_text_is_split_into_multiple_chunks():
    text = ("metformin cardiovascular outcome " * 100).strip()
    chunks = chunk_text(text, chunk_size=500, overlap=100)
    assert len(chunks) > 1
    # All but the last chunk stay within a reasonable margin of chunk_size;
    # the last chunk may run larger since a too-small trailing remainder is
    # deliberately merged into it rather than left as a meaningless fragment.
    for c in chunks[:-1]:
        assert c.char_count <= 600
    assert chunks[-1].char_count <= 900  # generous bound: chunk_size + a merged small remainder


def test_empty_or_whitespace_text_produces_no_chunks():
    assert chunk_text("") == []
    assert chunk_text("   \n\t  ") == []


def test_never_creates_meaninglessly_tiny_trailing_chunks():
    text = ("word " * 210).strip()
    chunks = chunk_text(text, chunk_size=1000, overlap=100)
    for c in chunks[:-1]:
        assert c.char_count >= MIN_CHUNK_CHARS
    if len(chunks) > 1:
        assert chunks[-1].char_count >= MIN_CHUNK_CHARS


# ---------- 2. Chunk ordering ----------


def test_chunk_indices_are_sequential_and_start_at_zero():
    text = ("metformin " * 300).strip()
    chunks = chunk_text(text, chunk_size=400, overlap=50)
    indices = [c.chunk_index for c in chunks]
    assert indices == list(range(len(chunks)))


def test_chunks_preserve_original_word_order():
    words = [f"word{i}" for i in range(200)]
    text = " ".join(words)
    chunks = chunk_text(text, chunk_size=300, overlap=30)
    assert chunks[0].content.split()[0] == "word0"
    assert "word199" in chunks[-1].content


# ---------- Determinism & config ----------


def test_chunking_is_deterministic():
    text = ("metformin reduces cardiovascular risk in adults with type 2 diabetes. " * 20).strip()
    a = chunk_text(text, chunk_size=300, overlap=50)
    b = chunk_text(text, chunk_size=300, overlap=50)
    assert [c.content for c in a] == [c.content for c in b]


def test_chunk_size_and_overlap_are_configurable():
    text = ("metformin " * 500).strip()
    small_chunks = chunk_text(text, chunk_size=200, overlap=20)
    large_chunks = chunk_text(text, chunk_size=2000, overlap=100)
    assert len(small_chunks) > len(large_chunks)


def test_invalid_overlap_configuration_raises():
    with pytest.raises(ValueError):
        chunk_text("some text here", chunk_size=100, overlap=100)
    with pytest.raises(ValueError):
        chunk_text("some text here", chunk_size=100, overlap=150)
    with pytest.raises(ValueError):
        chunk_text("some text here", chunk_size=0, overlap=0)
