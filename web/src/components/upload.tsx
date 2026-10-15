"use client";
import { useRef, useState } from "react";
import {
  CloudUpload,
  FileText,
  CheckCircle2,
  Loader2,
  X,
  RotateCcw,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { api, demoLimitReached } from "@/lib/client";
import type { InvoiceRecord } from "@/lib/types";
type Upload = {
  file: File;
  state: "ready" | "uploading" | "done" | "error";
  error?: string;
};
export function UploadPanel({ onUploaded }: { onUploaded: () => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [items, setItems] = useState<Upload[]>([]);
  const [drag, setDrag] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [limit, setLimit] = useState("");
  function add(files: FileList | File[]) {
    setError("");
    const next: Upload[] = Array.from(files).map((file) => ({
      file,
      state: "ready",
      error:
        file.size === 0
          ? "This file is empty."
          : file.size > 4_000_000
            ? "This file exceeds 4 MB."
            : ![
                  "application/pdf",
                  "image/png",
                  "image/jpeg",
                  "image/webp",
                ].includes(file.type)
              ? "Unsupported file type."
              : undefined,
    }));
    setItems((old) => [
      ...old,
      ...next.map((item) =>
        item.error ? { ...item, state: "error" as const } : item,
      ),
    ]);
  }
  async function upload() {
    setBusy(true);
    const next = [...items];
    for (let i = 0; i < next.length; i++) {
      if (next[i].state !== "ready") continue;
      next[i] = { ...next[i], state: "uploading" };
      setItems([...next]);
      const form = new FormData();
      form.append("file", next[i].file);
      try {
        await api<InvoiceRecord>("invoices", { method: "POST", body: form });
        next[i] = { ...next[i], state: "done" };
        onUploaded();
      } catch (error) {
        if (demoLimitReached(error)) {
          // Every later upload would hit the same cap; leave them ready.
          next[i] = { ...next[i], state: "ready" };
          setItems([...next]);
          setLimit((error as Error).message);
          break;
        }
        next[i] = {
          ...next[i],
          state: "error",
          error: (error as Error).message,
        };
      }
      setItems([...next]);
    }
    setBusy(false);
  }
  return (
    <section className="panel upload-panel">
      <div className="section-heading">
        <div>
          <h2>Upload supplier invoices</h2>
          <p>
            Start with the original. We’ll extract the details and check the
            match.
          </p>
        </div>
        <span className="subtle-label">PDF & images</span>
      </div>
      <div
        className={`drop-zone ${drag ? "dragging" : ""}`}
        onDragOver={(event) => {
          event.preventDefault();
          if (!busy) setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDrag(false);
          if (!busy) add(event.dataTransfer.files);
        }}
      >
        <span className="upload-icon">
          <CloudUpload size={26} />
        </span>
        <h3>Drop your invoices here</h3>
        <p>or choose files from your computer</p>
        <Button
          variant="outline"
          onClick={() => input.current?.click()}
          disabled={busy}
        >
          Browse files
        </Button>
        <small>PDF, PNG, JPG or WebP · Up to 4 MB per file</small>
        <input
          ref={input}
          type="file"
          multiple
          accept="application/pdf,image/png,image/jpeg,image/webp"
          className="sr-only"
          aria-label="Choose supplier invoices"
          onChange={(event) => {
            if (event.target.files) add(event.target.files);
            event.target.value = "";
          }}
        />
      </div>
      {limit && (
        <div className="error-banner limit-banner" role="alert">
          <div>
            <strong>Demo limit reached.</strong> {limit}
            {process.env.NEXT_PUBLIC_DEMO_VIDEO_URL && (
              <>
                {" "}
                <a
                  href={process.env.NEXT_PUBLIC_DEMO_VIDEO_URL}
                  target="_blank"
                  rel="noreferrer"
                >
                  Watch the demo video
                </a>{" "}
                to see uploads end to end.
              </>
            )}
          </div>
        </div>
      )}
      {items.length > 0 && (
        <div className="upload-list" aria-live="polite">
          {items.map((item, i) => (
            <div className="upload-item" key={`${item.file.name}-${i}`}>
              <FileText size={20} />
              <div>
                <strong>{item.file.name}</strong>
                <small className={item.error ? "error-message" : ""}>
                  {item.state === "done"
                    ? "Uploaded · Extraction and matching queued"
                    : item.state === "uploading"
                      ? "Uploading…"
                      : item.error ||
                        `${(item.file.size / 1_000_000).toFixed(2)} MB · Ready to upload`}
                </small>
              </div>
              {item.state === "done" ? (
                <CheckCircle2 className="text-success" size={18} />
              ) : item.state === "uploading" ? (
                <Loader2 className="animate-spin" size={18} />
              ) : (
                <>
                  <Button
                    variant="ghost"
                    size="icon"
                    disabled={busy}
                    aria-label={`Remove ${item.file.name}`}
                    onClick={() =>
                      setItems(items.filter((_, index) => index !== i))
                    }
                  >
                    <X />
                  </Button>
                  {item.state === "error" &&
                    item.file.size > 0 &&
                    item.file.size <= 4_000_000 &&
                    [
                      "application/pdf",
                      "image/png",
                      "image/jpeg",
                      "image/webp",
                    ].includes(item.file.type) && (
                      <Button
                        variant="ghost"
                        size="icon"
                        disabled={busy}
                        aria-label={`Retry ${item.file.name}`}
                        onClick={() =>
                          setItems(
                            items.map((value, index) =>
                              index === i
                                ? { ...value, state: "ready", error: undefined }
                                : value,
                            ),
                          )
                        }
                      >
                        <RotateCcw />
                      </Button>
                    )}
                </>
              )}
            </div>
          ))}
          <div className="upload-actions">
            <span>
              {items.filter((item) => item.state === "ready").length} ready to
              upload
            </span>
            <Button
              disabled={busy || !items.some((item) => item.state === "ready")}
              onClick={upload}
            >
              {busy && <Loader2 className="animate-spin" />}Upload & process
            </Button>
          </div>
        </div>
      )}
      {error && <p role="alert">{error}</p>}
      <p className="upload-footnote">
        Uploaded documents are supplier bills. Processing checks the invoice
        against purchase orders and recorded receipts.
      </p>
    </section>
  );
}
