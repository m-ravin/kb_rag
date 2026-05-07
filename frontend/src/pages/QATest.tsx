import { useState } from "react";
import { askQuestion, AskResponse } from "../api/client";
import { Send, Loader, AlertTriangle } from "lucide-react";

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
    } catch {
      setError("Request failed. Check your connection or try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="p-8 max-w-3xl">
      <h2 className="text-2xl font-bold text-gray-800 mb-1">Q&A Test Console</h2>
      <p className="text-gray-500 text-sm mb-6">
        Test the full RAG pipeline end-to-end. Ask any question about a PIL in the knowledge base.
      </p>

      <form onSubmit={handleSubmit} className="space-y-3 mb-6" data-testid="qa-form">
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Ask a question about a document in the knowledge base…"
          rows={3}
          data-testid="question-input"
          className="w-full border border-gray-300 rounded-xl px-4 py-3 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <div className="flex gap-3">
          <select
            value={language}
            onChange={(e) => setLanguage(e.target.value)}
            data-testid="language-select"
            className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none"
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
            className="flex items-center gap-2 bg-blue-600 text-white rounded-lg px-5 py-2 text-sm font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors"
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
          <div data-testid="answer-card" className="bg-white rounded-xl border border-gray-200 p-5">
            <div className="flex items-center gap-2 mb-3">
              <span className="text-xs font-semibold uppercase tracking-wide text-blue-600 bg-blue-50 px-2 py-0.5 rounded">
                Answer
              </span>
              {response.flagged_pii && (
                <span data-testid="pii-badge" className="flex items-center gap-1 text-xs text-yellow-600 bg-yellow-50 px-2 py-0.5 rounded">
                  <AlertTriangle size={11} /> PII Detected in question
                </span>
              )}
            </div>
            <p data-testid="answer-text" className="text-gray-800 leading-relaxed text-sm whitespace-pre-wrap">
              {response.answer}
            </p>
            <div className="mt-4 flex flex-wrap gap-4 text-xs text-gray-400 border-t border-gray-100 pt-3">
              <span>Type: <strong>{response.question_type}</strong></span>
              <span>Language: <strong>{response.language}</strong></span>
              <span>Tokens: <strong>{response.tokens_used.toLocaleString()}</strong></span>
              <span>Latency: <strong>{response.latency_ms}ms</strong></span>
            </div>
          </div>

          {/* Sources */}
          {response.sources.length > 0 && (
            <div data-testid="sources-card" className="bg-white rounded-xl border border-gray-200 p-5">
              <h4 className="text-sm font-semibold text-gray-700 mb-3">
                Sources ({response.sources.length})
              </h4>
              <div className="space-y-3">
                {response.sources.map((src) => (
                  <div key={src.chunk_id} data-testid="source-item" className="border border-gray-100 rounded-lg p-3">
                    <p className="text-xs font-medium text-blue-600 mb-1">{src.filename}</p>
                    <p className="text-xs text-gray-600 line-clamp-3">{src.content}</p>
                    <p className="text-xs text-gray-400 mt-1">
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
