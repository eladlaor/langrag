/**
 * Tests for useNewsletterStream hook
 */

import { renderHook, act, waitFor } from '@testing-library/react';
import { useNewsletterStream } from './useNewsletterStream';

// Mocking fetch
const mockFetch = jest.fn();
global.fetch = mockFetch;

describe('useNewsletterStream', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  afterEach(() => {
    jest.clearAllMocks();
  });

  it('initializes with idle state', () => {
    const { result } = renderHook(() => useNewsletterStream());

    expect(result.current.state.status).toBe('idle');
    expect(result.current.state.totalChats).toBe(0);
    expect(result.current.state.completedChats).toBe(0);
    expect(result.current.state.failedChats).toBe(0);
  });

  it('transitions to connecting when started', () => {
    // Mocking fetch that never resolves to keep state in connecting
    mockFetch.mockImplementation(() => new Promise(() => {}));

    const { result } = renderHook(() => useNewsletterStream());

    act(() => {
      result.current.start({
        start_date: '2025-01-01',
        end_date: '2025-01-15',
        data_source_name: 'langtalks',
        whatsapp_chat_names_to_include: ['Test Chat'],
        desired_language_for_summary: 'english',
        summary_format: 'langtalks_format',
      });
    });

    expect(result.current.state.status).toBe('connecting');
  });

  it('resets state to idle on cancel', async () => {
    // Mocking fetch that never resolves
    const mockAbort = jest.fn();
    const mockController = { abort: mockAbort };
    mockFetch.mockImplementation(() => new Promise(() => {}));

    const { result } = renderHook(() => useNewsletterStream());

    act(() => {
      result.current.start({
        start_date: '2025-01-01',
        end_date: '2025-01-15',
        data_source_name: 'langtalks',
        whatsapp_chat_names_to_include: ['Test Chat'],
        desired_language_for_summary: 'english',
        summary_format: 'langtalks_format',
      });
    });

    expect(result.current.state.status).toBe('connecting');

    act(() => {
      result.current.cancel();
    });

    expect(result.current.state.status).toBe('idle');
  });

  it('provides start and cancel functions', () => {
    const { result } = renderHook(() => useNewsletterStream());

    expect(typeof result.current.start).toBe('function');
    expect(typeof result.current.cancel).toBe('function');
  });

  it('has empty chats map on init', () => {
    const { result } = renderHook(() => useNewsletterStream());

    expect(result.current.state.chats.size).toBe(0);
  });

  it('handles error state when fetch fails', async () => {
    mockFetch.mockRejectedValue(new Error('Network error'));

    const { result } = renderHook(() => useNewsletterStream());

    await act(async () => {
      result.current.start({
        start_date: '2025-01-01',
        end_date: '2025-01-15',
        data_source_name: 'langtalks',
        whatsapp_chat_names_to_include: ['Test Chat'],
        desired_language_for_summary: 'english',
        summary_format: 'langtalks_format',
      });
    });

    await waitFor(() => {
      expect(result.current.state.status).toBe('error');
    });

    expect(result.current.state.error).toContain('Network error');
  });
});
