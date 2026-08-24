import { useState } from "react";
import { recentLogs } from "../log";
import { useStore } from "../store";
import { Dialog } from "./Dialog";

const MAX_TOTAL_BYTES = 20 * 1024 * 1024;

interface Attachment {
  name: string;
  type: string;
  data: string;
  size: number;
}

function readAttachment(file: File): Promise<Attachment> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () =>
      resolve({
        name: file.name,
        type: file.type || "application/octet-stream",
        data: (reader.result as string).split(",", 2)[1],
        size: file.size,
      });
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

export function ReportDialog() {
  const { send, isPending, openDialog, reportResult, toast } = useStore();
  const [message, setMessage] = useState("");
  const [email, setEmail] = useState("");
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const sending = isPending("report.send");
  const bundling = isPending("report.bundle");
  const close = () => openDialog(null);
  const downloadBundle = () => send({ cmd: "report.bundle", logs: recentLogs() });

  const addFiles = async (files: FileList | null) => {
    if (!files) return;
    let total = attachments.reduce((sum, a) => sum + a.size, 0);
    const added: Attachment[] = [];
    for (const file of Array.from(files)) {
      if (total + file.size > MAX_TOTAL_BYTES) {
        toast("error", `Attachments are capped at ${MAX_TOTAL_BYTES / 1024 / 1024} MB per report, so ${file.name} was skipped`);
        continue;
      }
      total += file.size;
      added.push(await readAttachment(file));
    }
    setAttachments((current) => [...current, ...added]);
  };

  const submit = () =>
    send({
      cmd: "report.send",
      message: message.trim(),
      email: email.trim(),
      client: {
        url: location.href,
        user_agent: navigator.userAgent,
        viewport: `${window.innerWidth}x${window.innerHeight}`,
      },
      logs: recentLogs(),
      attachments: attachments.map(({ name, type, data }) => ({ name, type, data })),
    });

  if (reportResult?.ok) {
    return (
      <Dialog title="Report a bug" onClose={close}>
        <div className="space-y-4">
          <p className="text-sm text-text-1">
            Report sent, thank you.{" "}
            {email.trim()
              ? "If more information is needed, you'll hear back at the address you left."
              : "It was submitted anonymously."}
          </p>
          <button className="btn btn-primary w-full" onClick={close}>
            Done
          </button>
        </div>
      </Dialog>
    );
  }

  return (
    <Dialog title="Report a bug" onClose={close}>
      <div className="space-y-3">
        <p className="text-sm text-text-1">
          Something broken? Describe it and it goes straight to me, anonymously and with no account needed.
        </p>
        <textarea
          className="field min-h-28"
          placeholder="What happened, and what did you expect instead?"
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          autoFocus
        />
        <input
          className="field"
          type="email"
          placeholder="Email for follow-up (optional)"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <div className="flex flex-wrap items-center gap-2">
          <label className="btn cursor-pointer">
            Attach screenshots
            <input type="file" hidden multiple accept="image/*,video/*" onChange={(e) => void addFiles(e.target.files)} />
          </label>
          {attachments.map((attachment, index) => (
            <span key={`${attachment.name}-${index}`} className="chip inline-flex items-center gap-1.5">
              {attachment.name}
              <button
                type="button"
                className="cursor-pointer hover:text-bad"
                aria-label={`Remove ${attachment.name}`}
                onClick={() => setAttachments((current) => current.filter((_, i) => i !== index))}
              >
                ×
              </button>
            </span>
          ))}
        </div>
        <details className="text-[0.7rem] text-text-2">
          <summary className="cursor-pointer hover:text-text-1">What's sent with your report</summary>
          <p className="mt-1.5 leading-relaxed">
            Your description, any files you attach, and a diagnostics bundle: the app version and platform, your
            camera, printer, monitor and notification configuration with every credential removed, performance
            stats, recent errors and warnings, and the app's recent logs, also scrubbed of credentials. No
            camera frames are included unless you attach them yourself. Download the same bundle to read it
            first, or to send it somewhere else yourself.
          </p>
        </details>
        {reportResult && !reportResult.ok && (
          <p className="text-xs text-bad">Sending failed: {reportResult.error || "unknown error"}</p>
        )}
        <div className="flex gap-2">
          <button className="btn flex-1" disabled={bundling} onClick={downloadBundle}>
            {bundling ? "Preparing…" : "Download logs"}
          </button>
          <button className="btn btn-primary flex-1" disabled={!message.trim() || sending} onClick={submit}>
            {sending ? "Sending…" : "Send report"}
          </button>
        </div>
      </div>
    </Dialog>
  );
}
