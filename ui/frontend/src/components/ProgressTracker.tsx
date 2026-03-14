/**
 * ProgressTracker Component
 *
 * Displays real-time progress for newsletter generation workflow.
 * Shows overall progress, per-chat stage-by-stage status, and consolidation progress.
 */

import React, { useState } from 'react';
import { Card, ProgressBar, Badge, Collapse, Button, Spinner } from 'react-bootstrap';
import { ChatProgress, ProgressState, ConsolidationProgress } from '../types';

interface ProgressTrackerProps {
  state: ProgressState;
  onCancel?: () => void;
}

// Per-chat pipeline stages
const STAGE_LABELS: Record<string, string> = {
  extract_messages: 'Extract',
  preprocess_messages: 'Preprocess',
  translate_messages: 'Translate',
  separate_discussions: 'Separate',
  rank_discussions: 'Rank',
  generate_content: 'Generate',
  enrich_with_links: 'Enrich',
  translate_final_summary: 'Translate Final',
};

// Consolidation stages (used when consolidate_chats=true, multi-chat mode)
const CONSOLIDATION_STAGE_LABELS: Record<string, string> = {
  setup_consolidated_directories: 'Setup',
  consolidate_discussions: 'Aggregate',
  rank_consolidated_discussions: 'Rank',
  generate_consolidated_newsletter: 'Generate',
  enrich_consolidated_newsletter: 'Enrich',
  translate_consolidated_newsletter: 'Translate',
};

const STAGE_ICONS: Record<string, string> = {
  pending: '⏸',
  in_progress: '⟳',
  completed: '✓',
  failed: '✗',
};

