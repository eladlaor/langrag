/**
 * DownloadDropdown Component
 *
 * Reusable dropdown for downloading newsletter content in JSON, Markdown, or PDF format.
 * Handles loading states, error feedback, and PDF generation from HTML.
 */

import React, { useState, useCallback } from "react";
import { Dropdown, Spinner } from "react-bootstrap";
import { api } from "../services/api";
import { downloadBlob, generateFilename, MIME_TYPES } from "../utils/download";
import html2pdf from "html2pdf.js";

type DownloadFormat = "json" | "md" | "pdf";

interface DownloadDropdownProps {
  runId: string;
  runType: "periodic";
  dataSource: string;
  startDate: string;
  endDate: string;
  disabled?: boolean;
  size?: "sm" | "lg";
}

export const DownloadDropdown: React.FC<DownloadDropdownProps> = ({
  runId,
  runType,
  dataSource,
  startDate,
  endDate,
  disabled = false,
  size = "sm",
}) => {
  const [downloading, setDownloading] = useState<DownloadFormat | null>(null);
  const [error, setError] = useState<string | null>(null);

  /**
   * Extracts body content from a full HTML document.
   */
  const extractBodyContent = (html: string): string => {
    const bodyMatch = html.match(/<body[^>]*>([\s\S]*)<\/body>/i);
    return bodyMatch ? bodyMatch[1] : html;
  };

  /**
   * Downloads JSON or Markdown content directly.
   */
  const downloadTextFormat = useCallback(
    async (format: "json" | "md") => {
      setDownloading(format);
      setError(null);

      try {
        const response = await api.getNewsletterContent(runId, {
          run_type: runType,
          format,
        });

        const content =
          format === "json" ? response.content_json : response.content_md;

        if (!content) {
          throw new Error(`No ${format.toUpperCase()} content available`);
        }

        const filename = generateFilename(dataSource, startDate, endDate, format);
        downloadBlob(content, filename, MIME_TYPES[format]);
      } catch (err) {
        const message =
          err instanceof Error ? err.message : `Failed to download ${format}`;
        setError(message);
        console.error(`Download ${format} error:`, err);
      } finally {
        setDownloading(null);
      }
    },
    [runId, runType, dataSource, startDate, endDate]
  );

  /**
   * Generates and downloads PDF from HTML content.
   */
  const downloadPdf = useCallback(async () => {
    setDownloading("pdf");
    setError(null);

    try {
      const response = await api.getNewsletterContent(runId, {
        run_type: runType,
        format: "html",
      });

      if (!response.content_html) {
        throw new Error("No HTML content available for PDF generation");
      }

      const bodyContent = extractBodyContent(response.content_html);
      const filename = generateFilename(dataSource, startDate, endDate, "pdf");

      // Create a temporary container for PDF generation
      const container = document.createElement("div");
      container.innerHTML = bodyContent;
      container.style.padding = "20px";
      container.style.fontFamily = "Arial, sans-serif";
      container.style.direction = response.direction || "ltr";

      // Configure html2pdf options
      const options = {
        margin: 10,
        filename,
        image: { type: "jpeg" as const, quality: 0.98 },
        html2canvas: {
          scale: 2,
          useCORS: true,
          letterRendering: true,
        },
        jsPDF: {
          unit: "mm" as const,
          format: "a4" as const,
          orientation: "portrait" as const,
        },
        pagebreak: { mode: ["avoid-all", "css", "legacy"] as const },
      };

      await html2pdf().set(options).from(container).save();
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to generate PDF";
      setError(message);
      console.error("Download PDF error:", err);
    } finally {
      setDownloading(null);
    }
  }, [runId, runType, dataSource, startDate, endDate]);

  /**
   * Handles download based on selected format.
   */
  const handleDownload = useCallback(
    (format: DownloadFormat) => {
      if (format === "pdf") {
        downloadPdf();
      } else {
        downloadTextFormat(format);
      }
    },
    [downloadPdf, downloadTextFormat]
  );

  const isDownloading = downloading !== null;

  return (
    <>
      <Dropdown>
        <Dropdown.Toggle
          variant="outline-secondary"
          size={size}
          disabled={disabled || isDownloading}
          id={`download-dropdown-${runId}`}
        >
          {isDownloading ? (
            <>
              <Spinner animation="border" size="sm" className="me-1" />
              {downloading === "pdf" ? "Generating..." : "Downloading..."}
            </>
          ) : (
            "Download"
          )}
        </Dropdown.Toggle>

        <Dropdown.Menu>
          <Dropdown.Item
            onClick={() => handleDownload("json")}
            disabled={isDownloading}
          >
            {downloading === "json" ? (
              <Spinner animation="border" size="sm" className="me-2" />
            ) : (
              <span className="me-2">{ }</span>
            )}
            JSON
          </Dropdown.Item>
          <Dropdown.Item
            onClick={() => handleDownload("md")}
            disabled={isDownloading}
          >
            {downloading === "md" ? (
              <Spinner animation="border" size="sm" className="me-2" />
            ) : (
              <span className="me-2">{ }</span>
            )}
            Markdown
          </Dropdown.Item>
          <Dropdown.Divider />
          <Dropdown.Item
            onClick={() => handleDownload("pdf")}
            disabled={isDownloading}
          >
            {downloading === "pdf" ? (
              <Spinner animation="border" size="sm" className="me-2" />
            ) : (
              <span className="me-2">{ }</span>
            )}
            PDF
          </Dropdown.Item>
        </Dropdown.Menu>
      </Dropdown>

      {error && (
        <div
          className="text-danger small mt-1"
          style={{ position: "absolute", whiteSpace: "nowrap" }}
        >
          {error}
        </div>
      )}
    </>
  );
};

export default DownloadDropdown;
