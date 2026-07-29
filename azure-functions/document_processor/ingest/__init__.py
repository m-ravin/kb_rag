"""
Ingestion pipeline stages — each stage is a separate, independently testable module.

  extraction.py    — pulls raw text out of uploaded PDF/DOCX/PPTX files
  chunking.py      — splits extracted text into overlapping chunks
  embedding.py     — turns chunk text into vectors via Azure OpenAI
  vector_store.py  — builds and uploads Azure AI Search documents
  graph.py         — builds the chunk relationship graph in Cosmos Gremlin
  status.py        — writes document processing status updates to MongoDB

function.py (one level up) wires these together behind the blob trigger —
that's the only file that should change when the trigger itself changes.
To fix a specific pipeline step, edit its module here instead.
"""
