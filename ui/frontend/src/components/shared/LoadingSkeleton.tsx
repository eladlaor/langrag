/**
 * Loading Skeleton Component
 *
 * Displays placeholder content while data is loading.
 */

import React from 'react';
import { Card, Placeholder } from 'react-bootstrap';

interface LoadingSkeletonProps {
  lines?: number;
  showHeader?: boolean;
}

export const LoadingSkeleton: React.FC<LoadingSkeletonProps> = ({
  lines = 3,
  showHeader = true,
}) => {
  return (
    <Card className="mb-3">
      {showHeader && (
        <Card.Header>
          <Placeholder as="span" animation="glow">
            <Placeholder xs={6} />
          </Placeholder>
        </Card.Header>
      )}
      <Card.Body>
        <Placeholder as="p" animation="glow">
          {Array.from({ length: lines }).map((_, i) => (
            <Placeholder key={i} xs={i === lines - 1 ? 8 : 12} className="mb-2" />
          ))}
        </Placeholder>
      </Card.Body>
    </Card>
  );
};

export default LoadingSkeleton;
