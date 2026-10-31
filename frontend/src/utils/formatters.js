/**
 * Format a byte count as a compact, readable storage value.
 * Returns a friendly placeholder when a storage limit is not configured.
 */
export function formatBytes(value) {
  if (value === null || value === undefined) return "Not configured";
  if (value === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(
    Math.floor(Math.log(value) / Math.log(1024)),
    units.length - 1
  );
  const amount = (value / Math.pow(1024, index)).toFixed(index > 1 ? 2 : 1);
  return amount + " " + units[index];
}

/**
 * Build a two-character avatar label from a member's display name.
 */
export function initials(name = "") {
  return name
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .map((part) => part[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
}
