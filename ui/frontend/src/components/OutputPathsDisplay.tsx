/**
 * OutputPathsDisplay Component
 *
 * Displays generated file paths in a hierarchical tree structure
 * with copy-to-clipboard functionality.
 */

import React, { useState } from 'react';
import { Card, Button, Badge, Collapse } from 'react-bootstrap';
import { ProgressState, ChatProgress } from '../types';

interface OutputPathsDisplayProps {
  state: ProgressState;
}

export const OutputPathsDisplay: React.FC<OutputPathsDisplayProps> = ({ state }) => {
  const [expandedSections, setExpandedSections] = useState<Set<string>>(
    new Set(['base', 'chats', 'consolidated'])
  );
  const [copiedPath, setCopiedPath] = useState<string | null>(null);

  const toggleSection = (sectionId: string) => {
    setExpandedSections((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(sectionId)) {
        newSet.delete(sectionId);
      } else {
        newSet.add(sectionId);
      }
      return newSet;
    });
  };

  const copyToClipboard = async (path: string) => {
    try {
      await navigator.clipboard.writeText(path);
      setCopiedPath(path);
      setTimeout(() => setCopiedPath(null), 2000);
    } catch (err) {
      console.error('Failed to copy:', err);
    }
  };

  const getFileIcon = (filename: string): string => {
    if (filename.endsWith('.md')) return '📝';
    if (filename.endsWith('.json')) return '📄';
    if (filename.endsWith('.jsonl')) return '📊';
    if (filename.endsWith('.html')) return '🌐';
    return '📄';
  };

  const getFileName = (path: string): string => {
    return path.split('/').pop() || path;
  };

  const chatsArray = Array.from(state.chats.values());

  // Filtering completed chats with output paths
  const completedChats = chatsArray.filter(
    (chat) => chat.status === 'completed' && Object.keys(chat.outputPaths).length > 0
  );

  if (!state.outputDirectory && completedChats.length === 0) {
    return null; // Nothing to display yet
  }

  return (
    <Card className="mt-3">
      <Card.Header className="bg-primary text-white">
        <h5 className="mb-0">📁 Generated Files</h5>
      </Card.Header>
      <Card.Body>
        {/* Base Output Directory */}
        {state.outputDirectory && (
          <div className="mb-4">
            <div
              className="d-flex justify-content-between align-items-center mb-2"
              onClick={() => toggleSection('base')}
              style={{ cursor: 'pointer' }}
            >
              <strong>
                {expandedSections.has('base') ? '▼' : '▶'} Base Directory
              </strong>
            </div>
            <Collapse in={expandedSections.has('base')}>
              <div>
                <div className="d-flex align-items-center gap-2">
                  <code className="flex-grow-1 small p-2 bg-light rounded text-break">
                    {state.outputDirectory}
                  </code>
                  <Button
                    variant="outline-secondary"
                    size="sm"
                    onClick={() => copyToClipboard(state.outputDirectory!)}
                  >
                    {copiedPath === state.outputDirectory ? '✓ Copied' : '📋 Copy'}
                  </Button>
                </div>
              </div>
            </Collapse>
          </div>
        )}

        {/* Per-Chat Outputs */}
        {completedChats.length > 0 && (
          <div className="mb-4">
            <div
              className="d-flex justify-content-between align-items-center mb-2"
              onClick={() => toggleSection('chats')}
              style={{ cursor: 'pointer' }}
            >
              <strong>
                {expandedSections.has('chats') ? '▼' : '▶'} Per-Chat Outputs
                <Badge bg="secondary" className="ms-2">
                  {completedChats.length} chat{completedChats.length > 1 ? 's' : ''}
                </Badge>
              </strong>
            </div>
            <Collapse in={expandedSections.has('chats')}>
              <div>
                {completedChats.map((chat) => (
                  <div key={chat.name} className="mb-3 ps-3 border-start border-2">
                    <div className="mb-2">
                      <strong className="text-primary">{chat.name}/</strong>
                    </div>
                    <div className="ps-3">
                      {Object.entries(chat.outputPaths).map(([stage, path]) => {
                        const filename = getFileName(path);
                        const icon = getFileIcon(filename);
                        const isNewsletter =
                          filename.includes('newsletter') &&
                          (filename.endsWith('.md') || filename.endsWith('.json'));

                        return (
                          <div key={stage} className="d-flex align-items-center gap-2 mb-2">
                            <span>{icon}</span>
                            <code className="flex-grow-1 small text-break">
                              {filename}
                              {isNewsletter && <span className="ms-1">⭐</span>}
                            </code>
                            <Button
                              variant="outline-secondary"
                              size="sm"
                              onClick={() => copyToClipboard(path)}
                            >
                              {copiedPath === path ? '✓' : '📋'}
                            </Button>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                ))}
              </div>
            </Collapse>
          </div>
        )}

        {/* Consolidated Output */}
        {state.consolidatedOutputDir && (
          <div className="mb-3">
            <div
              className="d-flex justify-content-between align-items-center mb-2"
              onClick={() => toggleSection('consolidated')}
              style={{ cursor: 'pointer' }}
            >
              <strong>
                {expandedSections.has('consolidated') ? '▼' : '▶'} Consolidated Output
                <Badge bg="success" className="ms-2">
                  Merged
                </Badge>
              </strong>
            </div>
            <Collapse in={expandedSections.has('consolidated')}>
              <div className="ps-3">
                <div className="d-flex align-items-center gap-2">
                  <code className="flex-grow-1 small p-2 bg-light rounded text-break">
                    {state.consolidatedOutputDir}
                  </code>
                  <Button
                    variant="outline-secondary"
                    size="sm"
                    onClick={() => copyToClipboard(state.consolidatedOutputDir!)}
                  >
                    {copiedPath === state.consolidatedOutputDir ? '✓ Copied' : '📋 Copy'}
                  </Button>
                </div>
              </div>
            </Collapse>
          </div>
        )}

        {/* Legend */}
        <div className="mt-4 pt-3 border-top">
          <small className="text-muted">
            <strong>Legend:</strong> ⭐ Final newsletter •
            📝 Markdown • 📄 JSON • 📊 JSONL • 🌐 HTML
          </small>
        </div>
      </Card.Body>
    </Card>
  );
};
