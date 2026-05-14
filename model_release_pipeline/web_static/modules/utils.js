export function statusClass(status) {
  if (!status) return "";
  if (["failed", "export_failed", "offboard_failed"].includes(status)) return "failed";
  if (["done", "completed", "ok"].includes(status)) return "done";
  return String(status).replace(/[^a-z0-9_-]/gi, "");
}

export function formatEpoch(epoch) {
  if (epoch === null || epoch === undefined) return "NA";
  return String(Number(epoch)).padStart(3, "0");
}

export function shortName(value) {
  if (!value) return "manual / unknown";
  return value.length > 58 ? `${value.slice(0, 55)}...` : value;
}

export function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}
