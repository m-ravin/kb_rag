import { useCallback, useEffect, useState } from "react";
import { useDropzone } from "react-dropzone";
import { listDocuments, uploadDocument, deleteDocument, Document } from "../api/client";
import { Upload, Trash2, CheckCircle, Clock, AlertCircle, Loader } from "lucide-react";
import clsx from "clsx";

const STATUS_ICON = {
  indexed: <CheckCircle size={14} className="text-green-500" />,
  pending: <Clock size={14} className="text-yellow-500" />,
  processing: <Loader size={14} className="text-blue-500 animate-spin" />,
  failed: <AlertCircle size={14} className="text-red-500" />,
};

export default function Documents() {
  const [docs, setDocs] = useState<Document[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [title, setTitle] = useState("");

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

  const onDrop = useCallback(async (accepted: File[]) => {
    const file = accepted[0];
    if (!file || !title.trim()) {
      alert("Please enter a document title before uploading.");
      return;
    }
    setUploading(true);
    try {
      await uploadDocument(file, title.trim());
      setTitle("");
      await fetchDocs();
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      alert(`Upload failed: ${message}`);
    } finally {
      setUploading(false);
    }
  }, [title]);

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

  const handleDelete = async (documentId: string) => {
    if (!confirm("Delete this document and remove it from the knowledge base?")) return;
    await deleteDocument(documentId);
    await fetchDocs();
  };

  return (
    <div className="p-8">
      <h2 className="text-2xl font-bold text-gray-800 mb-1">Documents</h2>
      <p className="text-gray-500 text-sm mb-6">
        Upload PIL documents (PDF, DOCX, PPTX). They are automatically processed and indexed.
      </p>

      {/* Upload section */}
      <div className="bg-white rounded-xl border border-gray-200 p-6 mb-6">
        <h3 className="text-base font-semibold text-gray-700 mb-4">Upload New Document</h3>
        <input
          type="text"
          placeholder="Document title (required)"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          data-testid="document-title-input"
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm mb-3 focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <div
          {...getRootProps()}
          data-testid="upload-dropzone"
          className={clsx(
            "border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-colors",
            isDragActive ? "border-blue-400 bg-blue-50" : "border-gray-300 hover:border-blue-400"
          )}
        >
          <input {...getInputProps()} />
          <Upload size={32} className="mx-auto text-gray-400 mb-2" />
          {uploading ? (
            <p className="text-blue-600 text-sm font-medium">Uploading…</p>
          ) : isDragActive ? (
            <p className="text-blue-600 text-sm">Drop the file here</p>
          ) : (
            <p className="text-gray-500 text-sm">
              Drag & drop a PDF, DOCX, or PPTX file, or click to select
            </p>
          )}
        </div>
      </div>

      {/* Document list */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="p-4 border-b border-gray-100 flex items-center justify-between">
          <h3 className="text-base font-semibold text-gray-700">
            Knowledge Base ({total} documents)
          </h3>
          <button onClick={fetchDocs} className="text-xs text-blue-600 hover:underline">
            Refresh
          </button>
        </div>

        {loading ? (
          <p className="p-6 text-gray-400 text-sm">Loading…</p>
        ) : docs.length === 0 ? (
          <p className="p-6 text-gray-400 text-sm">No documents yet. Upload your first PIL!</p>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-gray-500 text-xs uppercase tracking-wide">
              <tr>
                <th className="px-4 py-3 text-left">Filename</th>
                <th className="px-4 py-3 text-left">Status</th>
                <th className="px-4 py-3 text-left">Chunks</th>
                <th className="px-4 py-3 text-left">Uploaded</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {docs.map((doc) => (
                <tr key={doc.document_id} data-testid="document-row" className="hover:bg-gray-50">
                  <td className="px-4 py-3 font-medium text-gray-800">{doc.filename}</td>
                  <td className="px-4 py-3">
                    <span className="flex items-center gap-1.5 capitalize">
                      {STATUS_ICON[doc.status]}
                      {doc.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-gray-500">{doc.chunk_count}</td>
                  <td className="px-4 py-3 text-gray-400">
                    {new Date(doc.created_at).toLocaleDateString()}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      onClick={() => handleDelete(doc.document_id)}
                      data-testid="delete-button"
                      className="text-red-400 hover:text-red-600 transition-colors"
                    >
                      <Trash2 size={15} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {total > 20 && (
          <div className="p-4 border-t border-gray-100 flex justify-center gap-2">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1}
              className="px-3 py-1 text-xs border rounded disabled:opacity-40"
            >
              Prev
            </button>
            <span className="text-xs text-gray-500 self-center">Page {page}</span>
            <button
              onClick={() => setPage((p) => p + 1)}
              disabled={page * 20 >= total}
              className="px-3 py-1 text-xs border rounded disabled:opacity-40"
            >
              Next
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
