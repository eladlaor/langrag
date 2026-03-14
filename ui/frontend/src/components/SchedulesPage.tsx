/**
 * Schedules Page Component
 *
 * Manages scheduled newsletter generation via n8n automation.
 * Allows users to create, view, edit, and delete newsletter schedules.
 */

import React, { useState } from "react";
import {
  Container,
  Row,
  Col,
  Card,
  Button,
  Form,
  Table,
  Badge,
  Modal,
  Alert,
  Spinner,
} from "react-bootstrap";
import { useForm, Controller } from "react-hook-form";
import { useSchedules, Schedule, CreateScheduleRequest } from "../hooks/useSchedules";
import { ChatSelector } from "./shared/ChatSelector";
import {
  COMMUNITY_STRUCTURE,
  DATA_SOURCES,
  SUMMARY_FORMATS,
  LANGUAGES,
} from "../constants";

// Interval options for schedule frequency
const INTERVAL_OPTIONS = [
  { value: 1, label: "Daily" },
  { value: 3, label: "Every 3 days" },
  { value: 7, label: "Weekly" },
  { value: 14, label: "Every 2 weeks" },
  { value: 30, label: "Monthly" },
];

interface ScheduleFormData {
  name: string;
  interval_days: number;
  run_time: string;
  data_source_name: string;
  desired_language_for_summary: string;
  summary_format: string;
  email_recipients: string;
  consolidate_chats: boolean;
}

