import { useState } from "react";
import axios from "axios";
import ReactMarkdown from "react-markdown";
import { askQuestion, AskResponse } from "../api/client";
import { Send, Loader, AlertTriangle } from "lucide-react";

function getErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === "string") return detail;
    if (!error.response) return "Could not reach the server. Check your connection and try again.";
    return `Request failed (${error.response.status}). Please try again.`;
  }
  return "Something went wrong. Please try again.";
}

export default function QATest() {
  const [question, setQuestion] = useState("");
  const [language, setLanguage] = useState("en");
  const [response, setResponse] = useState<AskResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!question.trim()) return;
    setLoading(true);
    setError("");
    setResponse(null);
    try {
      const res = await askQuestion(question.trim(), language);
      setResponse(res.data);
    } catch (err: unknown) {
      setError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="p-8 max-w-3xl">
      <h2 className="font-display text-3xl font-semibold text-stone-900 tracking-tight mb-1">Q&A Test Console</h2>
      <p className="text-stone-500 text-sm mb-8">
        Test the full RAG pipeline end-to-end. Ask any question about a PIL in the knowledge base.
      </p>

      <form onSubmit={handleSubmit} className="space-y-3 mb-6" data-testid="qa-form">
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Ask a question about a document in the knowledge base…"
          rows={3}
          data-testid="question-input"
          className="w-full border border-stone-200 rounded-xl px-4 py-3 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-gold-400/40 focus:border-gold-400 transition-shadow"
        />
        <div className="flex gap-3">
          <select
            value={language}
            onChange={(e) => setLanguage(e.target.value)}
            data-testid="language-select"
            className="border border-stone-200 rounded-lg px-3 py-2 text-sm text-stone-700 focus:outline-none focus:ring-2 focus:ring-gold-400/40"
          >
            <option value="en">English</option>
            <option value="ms">Bahasa Malaysia</option>
            <option value="zh">Chinese</option>
            <option value="ta">Tamil</option>
          </select>
          <button
            type="submit"
            disabled={loading || !question.trim()}
            data-testid="ask-button"
            className="flex items-center gap-2 bg-stone-900 text-white rounded-lg px-5 py-2 text-sm font-medium hover:bg-stone-800 disabled:opacity-40 transition-colors"
          >
            {loading ? <Loader size={14} className="animate-spin" /> : <Send size={14} />}
            {loading ? "Thinking…" : "Ask"}
          </button>
        </div>
      </form>

      {error && (
        <div data-testid="qa-error" className="bg-red-50 border border-red-200 rounded-xl p-4 text-sm text-red-700 mb-4">
          {error}
        </div>
      )}

      {response && (
        <div className="space-y-4">
          {/* Answer */}
          <div data-testid="answer-card" className="bg-white rounded-2xl border border-stone-200/70 shadow-soft p-6">
            <div className="flex items-center gap-2 mb-4">
              <span className="text-xs font-semibold uppercase tracking-wide text-gold-700 bg-gold-50 px-2.5 py-1 rounded-full">
                Answer
              </span>
              {response.flagged_pii && (
                <span data-testid="pii-badge" className="flex items-center gap-1 text-xs text-amber-700 bg-amber-50 px-2.5 py-1 rounded-full">
                  <AlertTriangle size={11} /> PII Detected in question
                </span>
              )}
              {response.flagged_unsafe && (
                <span data-testid="unsafe-badge" className="flex items-center gap-1 text-xs text-red-700 bg-red-50 px-2.5 py-1 rounded-full">
                  <AlertTriangle size={11} /> Unsafe Content Flagged
                </span>
              )}
            </div>
            <div data-testid="answer-text" className="text-stone-800 leading-relaxed text-sm space-y-2">
              <ReactMarkdown
                components={{
                  p: ({ node, ...props }) => <p className="leading-relaxed" {...props} />,
                  strong: ({ node, ...props }) => <strong className="font-semibold text-stone-900" {...props} />,
                  ul: ({ node, ...props }) => <ul className="list-disc pl-5 space-y-1" {...props} />,
                  ol: ({ node, ...props }) => <ol className="list-decimal pl-5 space-y-1" {...props} />,
                  h1: ({ node, ...props }) => <h1 className="font-display text-base font-semibold text-stone-900 mt-3" {...props} />,
                  h2: ({ node, ...props }) => <h2 className="font-display text-sm font-semibold text-stone-900 mt-3" {...props} />,
                  h3: ({ node, ...props }) => <h3 className="font-display text-sm font-semibold text-stone-900 mt-2" {...props} />,
                }}
              >
                {response.answer}
              </ReactMarkdown>
            </div>
            <div className="mt-5 flex flex-wrap gap-4 text-xs text-stone-400 border-t border-stone-100 pt-3">
              <span>Type: <strong className="text-stone-600 font-medium">{response.question_type}</strong></span>
              <span>Language: <strong className="text-stone-600 font-medium">{response.language}</strong></span>
              <span>Tokens: <strong className="text-stone-600 font-medium">{response.tokens_used.toLocaleString()}</strong></span>
              <span>Latency: <strong className="text-stone-600 font-medium">{response.latency_ms}ms</strong></span>
            </div>
          </div>

          {/* Sources */}
          {response.sources.length > 0 && (
            <div data-testid="sources-card" className="bg-white rounded-2xl border border-stone-200/70 shadow-soft p-6">
              <h4 className="font-display text-base font-semibold text-stone-900 mb-4">
                Sources <span className="text-stone-400 font-sans text-sm font-normal">({response.sources.length})</span>
              </h4>
              <div className="space-y-3">
                {response.sources.map((src) => (
                  <div key={src.chunk_id} data-testid="source-item" className="border border-stone-100 rounded-xl p-3.5 hover:border-stone-200 transition-colors">
                    <p className="text-xs font-medium text-gold-700 mb-1">{src.filename}</p>
                    <p className="text-xs text-stone-600 line-clamp-3">{src.content}</p>
                    <p className="text-xs text-stone-400 mt-1.5">
                      Score: {src.score.toFixed(4)}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
