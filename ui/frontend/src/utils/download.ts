/**
 * Download utilities for newsletter export functionality.
 * Supports JSON, Markdown, and PDF downloads.
 */

/**
 * Triggers a browser download for the given content.
 */
export function downloadBlob(
  content: string | Blob,
  filename: string,
  mimeType: string
): void {
  const blob =
    content instanceof Blob ? content : new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

/**
 * MIME types for supported download formats.
 */
export const MIME_TYPES = {
  json: "application/json",
  md: "text/markdown",
  pdf: "application/pdf",
} as const;

/**
 * Generates a consistent filename for newsletter downloads.
 * Pattern: {dataSource}_{startDate}_to_{endDate}_newsletter.{format}
 */
export function generateFilename(
  dataSource: string,
  startDate: string,
  endDate: string,
  format: string
): string {
  return `${dataSource}_${startDate}_to_${endDate}_newsletter.${format}`;
}