export const SchedulesPage: React.FC = () => {
  const {
    schedules,
    loading,
    error,
    createSchedule,
    deleteSchedule,
    toggleSchedule,
    refresh,
  } = useSchedules();

  const [showCreateModal, setShowCreateModal] = useState(false);
  const [selectedChats, setSelectedChats] = useState<string[]>([]);
  const [formError, setFormError] = useState<string | null>(null);
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    watch,
    reset,
    formState: { errors },
  } = useForm<ScheduleFormData>({
    defaultValues: {
      name: "",
      interval_days: 7,
      run_time: "08:00",
      data_source_name: "langtalks",
      desired_language_for_summary: "english",
      summary_format: "langtalks_format",
      email_recipients: "",
      consolidate_chats: true,
    },
  });

  const dataSource = (watch("data_source_name") || "langtalks") as keyof typeof COMMUNITY_STRUCTURE;

  const handleCreateSchedule = async (data: ScheduleFormData) => {
    setFormError(null);

    if (selectedChats.length === 0) {
      setFormError("Please select at least one chat");
      return;
    }

    if (!data.email_recipients.trim()) {
      setFormError("Email recipients are required");
      return;
    }

    // Parse email recipients (comma-separated)
    const emails = data.email_recipients
      .split(",")
      .map((e) => e.trim())
      .filter((e) => e.length > 0);

    // Basic email validation
    const invalidEmails = emails.filter(
      (e) => !e.includes("@") || !e.includes(".")
    );
    if (invalidEmails.length > 0) {
      setFormError(`Invalid email format: ${invalidEmails.join(", ")}`);
      return;
    }

    const request: CreateScheduleRequest = {
      name: data.name,
      interval_days: data.interval_days,
      run_time: data.run_time,
      data_source_name: data.data_source_name,
      whatsapp_chat_names_to_include: selectedChats,
      email_recipients: emails,
      desired_language_for_summary: data.desired_language_for_summary,
      summary_format: data.summary_format,
      consolidate_chats: data.consolidate_chats,
    };

    const success = await createSchedule(request);
    if (success) {
      setShowCreateModal(false);
      reset();
      setSelectedChats([]);
    }
  };

  const handleDeleteSchedule = async (scheduleId: string) => {
    await deleteSchedule(scheduleId);
    setDeleteConfirmId(null);
  };

  const handleToggleSchedule = async (scheduleId: string) => {
    await toggleSchedule(scheduleId);
  };

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return "Never";
    const date = new Date(dateStr);
    return date.toLocaleString();
  };

  const getStatusBadge = (schedule: Schedule) => {
    if (!schedule.enabled) {
      return <Badge bg="secondary">Disabled</Badge>;
    }
    if (schedule.last_run_status === "failed") {
      return <Badge bg="danger">Last Run Failed</Badge>;
    }
    return <Badge bg="success">Active</Badge>;
  };

  return (
    <Container fluid className="py-4">
      <Row className="mb-4">
        <Col>
          <div className="d-flex justify-content-between align-items-center">
            <div>
              <h2>Scheduled Newsletters</h2>
              <p className="text-muted mb-0">
                Automate newsletter generation with scheduled runs
              </p>
            </div>
            <div>
              <Button
                variant="outline-secondary"
                className="me-2"
                onClick={refresh}
                disabled={loading}
              >
                {loading ? (
                  <Spinner animation="border" size="sm" />
                ) : (
                  "Refresh"
                )}
              </Button>
              <Button
                variant="primary"
                onClick={() => setShowCreateModal(true)}
              >
                + Create Schedule
              </Button>
            </div>
          </div>
        </Col>
      </Row>

      {error && (
        <Alert variant="danger" dismissible onClose={() => {}}>
          {error}
        </Alert>
      )}

      {/* Schedules List */}
      <Card>
        <Card.Header>
          <strong>Active Schedules</strong>
          <span className="text-muted ms-2">({schedules.length})</span>
        </Card.Header>
        <Card.Body className="p-0">
          {loading && schedules.length === 0 ? (
            <div className="text-center py-5">
              <Spinner animation="border" />
              <p className="mt-2 text-muted">Loading schedules...</p>
            </div>
          ) : schedules.length === 0 ? (
            <div className="text-center py-5">
              <p className="text-muted mb-3">No schedules configured yet</p>
              <Button
                variant="primary"
                onClick={() => setShowCreateModal(true)}
              >
                Create Your First Schedule
              </Button>
            </div>
          ) : (
            <Table responsive hover className="mb-0">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Data Source</th>
                  <th>Frequency</th>
                  <th>Run Time</th>
                  <th>Next Run</th>
                  <th>Last Run</th>
                  <th>Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {schedules.map((schedule) => (
                  <tr key={schedule.id}>
                    <td>
                      <strong>{schedule.name}</strong>
                      <br />
                      <small className="text-muted">
                        {schedule.whatsapp_chat_names_to_include.length} chat(s)
                      </small>
                    </td>
                    <td>{schedule.data_source_name}</td>
                    <td>
                      {INTERVAL_OPTIONS.find(
                        (o) => o.value === schedule.interval_days
                      )?.label || `Every ${schedule.interval_days} days`}
                    </td>
                    <td>{schedule.run_time} UTC</td>
                    <td>{formatDate(schedule.next_run)}</td>
                    <td>
                      {formatDate(schedule.last_run)}
                      {schedule.run_count > 0 && (
                        <small className="text-muted d-block">
                          ({schedule.run_count} runs)
                        </small>
                      )}
                    </td>
                    <td>{getStatusBadge(schedule)}</td>
                    <td>
                      <Button
                        variant={schedule.enabled ? "outline-warning" : "outline-success"}
                        size="sm"
                        className="me-1"
                        onClick={() => handleToggleSchedule(schedule.id)}
                        title={schedule.enabled ? "Disable" : "Enable"}
                      >
                        {schedule.enabled ? "Pause" : "Resume"}
                      </Button>
                      <Button
                        variant="outline-danger"
                        size="sm"
                        onClick={() => setDeleteConfirmId(schedule.id)}
                        title="Delete"
                      >
                        Delete
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card.Body>
      </Card>

      {/* Info Card */}
      <Card className="mt-4">
        <Card.Header>
          <strong>How Scheduled Newsletters Work</strong>
        </Card.Header>
        <Card.Body>
          <Row>
            <Col md={4}>
              <h6>1. Create a Schedule</h6>
              <p className="text-muted small">
                Configure which chats to monitor, how often to generate
                newsletters, and where to send notifications.
              </p>
            </Col>
            <Col md={4}>
              <h6>2. Automated Execution</h6>
              <p className="text-muted small">
                The n8n workflow checks for due schedules every minute and
                triggers newsletter generation automatically.
              </p>
            </Col>
            <Col md={4}>
              <h6>3. Email Notification</h6>
              <p className="text-muted small">
                When the newsletter is ready, you'll receive an email with a
                link to view it directly in your browser.
              </p>
            </Col>
          </Row>
        </Card.Body>
      </Card>

      {/* Create Schedule Modal */}
      <Modal
        show={showCreateModal}
        onHide={() => {
          setShowCreateModal(false);
          setFormError(null);
          reset();
          setSelectedChats([]);
        }}
        size="lg"
      >
        <Modal.Header closeButton>
          <Modal.Title>Create Newsletter Schedule</Modal.Title>
        </Modal.Header>
        <Form onSubmit={handleSubmit(handleCreateSchedule)}>
          <Modal.Body>
            {formError && (
              <Alert variant="danger" dismissible onClose={() => setFormError(null)}>
                {formError}
              </Alert>
            )}

            <Row>
              <Col md={6}>
                <Form.Group className="mb-3">
                  <Form.Label>Schedule Name *</Form.Label>
                  <Form.Control
                    type="text"
                    {...register("name", { required: "Name is required" })}
                    placeholder="e.g., Weekly LangTalks Newsletter"
                    isInvalid={!!errors.name}
                  />
                  <Form.Control.Feedback type="invalid">
                    {errors.name?.message}
                  </Form.Control.Feedback>
                </Form.Group>
              </Col>
              <Col md={6}>
                <Form.Group className="mb-3">
                  <Form.Label>Data Source *</Form.Label>
                  <Form.Select
                    {...register("data_source_name", { required: true })}
                  >
                    {DATA_SOURCES.map((ds) => (
                      <option key={ds.value} value={ds.value}>
                        {ds.label}
                      </option>
                    ))}
                  </Form.Select>
                </Form.Group>
              </Col>
            </Row>

            <Row>
              <Col md={6}>
                <Form.Group className="mb-3">
                  <Form.Label>Frequency *</Form.Label>
                  <Form.Select
                    {...register("interval_days", {
                      required: true,
                      valueAsNumber: true,
                    })}
                  >
                    {INTERVAL_OPTIONS.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.label}
                      </option>
                    ))}
                  </Form.Select>
                </Form.Group>
              </Col>
              <Col md={6}>
                <Form.Group className="mb-3">
                  <Form.Label>Run Time (UTC) *</Form.Label>
                  <Form.Control
                    type="time"
                    {...register("run_time", { required: true })}
                  />
                  <Form.Text className="text-muted">
                    Newsletter will be generated at this time daily
                  </Form.Text>
                </Form.Group>
              </Col>
            </Row>

            <Form.Group className="mb-3">
              <Form.Label>WhatsApp Chats *</Form.Label>
              <ChatSelector
                dataSource={dataSource}
                selectedChats={selectedChats}
                onSelectionChange={setSelectedChats}
              />
            </Form.Group>

            <Row>
              <Col md={6}>
                <Form.Group className="mb-3">
                  <Form.Label>Summary Language</Form.Label>
                  <Form.Select {...register("desired_language_for_summary")}>
                    {LANGUAGES.map((lang) => (
                      <option key={lang.value} value={lang.value}>
                        {lang.label}
                      </option>
                    ))}
                  </Form.Select>
                </Form.Group>
              </Col>
              <Col md={6}>
                <Form.Group className="mb-3">
                  <Form.Label>Summary Format</Form.Label>
                  <Form.Select {...register("summary_format")}>
                    {SUMMARY_FORMATS.map((fmt) => (
                      <option key={fmt.value} value={fmt.value}>
                        {fmt.label}
                      </option>
                    ))}
                  </Form.Select>
                </Form.Group>
              </Col>
            </Row>

            <Form.Group className="mb-3">
              <Form.Label>Email Recipients *</Form.Label>
              <Form.Control
                type="text"
                {...register("email_recipients", {
                  required: "Email recipients are required",
                })}
                placeholder="email1@example.com, email2@example.com"
                isInvalid={!!errors.email_recipients}
              />
              <Form.Text className="text-muted">
                Comma-separated list of email addresses
              </Form.Text>
              <Form.Control.Feedback type="invalid">
                {errors.email_recipients?.message}
              </Form.Control.Feedback>
            </Form.Group>

            <Form.Group className="mb-3">
              <Form.Check
                type="checkbox"
                label="Consolidate chats into single newsletter"
                {...register("consolidate_chats")}
              />
              <Form.Text className="text-muted">
                When enabled, discussions from all selected chats will be
                combined into one newsletter
              </Form.Text>
            </Form.Group>
          </Modal.Body>
          <Modal.Footer>
            <Button
              variant="secondary"
              onClick={() => {
                setShowCreateModal(false);
                setFormError(null);
                reset();
                setSelectedChats([]);
              }}
            >
              Cancel
            </Button>
            <Button variant="primary" type="submit" disabled={loading}>
              {loading ? (
                <>
                  <Spinner animation="border" size="sm" className="me-2" />
                  Creating...
                </>
              ) : (
                "Create Schedule"
              )}
            </Button>
          </Modal.Footer>
        </Form>
      </Modal>

      {/* Delete Confirmation Modal */}
      <Modal
        show={deleteConfirmId !== null}
        onHide={() => setDeleteConfirmId(null)}
        centered
      >
        <Modal.Header closeButton>
          <Modal.Title>Confirm Delete</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          Are you sure you want to delete this schedule? This action cannot be
          undone.
        </Modal.Body>
        <Modal.Footer>
          <Button variant="secondary" onClick={() => setDeleteConfirmId(null)}>
            Cancel
          </Button>
          <Button
            variant="danger"
            onClick={() =>
              deleteConfirmId && handleDeleteSchedule(deleteConfirmId)
            }
            disabled={loading}
          >
            {loading ? (
              <>
                <Spinner animation="border" size="sm" className="me-2" />
                Deleting...
              </>
            ) : (
              "Delete Schedule"
            )}
          </Button>
        </Modal.Footer>
      </Modal>
    </Container>
  );
};
