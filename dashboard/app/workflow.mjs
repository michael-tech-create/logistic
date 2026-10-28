export const API = process.env.NEXT_PUBLIC_API_URL || "";

export function money(currency, amount) {
  if (amount == null || !Number.isFinite(Number(amount))) return "Not available";
  return `${currency || ""} ${Number(amount).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`.trim();
}

export function missingDetails(record) {
  const missing = [];
  for (const field of ["origin", "destination"]) {
    if (!record.movement?.[field]?.location_name) missing.push(field);
  }
  if (!record.line_items?.length || !record.commercial?.currency || !(Number(record.commercial?.total_amount) > 0)) missing.push("priced charges");
  return missing;
}

export function statusOf(record) {
  if (missingDetails(record).length) return { key: "incomplete", label: "Needs details", color: "warning" };
  if (record.desk_review?.status === "reviewed") return { key: "reviewed", label: "Checked", color: "success" };
  return { key: "pending", label: "To check", color: "info" };
}

export function reviewStatusOf(row) {
  if (row.status === "approved" && ["pay", "clear"].includes(row.kind)) return { label: "Approved · Not sent", color: "warning", canSend: true };
  if (row.status === "executed") return { label: "Submitted to provider", color: "success" };
  if (row.status === "processing") return { label: "Submission started · Verify outcome", color: "warning" };
  if (row.status === "execution_uncertain") return { label: "Approved · Verify with provider", color: "warning" };
  if (row.status === "rejected") return { label: "Rejected", color: "default" };
  if (row.status === "approved") return { label: "Approved", color: "success" };
  return { label: "Awaiting your decision", color: "info" };
}

export function mergeRecords(live, pack) {
  const seen = new Set();
  return [...live, ...pack].filter((record) => {
    // References and filenames can legitimately repeat across vendors or shipments.
    if (!record.record_id) return true;
    if (seen.has(record.record_id)) return false;
    seen.add(record.record_id);
    return true;
  });
}

export function filterRecords(records, search, filter) {
  const query = search.trim().toLowerCase();
  return records.filter((record) => {
    const status = statusOf(record).key;
    if (filter === "unchecked" && status === "reviewed") return false;
    if (filter === "reviewed" && status !== "reviewed") return false;
    const text = [record.commercial?.vendor_name, record.commercial?.quote_reference_id, record.movement?.origin?.location_name, record.movement?.destination?.location_name, record.source_file].join(" ").toLowerCase();
    return text.includes(query);
  });
}

export function validateFiles(files, quota) {
  if (!files.length) return "Choose at least one PDF, text, image, or audio file.";
  if (files.length > quota) return `You have ${quota} parses left. Choose fewer files or add more parses in Settings.`;
  for (const file of files) {
    if (!/\.(pdf|txt|png|jpe?g|webp|mp3|m4a|wav|ogg|opus|aac)$/i.test(file.name)) return `${file.name}: choose a PDF, TXT, image, or audio file.`;
    if (file.size > 10 * 1024 * 1024) return `${file.name}: the maximum file size is 10 MB.`;
    if (!file.size) return `${file.name} is empty. Choose a file with quote details.`;
  }
  return "";
}

export async function request(token, path, options = {}) {
  const { timeout = 120000, retryDelay = 1000, download = false, ...rest } = options;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const signal = rest.signal ? AbortSignal.any([rest.signal, controller.signal]) : controller.signal;
    const safeRead = ["GET", "HEAD"].includes((rest.method || "GET").toUpperCase());
    let response;
    for (let attempt = 0; ; attempt++) {
      try {
        response = await fetch(`${API}${path}`, {
          ...rest, signal,
          headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(options.body && !(options.body instanceof FormData) ? { "Content-Type": "application/json" } : {}), ...options.headers },
        });
        if (!safeRead || ![502, 503, 504].includes(response.status) || attempt >= 2) break;
        await response.body?.cancel();
      } catch (error) {
        if (!safeRead || !(error instanceof TypeError) || attempt >= 2 || signal.aborted) throw error;
      }
      await pause(retryDelay, signal);
    }
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      const detail = typeof payload.detail === "string" ? payload.detail : Array.isArray(payload.detail)
        ? payload.detail.slice(0, 3).map((item) => `${(item.loc || []).filter((part) => part !== "body").join(" / ")}: ${item.msg || "Check this value"}`).join(". ") : response.status >= 500
        ? "We couldn’t connect to your workspace. Please wait a moment and try again. Your entries are still here."
        : "The request could not be completed. Please try again.";
      const error = new Error(response.status === 401 && token ? "Your session has expired. Sign out and sign in again." : detail);
      error.status = response.status;
      throw error;
    }
    return download ? response.blob() : response.json();
  } catch (error) {
    if (error.name === "AbortError") throw new Error("Connecting is taking longer than expected. Please wait a moment and try again. Your entries are still here.");
    if (error instanceof TypeError) throw new Error("Could not reach the desk. Check your connection and try again. Your input is still here.");
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

function pause(milliseconds, signal) {
  return new Promise((resolve, reject) => {
    if (signal.aborted) { reject(new DOMException("Aborted", "AbortError")); return; }
    const onAbort = () => { clearTimeout(timer); reject(new DOMException("Aborted", "AbortError")); };
    const timer = setTimeout(() => { signal.removeEventListener("abort", onAbort); resolve(); }, milliseconds);
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

// Only the read-only health request is repeated. Never replay form submissions.
export async function ensureServiceReady({ timeout = 60000, retryDelay = 1500 } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    while (!controller.signal.aborted) {
      try {
        const response = await fetch(`${API}/health`, { cache: "no-store", signal: AbortSignal.any([controller.signal, AbortSignal.timeout(8000)]) });
        const body = await response.json().catch(() => null);
        if (response.ok && body?.ok === true) return;
        if (response.status === 404) break;
      } catch { if (controller.signal.aborted) break; }
      await pause(retryDelay, controller.signal);
    }
  } catch { /* A bounded readiness check leaves the form intact. */ }
  finally { clearTimeout(timer); }
  throw new Error("We couldn’t connect to your workspace yet. Please wait a moment and try again. Your entries are still here.");
}

export function saveDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
