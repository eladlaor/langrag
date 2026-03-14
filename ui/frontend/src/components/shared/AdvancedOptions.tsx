/**
 * Advanced options component with collapsible section
 */

import React, { useState } from "react";
import { Form, Collapse, Card } from "react-bootstrap";
import {
  FORCE_REFRESH_OPTIONS,
  OUTPUT_ACTIONS,
  UNIVERSAL_OUTPUT_ACTIONS,
  COMMUNITY_ALLOWED_OUTPUT_ACTIONS,
} from "../../constants";
import { ForceRefreshFlags, OutputConfiguration } from "../../types";

interface AdvancedOptionsProps {
  forceRefresh: ForceRefreshFlags;
  outputConfig: OutputConfiguration;
  dataSource: string;
  onForceRefreshChange: (flags: ForceRefreshFlags) => void;
  onOutputConfigChange: (config: OutputConfiguration) => void;
}

export const AdvancedOptions: React.FC<AdvancedOptionsProps> = ({
  forceRefresh,
  outputConfig,
  dataSource,
  onForceRefreshChange,
  onOutputConfigChange,
}) => {
  const [isOpen, setIsOpen] = useState(false);

  const handleForceRefreshChange = (key: keyof ForceRefreshFlags) => {
    onForceRefreshChange({
      ...forceRefresh,
      [key]: !forceRefresh[key],
    });
  };

  const handleSelectAllForceRefresh = () => {
    const allSelected = Object.values(forceRefresh).every(Boolean);
    const newValue = !allSelected;

    onForceRefreshChange({
      force_refresh_extraction: newValue,
      force_refresh_preprocessing: newValue,
      force_refresh_translation: newValue,
      force_refresh_separate_discussions: newValue,
      force_refresh_content: newValue,
      force_refresh_final_translation: newValue,
    });
  };

  const allForceRefreshSelected = Object.values(forceRefresh).every(Boolean);

  // Compute which output actions are allowed for the selected community
  const communityActions = COMMUNITY_ALLOWED_OUTPUT_ACTIONS[dataSource] || [];
  const allowedActions = [...UNIVERSAL_OUTPUT_ACTIONS, ...communityActions];

  const handleOutputActionChange = (action: string) => {
    const actions = outputConfig.output_actions || [];
    const newActions = actions.includes(action)
      ? actions.filter((a) => a !== action)
      : [...actions, action];

    onOutputConfigChange({
      ...outputConfig,
      output_actions: newActions,
    });
  };

  const showWebhookField = outputConfig.output_actions?.includes("webhook");
  const showEmailField = outputConfig.output_actions?.includes("send_email");
  const showSubstackField = outputConfig.output_actions?.includes("send_substack");

  return (
    <Card className="mb-3">
      <Card.Header>
        <button
          type="button"
          className="btn btn-link text-decoration-none p-0 w-100 text-start"
          onClick={() => setIsOpen(!isOpen)}
          aria-controls="advanced-options-collapse"
          aria-expanded={isOpen}
        >
          <strong>Advanced Options</strong> {isOpen ? "▲" : "▼"}
        </button>
      </Card.Header>
      <Collapse in={isOpen}>
        <div id="advanced-options-collapse">
          <Card.Body>
            {/* Force Refresh Options */}
            <div className="d-flex justify-content-between align-items-center mb-3">
              <h6 className="mb-0">Force Refresh</h6>
              <button
                type="button"
                className="btn btn-sm btn-outline-secondary"
                onClick={handleSelectAllForceRefresh}
              >
                {allForceRefreshSelected ? "Deselect All" : "Select All"}
              </button>
            </div>
            <div className="mb-3">
              {FORCE_REFRESH_OPTIONS.map(({ key, label }) => (
                <Form.Check
                  key={key}
                  type="checkbox"
                  id={`refresh-${key}`}
                  label={label}
                  checked={forceRefresh[key as keyof ForceRefreshFlags]}
                  onChange={() => handleForceRefreshChange(key as keyof ForceRefreshFlags)}
                />
              ))}
            </div>

            <hr />

            {/* Output Actions - filtered by community */}
            <h6 className="mb-3">Output Actions</h6>
            <div className="mb-3">
              {OUTPUT_ACTIONS.filter(({ value }) => allowedActions.includes(value)).map(({ value, label }) => (
                <Form.Check
                  key={value}
                  type="checkbox"
                  id={`output-${value}`}
                  label={label}
                  checked={outputConfig.output_actions?.includes(value) || false}
                  onChange={() => handleOutputActionChange(value)}
                />
              ))}
            </div>

            {/* Conditional Fields */}
            {showWebhookField && (
              <Form.Group className="mb-3">
                <Form.Label>Webhook URL</Form.Label>
                <Form.Control
                  type="url"
                  placeholder="https://your-webhook.com/endpoint"
                  value={outputConfig.webhook_url || ""}
                  onChange={(e) =>
                    onOutputConfigChange({ ...outputConfig, webhook_url: e.target.value })
                  }
                />
              </Form.Group>
            )}

            {showEmailField && (
              <Form.Group className="mb-3">
                <Form.Label>Email Recipients (comma-separated)</Form.Label>
                <Form.Control
                  type="text"
                  placeholder="user@example.com, admin@example.com"
                  value={outputConfig.email_recipients || ""}
                  onChange={(e) =>
                    onOutputConfigChange({ ...outputConfig, email_recipients: e.target.value })
                  }
                />
              </Form.Group>
            )}

            {showSubstackField && (
              <Form.Group className="mb-3">
                <Form.Label>Substack Blog ID</Form.Label>
                <Form.Control
                  type="text"
                  placeholder="your-blog-id"
                  value={outputConfig.substack_blog_id || ""}
                  onChange={(e) =>
                    onOutputConfigChange({ ...outputConfig, substack_blog_id: e.target.value })
                  }
                />
              </Form.Group>
            )}
          </Card.Body>
        </div>
      </Collapse>
    </Card>
  );
};
