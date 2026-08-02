import { useCallback, useEffect, useState } from "react";
import { useDropzone } from "react-dropzone";
import { listDocuments, uploadDocument, deleteDocument, Document } from "../api/client";
import {
  Upload, Trash2, CheckCircle, Clock, AlertCircle, Loader, Archive, HelpCircle, FileText, X,
} from "lucide-react";
import clsx from "clsx";

const STATUS_STYLE: Record<Document["status"], { icon: JSX.Element; classes: string }> = {
  indexed: { icon: <CheckCircle size={13} />, classes: "bg-emerald-50 text-emerald-700" },
  pending: { icon: <Clock size={13} />, classes: "bg-gold-50 text-gold-700" },
  processing: { icon: <Loader size={13} className="animate-spin" />, classes: "bg-blue-50 text-blue-700" },
  failed: { icon: <AlertCircle size={13} />, classes: "bg-red-50 text-red-700" },
  superseded: { icon: <Archive size={13} />, classes: "bg-stone-100 text-stone-500" },
  deleted: { icon: <Trash2 size={13} />, classes: "bg-stone-100 text-stone-500" },
  purged: { icon: <Trash2 size={13} />, classes: "bg-stone-100 text-stone-400" },
  unknown: { icon: <HelpCircle size={13} />, classes: "bg-stone-100 text-stone-500" },
};

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function Documents() {
  const [docs, setDocs] = useState<Document[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [title, setTitle] = useState("");
  const [stagedFile, setStagedFile] = useState<File | null>(null);

  const fetchDocs = async () => {
    setLoading(true);
    try {
      const res = await listDocuments(page);
      setDocs(res.data.documents);
      setTotal(res.data.total);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchDocs(); }, [page]);

  const onDrop = useCallback((accepted: File[]) => {
    const file = accepted[0];
    if (file) setStagedFile(file);
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      "application/pdf": [".pdf"],
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [".docx"],
      "application/vnd.openxmlformats-officedocument.presentationml.presentation": [".pptx"],
    },
    maxFiles: 1,
    disabled: uploading,
  });

  const handleUpload = async () => {
    if (!stagedFile || !title.trim()) return;
    setUploading(true);
    try {
      await uploadDocument(stagedFile, title.trim());
      setTitle("");
      setStagedFile(null);
      await fetchDocs();
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      alert(`Upload failed: ${message}`);
    } finally {
      setUploading(false);
    }
  };

  const handleDelete = async (documentId: string) => {
    if (!confirm("Delete this document and remove it from the knowledge base?")) return;
    await deleteDocument(documentId);
    await fetchDocs();
  };

  const canUpload = !!stagedFile && title.trim().length > 0 && !uploading;

  return (
    <div className="p-8 max-w-6xl">
      <h2 className="font-display text-3xl font-semibold text-stone-900 tracking-tight mb-1">Documents</h2>
      <p className="text-stone-500 text-sm mb-8">
        Upload documents (PDF, DOCX, PPTX). They are automatically processed and indexed into the knowledge base.
      </p>

      {/* Upload section */}
      <div className="bg-white rounded-2xl border border-stone-200/70 shadow-soft p-6 mb-6">
        <h3 className="font-display text-lg font-semibold text-stone-900 mb-4">Upload New Document</h3>

        <label className="block text-xs font-medium text-stone-500 uppercase tracking-wide mb-1.5">
          Document Title
        </label>
        <input
          type="text"
          placeholder="e.g. Aspirin 500mg — Patient Information Leaflet"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          data-testid="document-title-input"
          className="w-full border border-stone-200 rounded-lg px-3.5 py-2.5 text-sm mb-4 focus:outline-none focus:ring-2 focus:ring-gold-400/40 focus:border-gold-400 transition-shadow"
        />

        {stagedFile ? (
          <div
            data-testid="staged-file"
            className="border border-stone-200 rounded-xl p-4 flex items-center gap-4 bg-stone-50"
          >
            <div className="p-2.5 rounded-lg bg-stone-900 text-white shrink-0">
              <FileText size={18} strokeWidth={1.75} />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-stone-800 truncate">{stagedFile.name}</p>
              <p className="text-xs text-stone-500 mt-0.5">{formatFileSize(stagedFile.size)}</p>
            </div>
            <button
              onClick={() => setStagedFile(null)}
              disabled={uploading}
              data-testid="remove-staged-file"
              aria-label="Remove selected file"
              className="p-1.5 rounded-lg text-stone-400 hover:text-stone-700 hover:bg-stone-200/60 transition-colors disabled:opacity-40"
            >
              <X size={16} />
            </button>
          </div>
        ) : (
          <div
            {...getRootProps()}
            data-testid="upload-dropzone"
            className={clsx(
              "border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-colors",
              isDragActive ? "border-gold-400 bg-gold-50/50" : "border-stone-200 hover:border-gold-300 hover:bg-stone-50"
            )}
          >
            <input {...getInputProps()} />
            <Upload size={28} strokeWidth={1.5} className="mx-auto text-stone-400 mb-3" />
            {isDragActive ? (
              <p className="text-gold-700 text-sm font-medium">Drop the file here</p>
            ) : (
              <p className="text-stone-500 text-sm">
                Drag & drop a PDF, DOCX, or PPTX file, or click to select
              </p>
            )}
          </div>
        )}

        <button
          onClick={handleUpload}
          disabled={!canUpload}
          data-testid="upload-button"
          className="mt-4 w-full sm:w-auto flex items-center justify-center gap-2 bg-stone-900 text-white rounded-lg px-6 py-2.5 text-sm font-medium hover:bg-stone-800 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {uploading ? <Loader size={15} className="animate-spin" /> : <Upload size={15} />}
          {uploading ? "Uploading…" : "Upload Document"}
        </button>
      </div>

      {/* Document list */}
      <div className="bg-white rounded-2xl border border-stone-200/70 shadow-soft overflow-hidden">
        <div className="p-5 border-b border-stone-100 flex items-center justify-between">
          <h3 className="font-display text-lg font-semibold text-stone-900">
            Knowledge Base <span className="text-stone-400 font-sans text-sm font-normal">({total} documents)</span>
          </h3>
          <button onClick={fetchDocs} className="text-xs font-medium text-gold-700 hover:text-gold-800 transition-colors">
            Refresh
          </button>
        </div>

        {loading ? (
          <p className="p-6 text-stone-400 text-sm">Loading…</p>
        ) : docs.length === 0 ? (
          <p data-testid="documents-empty-state" className="p-6 text-stone-400 text-sm">No documents yet. Upload your first document!</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm min-w-[540px]">
              <thead className="bg-stone-50 text-stone-500 text-xs uppercase tracking-wide">
                <tr>
                  <th className="px-5 py-3 text-left font-medium">Filename</th>
                  <th className="px-5 py-3 text-left font-medium">Status</th>
                  <th className="px-5 py-3 text-left font-medium">Chunks</th>
                  <th className="px-5 py-3 text-left font-medium">Uploaded</th>
                  <th className="px-5 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y divide-stone-100">
                {docs.map((doc) => {
                  const status = STATUS_STYLE[doc.status];
                  return (
                    <tr key={doc.document_id} data-testid="document-row" className="hover:bg-stone-50/80 transition-colors">
                      <td className="px-5 py-3.5 font-medium text-stone-800">{doc.filename}</td>
                      <td className="px-5 py-3.5">
                        <span className={clsx("inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium capitalize", status.classes)}>
                          {status.icon}
                          {doc.status}
                        </span>
                      </td>
                      <td className="px-5 py-3.5 text-stone-500">{doc.chunk_count}</td>
                      <td className="px-5 py-3.5 text-stone-400">
                        {new Date(doc.created_at).toLocaleDateString()}
                      </td>
                      <td className="px-5 py-3.5 text-right">
                        <button
                          onClick={() => handleDelete(doc.document_id)}
                          data-testid="delete-button"
                          className="text-stone-400 hover:text-red-600 transition-colors"
                        >
                          <Trash2 size={15} />
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {total > 20 && (
          <div className="p-4 border-t border-stone-100 flex justify-center gap-2">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1}
              className="px-3 py-1.5 text-xs border border-stone-200 rounded-lg disabled:opacity-40 hover:bg-stone-50 transition-colors"
            >
              Prev
            </button>
            <span className="text-xs text-stone-500 self-center">Page {page}</span>
            <button
              onClick={() => setPage((p) => p + 1)}
              disabled={page * 20 >= total}
              className="px-3 py-1.5 text-xs border border-stone-200 rounded-lg disabled:opacity-40 hover:bg-stone-50 transition-colors"
            >
              Next
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
