/**
 * ExtractedImagesGallery - admin-only gallery of images shared in community chats.
 *
 * Browses extracted images filtered by any combination of community, chat,
 * date range, and discussion. Each card shows the image plus short metadata
 * (source group, timestamp, sender) and an expandable accordion linking the
 * image to its associated discussion. Image bytes are served by the admin-gated
 * /api/media/images/{id} endpoint. Renders an access note for non-admins.
 *
 * This is a minimal infrastructure-first surface; the interface is expected to
 * evolve. Filters, pagination, and the data contract are the stable parts.
 */

import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  Accordion,
  Alert,
  Badge,
  Button,
  Card,
  Col,
  Form,
  Row,
  Spinner,
} from "react-bootstrap";
import { useAuth } from "../../contexts/AuthContext";
import { api, ApiError } from "../../services/api";
import { ExtractedImageItem, ExtractedImagesQuery } from "../../types";
import {
  API_BASE_URL,
  DATA_SOURCES,
  KNOWN_WHATSAPP_CHAT_NAMES,
} from "../../constants";
import { logger } from "../../utils/logger";

const LOG_COMPONENT = "ExtractedImagesGallery";
const PAGE_SIZE = 60;
const ANY_VALUE = "";

interface Filters {
  dataSourceName: string;
  chatName: string;
  startDate: string;
  endDate: string;
}

const EMPTY_FILTERS: Filters = {
  dataSourceName: ANY_VALUE,
  chatName: ANY_VALUE,
  startDate: ANY_VALUE,
  endDate: ANY_VALUE,
};

function formatTimestamp(ms: number | null): string {
  if (!ms) return "Unknown date";
  try {
    return new Date(ms).toLocaleString();
  } catch {
    return "Unknown date";
  }
}

function buildQuery(filters: Filters, offset: number): ExtractedImagesQuery {
  return {
    data_source_name: filters.dataSourceName || undefined,
    chat_name: filters.chatName || undefined,
    start_date: filters.startDate || undefined,
    end_date: filters.endDate || undefined,
    limit: PAGE_SIZE,
    offset,
  };
}

