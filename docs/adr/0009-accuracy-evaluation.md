# ADR-0009: LLM Accuracy Evaluation — Deferred to v2 (Gap Acknowledged)

**Date**: 2026-05-07
**Status**: proposed
**Deciders**: KB RAG system design

## Context

KB RAG produces answers to user questions by retrieving document chunks and generating responses with GPT-4o. The TDD test suite verifies that the code runs correctly (unit and integration tests), but it does not verify that the answers are accurate, faithful to the source documents, or relevant to the question. In production, two types of failure are invisible without an eval harness: **retrieval failures** (the right document exists but the wrong chunks were returned) and **generation failures** (the correct chunks were retrieved but GPT-4o hallucinated or misrepresented the content).

## Decision

v1 ships without a formal accuracy eval harness. v2 will implement **RAGAS** (Retrieval-Augmented Generation Assessment) as the evaluation framework, measuring four metrics against a curated ground-truth dataset:

| Metric | Measures | Target |
|--------|----------|--------|
| **Faithfulness** | Does the answer contain only claims supported by the retrieved chunks? | > 0.85 |
| **Answer Relevance** | Is the answer relevant to the question asked? | > 0.80 |
| **Context Precision** | Are the retrieved chunks actually useful for answering the question? | > 0.75 |
| **Context Recall** | Does the retrieval surface all chunks needed to answer correctly? | > 0.70 |

## Alternatives Considered

### Alternative 1: Manual QA by domain experts
- **Pros**: Highest quality signal; catches subtle domain errors no automated metric detects
- **Cons**: Not scalable; expensive; cannot be run in CI; one-time effort decays as the knowledge base evolves
- **Why not** (as sole method): Manual QA is valuable for establishing the ground truth dataset but cannot serve as an ongoing regression gate. It must be combined with automated metrics.

### Alternative 2: BERTScore / ROUGE / BLEU
- **Pros**: Well-understood NLP metrics; fast to compute; no LLM required for evaluation
- **Cons**: ROUGE and BLEU measure surface-level token overlap — an answer can paraphrase the source perfectly and score poorly; BERTScore is better but still measures similarity, not faithfulness or factual correctness
- **Why not**: These metrics were designed for machine translation and summarisation, not RAG evaluation. A GPT-4o answer that is accurate but worded differently from the ground truth will score poorly, creating false negatives.

### Alternative 3: LLM-as-judge (GPT-4o evaluates GPT-4o outputs)
- **Pros**: Flexible; can evaluate any dimension with a custom rubric; correlates well with human judgment on RAG tasks
- **Cons**: Expensive (evaluation doubles the OpenAI cost); GPT-4o has a known bias toward longer, more confident-sounding answers; evaluation results are not deterministic
- **Why not** (as sole method): RAGAS uses LLM-as-judge internally for some metrics but combines it with embedding-based metrics for others, reducing the bias and cost. A pure LLM-as-judge approach without structured metrics makes it hard to track regressions quantitatively over time.

## Consequences

### Positive (when v2 eval is implemented)
- CI pipeline can reject a PR that degrades faithfulness below 0.85 — the same way coverage gates reject low-test PRs
- Retrieval quality improvements (e.g., changing chunk size, overlap, or top-k) are measurable, not anecdotal
- Knowledge base administrators can see answer quality metrics in the monitoring dashboard alongside latency and token usage

### Negative (v1 gap)
- **No regression detection on prompt changes**: If a system prompt is updated and the model starts hallucinating, this is only caught by a user complaint, not automated testing
- **No retrieval quality signal**: We do not know if hybrid search is returning the right chunks for our knowledge base domain; we only know it returns *some* chunks quickly
- **Ground truth curation cost**: Building a meaningful eval dataset requires 100–500 Q&A pairs validated by domain experts; this is a one-time cost of 1–2 weeks of expert time

### Risks
- **Eval dataset drift**: If the knowledge base content changes significantly but the eval dataset is not updated, accuracy scores become misleading. Mitigation: tag each eval example with the document version it was created from; deprecate examples when the source document is updated.

## v2 Implementation Sketch

```python
# scripts/eval/run_ragas.py
from ragas import evaluate
from ragas.metrics import faithfulness, answer_relevancy, context_precision, context_recall
from datasets import Dataset

# Load ground-truth dataset from docs/eval/ground_truth.jsonl
# Each record: {"question": "...", "ground_truth": "...", "contexts": [...]}
dataset = Dataset.from_json("docs/eval/ground_truth.jsonl")

results = evaluate(
    dataset=dataset,
    metrics=[faithfulness, answer_relevancy, context_precision, context_recall],
)
print(results)
# Fail CI if any metric below threshold
assert results["faithfulness"] > 0.85, "Faithfulness regression detected"
```