export const ProgressTracker: React.FC<ProgressTrackerProps> = ({ state, onCancel }) => {
  const [expandedChats, setExpandedChats] = useState<Set<string>>(new Set());
  const [consolidationExpanded, setConsolidationExpanded] = useState<boolean>(true);

  const toggleChat = (chatName: string) => {
    setExpandedChats((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(chatName)) {
        newSet.delete(chatName);
      } else {
        newSet.add(chatName);
      }
      return newSet;
    });
  };

  const getOverallProgress = (): number => {
    if (state.totalChats === 0) return 0;
    return Math.round(((state.completedChats + state.failedChats) / state.totalChats) * 100);
  };

  const getChatProgress = (chat: ChatProgress): number => {
    const totalStages = Object.keys(STAGE_LABELS).length;
    if (totalStages === 0) return 0;
    return Math.round((chat.completedStages.length / totalStages) * 100);
  };

  const getConsolidationProgress = (consolidation: ConsolidationProgress): number => {
    const totalStages = Object.keys(CONSOLIDATION_STAGE_LABELS).length;
    if (totalStages === 0) return 0;
    return Math.round((consolidation.completedStages.length / totalStages) * 100);
  };

  const getStatusVariant = (status: string): string => {
    switch (status) {
      case 'completed':
        return 'success';
      case 'failed':
        return 'danger';
      case 'in_progress':
        return 'primary';
      case 'reconnecting':
        return 'warning';
      default:
        return 'secondary';
    }
  };

  const chatsArray = Array.from(state.chats.values());

  return (
    <div className="progress-tracker">
      {/* Overall Progress Card */}
      <Card className="mb-3">
        <Card.Body>
          <div className="d-flex justify-content-between align-items-center mb-2">
            <h5 className="mb-0">📊 Overall Progress</h5>
            <div>
              <Badge bg={getStatusVariant(state.status)} className="me-2">
                {state.status === 'reconnecting' ? (
                  <>
                    <Spinner animation="border" size="sm" className="me-1" />
                    RECONNECTING
                  </>
                ) : (
                  state.status.toUpperCase()
                )}
              </Badge>
              {onCancel && (state.status === 'running' || state.status === 'reconnecting') && (
                <Button variant="outline-danger" size="sm" onClick={onCancel}>
                  Cancel
                </Button>
              )}
            </div>
          </div>
          <ProgressBar
            now={getOverallProgress()}
            label={`${state.completedChats + state.failedChats}/${state.totalChats} chats`}
            variant={state.failedChats > 0 ? 'warning' : 'success'}
            animated={state.status === 'running' || state.status === 'reconnecting'}
            className="mb-2"
          />
          <div className="small text-muted">
            {state.completedChats > 0 && (
              <span className="me-3">
                ✓ {state.completedChats} completed
              </span>
            )}
            {state.failedChats > 0 && (
              <span className="text-danger">
                ✗ {state.failedChats} failed
              </span>
            )}
            {(state.status === 'running' || state.status === 'reconnecting') && chatsArray.filter((c) => c.status === 'pending').length > 0 && (
              <span className="text-muted">
                • {chatsArray.filter((c) => c.status === 'pending').length} waiting
              </span>
            )}
          </div>
        </Card.Body>
      </Card>

      {/* Consolidation Progress Card (only shown when consolidation is active) */}
      {state.consolidation && (
        <Card className="mb-3 border-info">
          <Card.Header
            onClick={() => setConsolidationExpanded(!consolidationExpanded)}
            style={{ cursor: 'pointer' }}
            className="d-flex justify-content-between align-items-center bg-info bg-opacity-10"
            role="button"
            aria-expanded={consolidationExpanded}
          >
            <div className="d-flex align-items-center">
              <span className="me-2">{consolidationExpanded ? '▼' : '▶'}</span>
              <strong>🔗 Consolidation Progress</strong>
              <Badge bg={getStatusVariant(state.consolidation.status)} className="ms-2">
                {STAGE_ICONS[state.consolidation.status]} {state.consolidation.status}
              </Badge>
            </div>
            <span className="small text-muted">
              {state.consolidation.completedStages.length}/{Object.keys(CONSOLIDATION_STAGE_LABELS).length} stages
            </span>
          </Card.Header>
          <Collapse in={consolidationExpanded}>
            <div>
              <Card.Body>
                {/* Progress Bar */}
                <ProgressBar
                  now={getConsolidationProgress(state.consolidation)}
                  label={`${getConsolidationProgress(state.consolidation)}%`}
                  variant={getStatusVariant(state.consolidation.status)}
                  animated={state.consolidation.status === 'in_progress'}
                  className="mb-3"
                />

                {/* Current Message */}
                <div className="mb-3">
                  <strong className="small">Status:</strong>{' '}
                  <span className="text-muted">{state.consolidation.currentMessage}</span>
                </div>

                {/* Stage Pills */}
                <div className="d-flex flex-wrap gap-2 mb-3">
                  {Object.entries(CONSOLIDATION_STAGE_LABELS).map(([stageKey, label]) => {
                    let variant = 'light';
                    let icon = '';

                    if (state.consolidation!.completedStages.includes(stageKey)) {
                      variant = 'success';
                      icon = '✓ ';
                    } else if (state.consolidation!.currentStage === stageKey) {
                      variant = 'primary';
                      icon = '⟳ ';
                    }

                    return (
                      <Badge key={stageKey} bg={variant} className="px-2 py-1">
                        {icon}
                        {label}
                      </Badge>
                    );
                  })}
                </div>

                {/* Output Paths */}
                {Object.keys(state.consolidation.outputPaths).length > 0 && (
                  <div className="mt-3">
                    <strong className="small">Output Files:</strong>
                    <div className="small text-muted mt-1">
                      {Object.entries(state.consolidation.outputPaths).map(([stage, path]) => (
                        <div key={stage} className="mb-1">
                          <span className="badge bg-info me-1">
                            {CONSOLIDATION_STAGE_LABELS[stage] || stage}
                          </span>
                          <code className="text-break">{path}</code>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Error Display */}
                {state.consolidation.error && (
                  <div className="alert alert-danger mt-3 mb-0 small">
                    <strong>Error:</strong> {state.consolidation.error}
                  </div>
                )}
              </Card.Body>
            </div>
          </Collapse>
        </Card>
      )}

      {/* Per-Chat Progress Cards */}
      {chatsArray.map((chat) => {
        const isExpanded = expandedChats.has(chat.name);
        const progress = getChatProgress(chat);

        return (
          <Card key={chat.name} className="mb-2">
            <Card.Header
              onClick={() => toggleChat(chat.name)}
              style={{ cursor: 'pointer' }}
              className="d-flex justify-content-between align-items-center"
              role="button"
              aria-expanded={isExpanded}
              aria-controls={`chat-details-${chat.name.replace(/\s+/g, '-')}`}
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  toggleChat(chat.name);
                }
              }}
            >
              <div className="d-flex align-items-center">
                <span className="me-2">{isExpanded ? '▼' : '▶'}</span>
                <strong>{chat.name}</strong>
                <Badge bg={getStatusVariant(chat.status)} className="ms-2">
                  {STAGE_ICONS[chat.status]} {chat.status}
                </Badge>
              </div>
              <span className="small text-muted">
                {chat.completedStages.length}/{Object.keys(STAGE_LABELS).length} stages
              </span>
            </Card.Header>
            <Collapse in={isExpanded}>
              <div id={`chat-details-${chat.name.replace(/\s+/g, '-')}`}>
                <Card.Body>
                  {/* Progress Bar */}
                  <ProgressBar
                    now={progress}
                    label={`${progress}%`}
                    variant={getStatusVariant(chat.status)}
                    animated={chat.status === 'in_progress'}
                    className="mb-3"
                  />

                  {/* Current Message */}
                  <div className="mb-3">
                    <strong className="small">Status:</strong>{' '}
                    <span className="text-muted">{chat.currentMessage}</span>
                  </div>

                  {/* Stage Pills */}
                  <div className="d-flex flex-wrap gap-2 mb-3">
                    {Object.entries(STAGE_LABELS).map(([stageKey, label]) => {
                      let variant = 'light';
                      let icon = '';

                      if (chat.completedStages.includes(stageKey)) {
                        variant = 'success';
                        icon = '✓ ';
                      } else if (chat.currentStage === stageKey) {
                        variant = 'primary';
                        icon = '⟳ ';
                      } else if (chat.failedStage === stageKey) {
                        variant = 'danger';
                        icon = '✗ ';
                      }

                      return (
                        <Badge key={stageKey} bg={variant} className="px-2 py-1">
                          {icon}
                          {label}
                        </Badge>
                      );
                    })}
                  </div>

                  {/* Output Paths */}
                  {Object.keys(chat.outputPaths).length > 0 && (
                    <div className="mt-3">
                      <strong className="small">Output Files:</strong>
                      <div className="small text-muted mt-1">
                        {Object.entries(chat.outputPaths).map(([stage, path]) => (
                          <div key={stage} className="mb-1">
                            <span className="badge bg-secondary me-1">
                              {STAGE_LABELS[stage] || stage}
                            </span>
                            <code className="text-break">{path}</code>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Error Display */}
                  {chat.error && (
                    <div className="alert alert-danger mt-3 mb-0 small">
                      <strong>Error:</strong> {chat.error}
                    </div>
                  )}
                </Card.Body>
              </div>
            </Collapse>
          </Card>
        );
      })}

      {/* Error Display */}
      {state.error && (
        <Card className="border-danger mt-3">
          <Card.Body>
            <h6 className="text-danger">Error</h6>
            <p className="mb-0 small">{state.error}</p>
          </Card.Body>
        </Card>
      )}
    </div>
  );
};
