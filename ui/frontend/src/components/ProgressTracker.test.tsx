/**
 * Tests for ProgressTracker component
 */

import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { ProgressTracker } from './ProgressTracker';
import { ProgressState, ChatProgress } from '../types';

const mockEmptyState: ProgressState = {
  status: 'idle',
  totalChats: 0,
  completedChats: 0,
  failedChats: 0,
  chats: new Map(),
  error: undefined,
  result: undefined,
  hitlRunDirectory: undefined,
};

const createMockChat = (name: string, status: 'pending' | 'in_progress' | 'completed' | 'failed', completedStages: string[]): ChatProgress => ({
  name,
  status,
  currentStage: status === 'in_progress' ? 'preprocess_messages' : '',
  currentMessage: status === 'in_progress' ? 'Processing...' : '',
  completedStages,
  outputPaths: {},
});

const mockRunningState: ProgressState = {
  status: 'running',
  totalChats: 2,
  completedChats: 0,
  failedChats: 0,
  chats: new Map([
    ['Chat1', createMockChat('Chat1', 'in_progress', ['extract_messages'])],
    ['Chat2', createMockChat('Chat2', 'pending', [])],
  ]),
  error: undefined,
  result: undefined,
  hitlRunDirectory: undefined,
};

const mockCompletedState: ProgressState = {
  status: 'completed',
  totalChats: 2,
  completedChats: 2,
  failedChats: 0,
  chats: new Map([
    ['Chat1', createMockChat('Chat1', 'completed', ['extract_messages', 'preprocess_messages', 'translate_messages'])],
    ['Chat2', createMockChat('Chat2', 'completed', ['extract_messages', 'preprocess_messages'])],
  ]),
  error: undefined,
  result: undefined,
  hitlRunDirectory: undefined,
};

describe('ProgressTracker', () => {
  it('renders overall progress card', () => {
    render(<ProgressTracker state={mockRunningState} />);
    expect(screen.getByText(/Overall Progress/)).toBeInTheDocument();
  });

  it('displays correct chat count', () => {
    render(<ProgressTracker state={mockRunningState} />);
    expect(screen.getByText(/0\/2 chats/)).toBeInTheDocument();
  });

  it('displays status badge with correct state', () => {
    render(<ProgressTracker state={mockRunningState} />);
    expect(screen.getByText('RUNNING')).toBeInTheDocument();
  });

  it('shows cancel button when running', () => {
    const mockCancel = jest.fn();
    render(<ProgressTracker state={mockRunningState} onCancel={mockCancel} />);

    const cancelButton = screen.getByText('Cancel');
    expect(cancelButton).toBeInTheDocument();

    fireEvent.click(cancelButton);
    expect(mockCancel).toHaveBeenCalled();
  });

  it('does not show cancel button when not running', () => {
    render(<ProgressTracker state={mockCompletedState} />);
    expect(screen.queryByText('Cancel')).not.toBeInTheDocument();
  });

  it('expands chat details on click', () => {
    render(<ProgressTracker state={mockRunningState} />);

    const chatHeader = screen.getByText('Chat1').closest('[role="button"]');
    expect(chatHeader).toBeInTheDocument();

    if (chatHeader) {
      fireEvent.click(chatHeader);
      // After expansion, should show status label
      expect(screen.getByText('Status:')).toBeInTheDocument();
    }
  });

  it('supports keyboard navigation', () => {
    render(<ProgressTracker state={mockRunningState} />);

    const chatHeader = screen.getByText('Chat1').closest('[role="button"]');
    expect(chatHeader).toHaveAttribute('tabIndex', '0');
    expect(chatHeader).toHaveAttribute('aria-expanded', 'false');

    if (chatHeader) {
      fireEvent.keyDown(chatHeader, { key: 'Enter' });
      expect(chatHeader).toHaveAttribute('aria-expanded', 'true');
    }
  });

  it('displays completed chat count correctly', () => {
    render(<ProgressTracker state={mockCompletedState} />);
    expect(screen.getByText(/2 completed/)).toBeInTheDocument();
  });

  it('displays chat names in the list', () => {
    render(<ProgressTracker state={mockRunningState} />);
    expect(screen.getByText('Chat1')).toBeInTheDocument();
    expect(screen.getByText('Chat2')).toBeInTheDocument();
  });

  it('displays error state when present', () => {
    const errorState: ProgressState = {
      ...mockEmptyState,
      status: 'error',
      error: 'Something went wrong',
    };
    render(<ProgressTracker state={errorState} />);
    expect(screen.getByText('Something went wrong')).toBeInTheDocument();
  });
});
