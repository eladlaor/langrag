/**
 * Chat selector component with dynamic options based on data source
 * Organized by community groups with expandable sections
 */

import React, { useState } from "react";
import { Form, Badge } from "react-bootstrap";
import { COMMUNITY_STRUCTURE } from "../../constants";

type DataSourceKey = keyof typeof COMMUNITY_STRUCTURE;

interface ChatSelectorProps {
  dataSource: DataSourceKey;
  selectedChats: string[];
  onChange?: (chats: string[]) => void;
  onSelectionChange?: (chats: string[]) => void;
  error?: string;
}

export const ChatSelector: React.FC<ChatSelectorProps> = ({
  dataSource,
  selectedChats,
  onChange,
  onSelectionChange,
  error,
}) => {
  // Support both onChange and onSelectionChange prop names
  const handleChange = onChange || onSelectionChange || (() => {});
  const communityGroups = COMMUNITY_STRUCTURE[dataSource];
  const [expandedGroups, setExpandedGroups] = useState<string[]>(
    Object.keys(communityGroups)
  );

  if (!communityGroups) {
    throw new Error(`Invalid data source: ${dataSource}. Expected 'langtalks', 'mcp_israel', or 'n8n_israel'`);
  }

  const handleCheckboxChange = (chatName: string) => {
    if (selectedChats.includes(chatName)) {
      handleChange(selectedChats.filter((c) => c !== chatName));
    } else {
      handleChange([...selectedChats, chatName]);
    }
  };

  const handleSelectAllInGroup = (groupChats: readonly string[]) => {
    const newSelection = new Set(selectedChats);
    groupChats.forEach(chat => newSelection.add(chat));
    handleChange(Array.from(newSelection));
  };

  const handleDeselectAllInGroup = (groupChats: readonly string[]) => {
    handleChange(selectedChats.filter(chat => !groupChats.includes(chat)));
  };

  const handleSelectAll = () => {
    const allChats = Object.values(communityGroups).flat();
    handleChange(allChats as string[]);
  };

  const handleDeselectAll = () => {
    handleChange([]);
  };

  const toggleGroup = (groupName: string) => {
    setExpandedGroups(prev =>
      prev.includes(groupName)
        ? prev.filter(g => g !== groupName)
        : [...prev, groupName]
    );
  };

  const getGroupSelectionCount = (groupChats: readonly string[]) => {
    return groupChats.filter(chat => selectedChats.includes(chat)).length;
  };

  const allChats = Object.values(communityGroups).flat();

  return (
    <Form.Group className="mb-3">
      <Form.Label>WhatsApp Chat Groups</Form.Label>
      <div className="mb-2">
        <button
          type="button"
          className="btn btn-sm btn-outline-primary me-2"
          onClick={handleSelectAll}
        >
          Select All
        </button>
        <button
          type="button"
          className="btn btn-sm btn-outline-secondary"
          onClick={handleDeselectAll}
        >
          Deselect All
        </button>
      </div>
      <div className="border rounded p-2" style={{ maxHeight: "400px", overflowY: "auto" }}>
        {Object.entries(communityGroups).map(([groupName, groupChats]) => {
          const selectionCount = getGroupSelectionCount(groupChats);
          const isExpanded = expandedGroups.includes(groupName);
          const isFullySelected = selectionCount === groupChats.length;

          return (
            <div key={groupName} className="mb-2">
              <div
                className="d-flex align-items-center justify-content-between p-2 bg-light rounded"
                style={{ cursor: "pointer" }}
                onClick={() => toggleGroup(groupName)}
              >
                <div className="d-flex align-items-center">
                  <span className="me-2">
                    {isExpanded ? "▼" : "▶"}
                  </span>
                  <strong>{groupName}</strong>
                  <Badge bg="secondary" className="ms-2">
                    {selectionCount}/{groupChats.length}
                  </Badge>
                </div>
                <div onClick={(e) => e.stopPropagation()}>
                  {isFullySelected ? (
                    <button
                      type="button"
                      className="btn btn-sm btn-outline-secondary"
                      onClick={() => handleDeselectAllInGroup(groupChats)}
                    >
                      Deselect All
                    </button>
                  ) : (
                    <button
                      type="button"
                      className="btn btn-sm btn-outline-primary"
                      onClick={() => handleSelectAllInGroup(groupChats)}
                    >
                      Select All
                    </button>
                  )}
                </div>
              </div>

              {isExpanded && (
                <div className="ps-4 pt-2">
                  {groupChats.map((chatName: string) => (
                    <Form.Check
                      key={chatName}
                      type="checkbox"
                      id={`chat-${chatName}`}
                      label={chatName}
                      checked={selectedChats.includes(chatName)}
                      onChange={() => handleCheckboxChange(chatName)}
                      className="mb-1"
                    />
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
      {error && <Form.Text className="text-danger">{error}</Form.Text>}
      <Form.Text className="text-muted">
        Selected: {selectedChats.length} of {allChats.length} chat(s)
      </Form.Text>
    </Form.Group>
  );
};
