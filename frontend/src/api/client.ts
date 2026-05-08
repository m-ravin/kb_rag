import axios from "axios";

const api = axios.create({
  baseURL: "/api",
  timeout: 60000,
});

// Attach JWT token to every request if logged in
api.interceptors.request.use((config) => {
  const token = localStorage.getItem("access_token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Module-level flag: true while the login() function is executing.
// Used by the 401 interceptor to skip the redirect-to-login during login itself.
let _loginInProgress = false;

// Redirect to login on 401 — but never while a login call is in-flight
// (wrong password) and never when we are already on /login.
api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401 && !_loginInProgress) {
      const isOnLoginPage = window.location.pathname === "/login";
      if (!isOnLoginPage) {
        localStorage.removeItem("access_token");
        window.location.href = "/login";
      }
    }
    return Promise.reject(err);
  }
);

export default api;

// ── Typed API functions ───────────────────────────────────────────────────────

export interface AskResponse {
  session_id: string;
  question: string;
  answer: string;
  question_type: string;
  sources: ChunkResult[];
  language: string;
  tokens_used: number;
  latency_ms: number;
  flagged_pii: boolean;
  flagged_unsafe: boolean;
  created_at: string;
}

export interface ChunkResult {
  chunk_id: string;
  document_id: string;
  filename: string;
  content: string;
  score: number;
}

export interface Document {
  document_id: string;
  filename: string;
  status: "pending" | "processing" | "indexed" | "failed";
  metadata: Record<string, unknown>;
  chunk_count: number;
  created_at: string;
  updated_at: string;
  error?: string;
}

export const askQuestion = (question: string, language = "en") =>
  api.post<AskResponse>("/qa/ask", { question, language });

export const listDocuments = (page = 1, limit = 20) =>
  api.get<{ documents: Document[]; total: number; page: number; limit: number }>(
    `/manage/documents?page=${page}&limit=${limit}`
  );

export const uploadDocument = (file: File, title: string, version = "1.0") => {
  const form = new FormData();
  form.append("file", file);
  form.append("title", title);
  form.append("version", version);
  return api.post("/manage/documents/upload", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
};

export const deleteDocument = (documentId: string) =>
  api.delete(`/manage/documents/${documentId}`);

export const getMetrics = () => api.get("/manage/metrics");

export const login = async (email: string, password: string): Promise<void> => {
  const form = new URLSearchParams();
  form.append("username", email);
  form.append("password", password);
  _loginInProgress = true;
  try {
    const res = await api.post<{ access_token: string }>("/manage/auth/token", form, {
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
    });
    localStorage.setItem("access_token", res.data.access_token);
  } finally {
    _loginInProgress = false;
  }
};