export const ExtractedImagesGallery: React.FC = () => {
  const { isAdmin } = useAuth();
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [images, setImages] = useState<ExtractedImageItem[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Chats available for the selected community (or all chats when none chosen).
  const chatOptions = useMemo<string[]>(() => {
    if (!filters.dataSourceName) {
      return Object.values(KNOWN_WHATSAPP_CHAT_NAMES).flat();
    }
    return KNOWN_WHATSAPP_CHAT_NAMES[filters.dataSourceName] ?? [];
  }, [filters.dataSourceName]);

  const loadImages = useCallback(
    async (nextOffset: number) => {
      setLoading(true);
      setError(null);
      logger.info("Loading extracted images", { component: LOG_COMPONENT, filters, offset: nextOffset });
      try {
        const response = await api.listExtractedImages(buildQuery(filters, nextOffset));
        setImages(response.images);
        setTotal(response.total);
        setOffset(response.offset);
        logger.info("Loaded extracted images", { component: LOG_COMPONENT, returned: response.images.length, total: response.total });
      } catch (err) {
        const message = err instanceof ApiError ? err.message : "Failed to load images";
        setError(message);
        logger.error("Failed to load extracted images", { component: LOG_COMPONENT, error: message });
      } finally {
        setLoading(false);
      }
    },
    [filters]
  );

  // Load the first page on mount.
  useEffect(() => {
    void loadImages(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onApplyFilters = (e: React.FormEvent) => {
    e.preventDefault();
    void loadImages(0);
  };

  const onResetFilters = () => {
    setFilters(EMPTY_FILTERS);
  };

  const onPrevPage = () => {
    const prev = Math.max(0, offset - PAGE_SIZE);
    void loadImages(prev);
  };

  const onNextPage = () => {
    void loadImages(offset + PAGE_SIZE);
  };

  if (!isAdmin) {
    return (
      <Alert variant="warning" className="mt-3">
        Extracted Images is an admin-only view.
      </Alert>
    );
  }

  const pageStart = total === 0 ? 0 : offset + 1;
  const pageEnd = Math.min(offset + PAGE_SIZE, total);
  const hasPrev = offset > 0;
  const hasNext = offset + PAGE_SIZE < total;

  return (
    <div className="mt-3">
      <Card className="mb-4">
        <Card.Body>
          <Form onSubmit={onApplyFilters}>
            <Row className="g-3 align-items-end">
              <Col md={3}>
                <Form.Label>Community</Form.Label>
                <Form.Select
                  value={filters.dataSourceName}
                  onChange={(e) => setFilters((f) => ({ ...f, dataSourceName: e.target.value, chatName: ANY_VALUE }))}
                >
                  <option value={ANY_VALUE}>All communities</option>
                  {DATA_SOURCES.map((ds) => (
                    <option key={ds.value} value={ds.value}>
                      {ds.label}
                    </option>
                  ))}
                </Form.Select>
              </Col>
              <Col md={3}>
                <Form.Label>Chat group</Form.Label>
                <Form.Select
                  value={filters.chatName}
                  onChange={(e) => setFilters((f) => ({ ...f, chatName: e.target.value }))}
                >
                  <option value={ANY_VALUE}>All chats</option>
                  {chatOptions.map((chat) => (
                    <option key={chat} value={chat}>
                      {chat}
                    </option>
                  ))}
                </Form.Select>
              </Col>
              <Col md={2}>
                <Form.Label>From</Form.Label>
                <Form.Control
                  type="date"
                  value={filters.startDate}
                  onChange={(e) => setFilters((f) => ({ ...f, startDate: e.target.value }))}
                />
              </Col>
              <Col md={2}>
                <Form.Label>To</Form.Label>
                <Form.Control
                  type="date"
                  value={filters.endDate}
                  onChange={(e) => setFilters((f) => ({ ...f, endDate: e.target.value }))}
                />
              </Col>
              <Col md={2} className="d-flex gap-2">
                <Button type="submit" variant="primary" disabled={loading}>
                  Apply
                </Button>
                <Button type="button" variant="outline-secondary" onClick={onResetFilters} disabled={loading}>
                  Reset
                </Button>
              </Col>
            </Row>
          </Form>
        </Card.Body>
      </Card>

      {error && <Alert variant="danger">{error}</Alert>}

      {loading ? (
        <div className="text-center py-5">
          <Spinner animation="border" role="status" />
        </div>
      ) : (
        <>
          <div className="d-flex justify-content-between align-items-center mb-3">
            <span className="text-muted">
              {total === 0 ? "No images found" : `Showing ${pageStart}–${pageEnd} of ${total}`}
            </span>
            <div className="d-flex gap-2">
              <Button variant="outline-secondary" size="sm" onClick={onPrevPage} disabled={!hasPrev}>
                Previous
              </Button>
              <Button variant="outline-secondary" size="sm" onClick={onNextPage} disabled={!hasNext}>
                Next
              </Button>
            </div>
          </div>

          <Row className="g-3">
            {images.map((img) => (
              <Col key={img.image_id} xs={12} sm={6} md={4} lg={3}>
                <Card className="h-100">
                  <Card.Img
                    variant="top"
                    src={`${API_BASE_URL || ""}${img.image_url}`}
                    alt={img.description || img.filename || "Extracted image"}
                    loading="lazy"
                    style={{ objectFit: "cover", height: "180px", background: "#f4f4f4" }}
                  />
                  <Card.Body className="d-flex flex-column">
                    <div className="mb-2">
                      <Badge bg="secondary" className="me-1">
                        {img.chat_name || "Unknown chat"}
                      </Badge>
                      {img.data_source_name && <Badge bg="light" text="dark">{img.data_source_name}</Badge>}
                    </div>
                    <small className="text-muted d-block">{formatTimestamp(img.timestamp)}</small>
                    {img.sender_id && <small className="text-muted d-block text-truncate">From: {img.sender_id}</small>}
                    {img.description && <p className="small mt-2 mb-2">{img.description}</p>}

                    <Accordion className="mt-auto">
                      <Accordion.Item eventKey="discussion">
                        <Accordion.Header>
                          {img.discussion_id ? "Discussion" : "No discussion linked"}
                        </Accordion.Header>
                        <Accordion.Body>
                          {img.discussion_id ? (
                            <>
                              <div className="fw-semibold">{img.discussion_title || "(untitled discussion)"}</div>
                              <small className="text-muted">ID: {img.discussion_id}</small>
                            </>
                          ) : (
                            <small className="text-muted">This image was not associated with any discussion.</small>
                          )}
                        </Accordion.Body>
                      </Accordion.Item>
                    </Accordion>
                  </Card.Body>
                </Card>
              </Col>
            ))}
          </Row>
        </>
      )}
    </div>
  );
};
