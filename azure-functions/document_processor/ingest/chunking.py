"""
Chunking stage — splits extracted text into overlapping word-window chunks.

Pure function, no I/O or SDK dependency — trivially unit-testable.
"""


def chunk_text(text: str, chunk_size: int = 512, overlap: int = 64) -> list[dict]:
    """
    Splits a long document into smaller overlapping pieces.

    Like cutting a long book into short chapters that each overlap a little with
    the next one — so no sentence gets cut off awkwardly at a boundary.
    """
    words = text.split()
    chunks = []
    step = chunk_size - overlap

    for i in range(0, len(words), step):
        chunk_words = words[i : i + chunk_size]
        piece = " ".join(chunk_words)
        if not piece.strip():
            continue
        chunks.append(
            {
                "chunk_index": len(chunks),
                "text": piece,
                "word_start": i,
                "word_end": i + len(chunk_words),
            }
        )

    return chunks
