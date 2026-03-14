/**
 * Periodic Newsletter Form Component
 */

import React, { useState } from "react";
import { Form, Button, Row, Col, Alert, Spinner } from "react-bootstrap";
import { useForm } from "react-hook-form";
import { ChatSelector } from "./shared/ChatSelector";
import { AdvancedOptions } from "./shared/AdvancedOptions";
import { ProgressTracker } from "./ProgressTracker";
import { OutputPathsDisplay } from "./OutputPathsDisplay";
import { api, ApiError } from "../services/api";
import { useNewsletterStream } from "../hooks/useNewsletterStream";
import { DATA_SOURCES, SUMMARY_FORMATS, LANGUAGES } from "../constants";
import { PeriodicNewsletterRequest, PeriodicNewsletterResponse, ForceRefreshFlags, OutputConfiguration, HITLConfiguration } from "../types";
import { NewsletterDiscussionSelector } from "./NewsletterDiscussionSelector";

interface FormData {
  start_date: string;
  end_date: string;
  data_source_name: "langtalks" | "mcp_israel" | "n8n_israel";
  desired_language_for_summary: string;
  summary_format: "langtalks_format" | "mcp_israel_format";
}

interface PeriodicNewsletterFormProps {
  onSuccess: (result: PeriodicNewsletterResponse) => void;
}

