/**
 * SourceSelector - Multi-select checkboxes for content source types
 */

import React from "react";
import { Form } from "react-bootstrap";
import { RAG_CONTENT_SOURCES } from "../../constants/rag";

interface SourceSelectorProps {
  selected: string[];
  onChange: (sources: string[]) => void;
}

export const SourceSelector: React.FC<SourceSelectorProps> = ({
  selected,
  onChange,
}) => {
  const handleToggle = (value: string) => {
    if (selected.includes(value)) {
      onChange(selected.filter((s) => s !== value));
    } else {
      onChange([...selected, value]);
    }
  };

  return (
    <div className="d-flex gap-3 align-items-center">
      <small className="text-muted">Search in:</small>
      {RAG_CONTENT_SOURCES.map((source) => (
        <Form.Check
          key={source.value}
          type="checkbox"
          id={`source-${source.value}`}
          label={source.label}
          checked={selected.includes(source.value)}
          onChange={() => handleToggle(source.value)}
          inline
        />
      ))}
    </div>
  );
};
