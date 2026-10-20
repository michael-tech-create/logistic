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
  if (!files.length) return "Choose at least one PDF or TXT file.";
  if (files.length > quota) return `You have ${quota} parses left. Choose fewer files or add more parses in Settings.`;
  for (const file of files) {
    if (!/\.(pdf|txt)$/i.test(file.name)) return `${file.name}: choose a PDF or TXT file.`;
    if (file.size > 10 * 1024 * 1024) return `${file.name}: the maximum file size is 10 MB.`;
    if (!file.size) return `${file.name} is empty. Choose a file with quote details.`;
  }
  return "";
}

export async function request(token, path, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 120000);
  try {
    const response = await fetch(`${API}${path}`, {
      ...options,
      signal: options.signal || controller.signal,
      headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(options.body && !(options.body instanceof FormData) ? { "Content-Type": "application/json" } : {}), ...options.headers },
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      const detail = typeof payload.detail === "string" ? payload.detail : response.status >= 500
        ? "The desk API is unavailable. If you’re running locally, restart with npm run dev in dashboard to start both the API and website. Otherwise, try again shortly."
        : "The request could not be completed. Please try again.";
      const error = new Error(response.status === 401 && token ? "Your session has expired. Sign out and sign in again." : detail);
      error.status = response.status;
      throw error;
    }
    return options.download ? response.blob() : response.json();
  } catch (error) {
    if (error.name === "AbortError") throw new Error("This is taking longer than expected. Your service may be starting up. Please try again shortly.");
    if (error instanceof TypeError) throw new Error("Could not reach the desk. Check your connection and try again. Your input is still here.");
    throw error;
  } finally {
    clearTimeout(timer);
  }
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