export const PeriodicNewsletterForm: React.FC<PeriodicNewsletterFormProps> = ({ onSuccess }) => {
  const { register, handleSubmit, watch, setValue, formState: { errors } } = useForm<FormData>();
  const [selectedChats, setSelectedChats] = useState<string[]>([]);
  const [forceRefresh, setForceRefresh] = useState<ForceRefreshFlags>({
    force_refresh_extraction: true,
    force_refresh_preprocessing: true,
    force_refresh_translation: true,
    force_refresh_separate_discussions: true,
    force_refresh_content: true,
    force_refresh_final_translation: true,
  });
  const [outputConfig, setOutputConfig] = useState<OutputConfiguration>({
    output_actions: ["save_local"],
    webhook_url: "",
    email_recipients: "",
    substack_blog_id: "",
  });
  const [hitlConfig, setHitlConfig] = useState<HITLConfiguration>({
    enabled: false,
    timeoutMinutes: 60,  // Default: 1 hour
  });
  const [hitlRunDirectory, setHitlRunDirectory] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Using streaming hook for real-time progress
  const { state: streamState, start: startStream, cancel: cancelStream } = useNewsletterStream();

  const dataSource = watch("data_source_name") || "langtalks";

  // Showing completed result via onSuccess callback
  React.useEffect(() => {
    if (streamState.status === 'completed' && streamState.result) {
      onSuccess(streamState.result);
    }
  }, [streamState.status, streamState.result, onSuccess]);

  const onSubmit = async (data: FormData) => {
    if (selectedChats.length === 0) {
      setError("Please select at least one chat");
      return;
    }

    if (outputConfig.output_actions.length === 0) {
      setError("Please select at least one output action");
      return;
    }

    // Validating required conditional fields
    if (outputConfig.output_actions.includes("webhook") && !outputConfig.webhook_url.trim()) {
      setError("Webhook URL is required when using webhook output");
      return;
    }

    if (outputConfig.output_actions.includes("send_email") && !outputConfig.email_recipients.trim()) {
      setError("Email recipients are required when using email output");
      return;
    }

    if (outputConfig.output_actions.includes("send_substack") && !outputConfig.substack_blog_id.trim()) {
      setError("Substack Blog ID is required when using Substack output");
      return;
    }

    setError(null);

    try {
      const requestData: PeriodicNewsletterRequest = {
        ...data,
        whatsapp_chat_names_to_include: selectedChats,
        ...forceRefresh,
        output_actions: outputConfig.output_actions,
      };

      // Adding conditional fields
      if (outputConfig.output_actions.includes("webhook") && outputConfig.webhook_url) {
        requestData.webhook_url = outputConfig.webhook_url;
      }

      if (outputConfig.output_actions.includes("send_email") && outputConfig.email_recipients) {
        const emails = outputConfig.email_recipients
          .split(",")
          .map(e => e.trim())
          .filter(e => e.length > 0);

        if (emails.length === 0) {
          setError("At least one valid email recipient is required");
          return;
        }

        requestData.email_recipients = emails;
      }

      if (outputConfig.output_actions.includes("send_substack") && outputConfig.substack_blog_id) {
        requestData.substack_blog_id = outputConfig.substack_blog_id;
      }

      // Adding HITL configuration
      requestData.hitl_selection_timeout_minutes = hitlConfig.enabled ? hitlConfig.timeoutMinutes : 0;

      // Starting streaming workflow
      startStream(requestData);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(`Error ${err.status}: ${err.message}`);
      } else {
        console.error('Unexpected error during newsletter generation:', err);
        setError(`Unexpected error: ${err instanceof Error ? err.message : String(err)}`);
      }
    }
  };

  const handleReset = () => {
    setError(null);
  };

  // Showing progress tracker when workflow is running (including reconnecting)
  if (streamState.status === 'running' || streamState.status === 'connecting' || streamState.status === 'reconnecting') {
    return (
      <div>
        {error && <Alert variant="danger">{error}</Alert>}
        {streamState.error && <Alert variant="danger">{streamState.error}</Alert>}
        {streamState.status === 'reconnecting' && (
          <Alert variant="warning">
            Connection lost. Attempting to reconnect...
          </Alert>
        )}
        <ProgressTracker state={streamState} onCancel={cancelStream} />
      </div>
    );
  }

  // Showing results when workflow completed
  if (streamState.status === 'completed') {
    return (
      <div>
        <Alert variant="success">
          <h5 className="mb-2">✓ Newsletter Generated Successfully!</h5>
          <p className="mb-0">
            {streamState.completedChats} of {streamState.totalChats} chats processed successfully
            {streamState.failedChats > 0 && ` (${streamState.failedChats} failed)`}
          </p>
        </Alert>
        <OutputPathsDisplay state={streamState} />
        <Button
          variant="primary"
          className="w-100 mt-3"
          onClick={handleReset}
        >
          Generate Another Newsletter
        </Button>
      </div>
    );
  }

  // Showing error state
  if (streamState.status === 'error') {
    return (
      <div>
        <Alert variant="danger">
          <h5 className="mb-2">✗ Newsletter Generation Failed</h5>
          <p className="mb-0">{streamState.error || 'An unknown error occurred'}</p>
        </Alert>
        <Button
          variant="primary"
          className="w-100 mt-3"
          onClick={handleReset}
        >
          Try Again
        </Button>
      </div>
    );
  }

  // Showing HITL Discussion Selection UI
  if (streamState.status === 'hitl_selection' && streamState.hitlRunDirectory) {
    return (
      <div>
        <Alert variant="info">
          <h5 className="mb-2">📋 Phase 1 Complete - Select Discussions</h5>
          <p className="mb-0">
            The system has ranked all discussions. Please select the ones you want to include in the final newsletter.
          </p>
          {streamState.hitlSelectionDeadline && (
            <p className="mb-0 mt-2">
              <small className="text-muted">
                Selection expires: {new Date(streamState.hitlSelectionDeadline).toLocaleString()}
              </small>
            </p>
          )}
        </Alert>
        <NewsletterDiscussionSelector
          runDirectory={streamState.hitlRunDirectory}
          onGenerationComplete={(result) => {
            // After Phase 2 completes, showing success
            onSuccess({
              message: result.message,
              total_chats: streamState.totalChats,
              successful_chats: streamState.completedChats,
              failed_chats: streamState.failedChats,
              results: [],
            });
            handleReset();
          }}
        />
        <Button
          variant="outline-secondary"
          className="w-100 mt-3"
          onClick={handleReset}
        >
          Cancel and Start Over
        </Button>
      </div>
    );
  }

  // Default: Showing form
  return (
    <Form onSubmit={handleSubmit(onSubmit)}>
      {error && <Alert variant="danger">{error}</Alert>}

      <Row>
        <Col md={6}>
          <Form.Group className="mb-3">
            <Form.Label>Start Date</Form.Label>
            <Form.Control
              type="date"
              {...register("start_date", { required: "Start date is required" })}
              isInvalid={!!errors.start_date}
            />
            <Form.Control.Feedback type="invalid">
              {errors.start_date?.message}
            </Form.Control.Feedback>
          </Form.Group>
        </Col>
        <Col md={6}>
          <Form.Group className="mb-3">
            <Form.Label>End Date</Form.Label>
            <Form.Control
              type="date"
              {...register("end_date", {
                required: "End date is required",
                validate: (value) => {
                  const startDate = watch("start_date");
                  if (startDate && value < startDate) {
                    return "End date must be after or equal to start date";
                  }
                  return true;
                }
              })}
              isInvalid={!!errors.end_date}
            />
            <Form.Control.Feedback type="invalid">
              {errors.end_date?.message}
            </Form.Control.Feedback>
          </Form.Group>
        </Col>
      </Row>

      <Form.Group className="mb-3">
        <Form.Label>Data Source</Form.Label>
        <Form.Select
          {...register("data_source_name", { required: true })}
          onChange={(e) => {
            setValue("data_source_name", e.target.value as "langtalks" | "mcp_israel" | "n8n_israel");
            setSelectedChats([]); // Resetting chats after form update
          }}
        >
          {DATA_SOURCES.map(({ value, label }) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </Form.Select>
      </Form.Group>

      <ChatSelector
        dataSource={dataSource}
        selectedChats={selectedChats}
        onChange={setSelectedChats}
      />

      <Row>
        <Col md={6}>
          <Form.Group className="mb-3">
            <Form.Label>Summary Language</Form.Label>
            <Form.Select {...register("desired_language_for_summary", { required: true })}>
              {LANGUAGES.map(({ value, label }) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </Form.Select>
          </Form.Group>
        </Col>
        <Col md={6}>
          <Form.Group className="mb-3">
            <Form.Label>Summary Format</Form.Label>
            <Form.Select {...register("summary_format", { required: true })}>
              {SUMMARY_FORMATS.map(({ value, label }) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </Form.Select>
          </Form.Group>
        </Col>
      </Row>

      {/* HITL Discussion Selection Section */}
      <Form.Group className="mb-3 p-3 border rounded bg-light">
        <Form.Check
          type="switch"
          id="hitl-enabled"
          label={
            <span>
              <strong>Enable Human-in-the-Loop Discussion Selection</strong>
              <br />
              <small className="text-muted">
                Pause after ranking to manually select which discussions to include in the newsletter
              </small>
            </span>
          }
          checked={hitlConfig.enabled}
          onChange={(e) => setHitlConfig({ ...hitlConfig, enabled: e.target.checked })}
        />

        {hitlConfig.enabled && (
          <div className="mt-3 ms-4">
            <Form.Label>Selection Timeout</Form.Label>
            <Form.Select
              value={hitlConfig.timeoutMinutes}
              onChange={(e) => setHitlConfig({ ...hitlConfig, timeoutMinutes: parseInt(e.target.value) })}
              style={{ width: "auto" }}
            >
              <option value={15}>15 minutes</option>
              <option value={30}>30 minutes</option>
              <option value={60}>1 hour</option>
              <option value={120}>2 hours</option>
              <option value={240}>4 hours</option>
              <option value={480}>8 hours</option>
              <option value={1440}>24 hours</option>
            </Form.Select>
            <Form.Text className="text-muted">
              How long to wait for your selection before the workflow times out
            </Form.Text>
          </div>
        )}
      </Form.Group>

      <AdvancedOptions
        forceRefresh={forceRefresh}
        outputConfig={outputConfig}
        dataSource={dataSource}
        onForceRefreshChange={setForceRefresh}
        onOutputConfigChange={setOutputConfig}
      />

      <Button type="submit" variant="primary" disabled={streamState.status !== 'idle'} className="w-100">
        {streamState.status !== 'idle' ? (
          <>
            <Spinner as="span" animation="border" size="sm" className="me-2" />
            Generating Newsletter...
          </>
        ) : (
          "Generate Newsletter"
        )}
      </Button>
    </Form>
  );
};
