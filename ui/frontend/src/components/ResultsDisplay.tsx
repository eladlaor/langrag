/**
 * Results Display Component
 * Shows newsletter generation results with expandable details
 */

import React from "react";
import { Alert, Accordion, Badge, Card } from "react-bootstrap";
import { PeriodicNewsletterResponse, NewsletterResult } from "../types";

interface ResultsDisplayProps {
  results: PeriodicNewsletterResponse | null;
  type: "periodic";
}

export const ResultsDisplay: React.FC<ResultsDisplayProps> = ({ results, type }) => {
  if (!results) return null;

  const getResultsList = (): NewsletterResult[] => {
    if (!Array.isArray(results.results)) {
      throw new Error(`Invalid PeriodicNewsletterResponse: 'results' is not an array`);
    }
    return results.results;
  };

  const getSummaryStats = () => {
    return {
      total: results.total_chats,
      successful: results.successful_chats,
      failed: results.failed_chats,
    };
  };

  const stats = getSummaryStats();
  const resultsList = getResultsList();

  const getAlertVariant = () => {
    if (stats.failed === 0) return "success";
    if (stats.successful === 0) return "danger";
    return "warning";
  };

  return (
    <div className="mt-4">
      <Alert variant={getAlertVariant()}>
        <Alert.Heading>
          {stats.failed === 0 ? "✓ Success!" : stats.successful === 0 ? "✗ Failed" : "⚠ Partial Success"}
        </Alert.Heading>
        <p className="mb-0">
          {results.message} ({stats.successful}/{stats.total} successful)
        </p>
      </Alert>

      <Card>
        <Card.Header>
          <strong>Results Details</strong>
        </Card.Header>
        <Card.Body>
          <Accordion>
            {resultsList.map((result, index) => (
              <Accordion.Item eventKey={String(index)} key={index}>
                <Accordion.Header>
                  <div className="d-flex justify-content-between align-items-center w-100 me-3">
                    <span>
                      {result.chat_name}
                      {result.date && <small className="text-muted ms-2">({result.date})</small>}
                    </span>
                    <Badge bg={result.success ? "success" : "danger"}>
                      {result.success ? "Success" : "Failed"}
                    </Badge>
                  </div>
                </Accordion.Header>
                <Accordion.Body>
                  {result.success ? (
                    <div>
                      {result.message_count !== undefined && (
                        <p>
                          <strong>Messages:</strong> {result.message_count}
                        </p>
                      )}
                      {result.reused_existing !== undefined && (
                        <p>
                          <strong>Cached:</strong> {result.reused_existing ? "Yes" : "No"}
                        </p>
                      )}
                      {result.newsletter_md && (
                        <p>
                          <strong>Markdown:</strong>{" "}
                          <code className="small">{result.newsletter_md}</code>
                        </p>
                      )}
                      {result.newsletter_json && (
                        <p>
                          <strong>JSON:</strong>{" "}
                          <code className="small">{result.newsletter_json}</code>
                        </p>
                      )}
                      {result.translated_file && (
                        <p>
                          <strong>Translated:</strong>{" "}
                          <code className="small">{result.translated_file}</code>
                        </p>
                      )}
                    </div>
                  ) : (
                    <Alert variant="danger" className="mb-0">
                      <strong>Error:</strong> {result.error || "Unknown error occurred"}
                    </Alert>
                  )}
                </Accordion.Body>
              </Accordion.Item>
            ))}
          </Accordion>
        </Card.Body>
      </Card>
    </div>
  );
};
