/**
 * EvaluationBadge - Shows faithfulness/relevance scores on assistant messages
 */

import React from "react";
import { Badge, OverlayTrigger, Tooltip } from "react-bootstrap";

interface EvaluationBadgeProps {
  scores: Record<string, number>;
  overallPassed: boolean;
}

export const EvaluationBadge: React.FC<EvaluationBadgeProps> = ({
  scores,
  overallPassed,
}) => {
  if (Object.keys(scores).length === 0) return null;

  const tooltipContent = Object.entries(scores)
    .map(([key, value]) => `${key}: ${(value * 100).toFixed(0)}%`)
    .join("\n");

  return (
    <OverlayTrigger
      placement="top"
      overlay={
        <Tooltip>
          <pre style={{ margin: 0, fontSize: "0.75rem", textAlign: "left" }}>
            {tooltipContent}
          </pre>
        </Tooltip>
      }
    >
      <Badge
        bg={overallPassed ? "success" : "warning"}
        style={{ fontSize: "0.7rem", cursor: "help" }}
      >
        {overallPassed ? "Verified" : "Low confidence"}
      </Badge>
    </OverlayTrigger>
  );
};
