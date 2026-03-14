"""
HTTP client for FastAPI backend.

Handles all API interactions including synchronous requests and SSE streaming.
"""

import json
import httpx
from typing import Any, Dict, Iterator, List, Optional
from rich.console import Console


class NewsletterAPIClient:
    """Client for LangTalks Newsletter API."""

    def __init__(self, base_url: str = "http://localhost:8000", timeout: float = 600.0):
        """
        Initialize API client.

        Args:
            base_url: Base URL for API (default: http://localhost:8000)
            timeout: Default timeout in seconds for non-streaming requests
        """
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(timeout=timeout)
        self.console = Console()

    def generate_periodic_newsletter(
        self,
        request: Dict[str, Any],
        stream: bool = True,
    ) -> Dict[str, Any] | Iterator[Dict[str, Any]]:
        """
        Generate periodic newsletter from WhatsApp chats.

        Args:
            request: Newsletter generation request (PeriodicNewsletterRequest)
            stream: Use streaming endpoint (SSE) for real-time progress

        Returns:
            If stream=False: Complete response dictionary
            If stream=True: Iterator yielding SSE events

        Raises:
            httpx.HTTPStatusError: On API error (400, 404, 500, etc.)
        """
        endpoint = "/api/generate_periodic_newsletter/stream" if stream else "/api/generate_periodic_newsletter"

        if stream:
            return self._stream_sse(endpoint, request)
        else:
            response = self.client.post(f"{self.base_url}{endpoint}", json=request)
            response.raise_for_status()
            return response.json()

    def _stream_sse(self, endpoint: str, request: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
        """
        Stream SSE events from endpoint.

        Args:
            endpoint: API endpoint path
            request: Request payload

        Yields:
            Parsed SSE event dictionaries

        Raises:
            httpx.HTTPStatusError: On API error
        """
        try:
            with self.client.stream(
                "POST",
                f"{self.base_url}{endpoint}",
                json=request,
                timeout=None,  # Streaming, no timeout
            ) as response:
                response.raise_for_status()

                # Manually parse SSE events
                for line in response.iter_lines():
                    line_str = line.decode('utf-8') if isinstance(line, bytes) else line
                    line_str = line_str.strip()

                    # SSE data lines start with "data: "
                    if line_str.startswith('data: '):
                        data = line_str[6:]  # Remove "data: " prefix
                        if data:
                            try:
                                yield json.loads(data)
                            except json.JSONDecodeError:
                                # Skip malformed events
                                continue
        except httpx.HTTPStatusError as e:
            self.console.print(f"[red]❌ API Error: {e.response.status_code} - {e.response.text}[/red]")
            raise

    def get_runs(
        self,
        run_type: Optional[str] = "periodic",
        data_source: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """
        List past newsletter generation runs.

        Args:
            run_type: Filter by run type (default: "periodic")
            data_source: Filter by data source name
            limit: Maximum runs to return
            offset: Pagination offset

        Returns:
            RunsListResponse dictionary

        Raises:
            httpx.HTTPStatusError: On API error
        """
        params = {"limit": limit, "offset": offset}
        if run_type:
            params["run_type"] = run_type
        if data_source:
            params["data_source"] = data_source

        response = self.client.get(f"{self.base_url}/api/runs", params=params)
        response.raise_for_status()
        return response.json()

    def get_run_newsletter(
        self,
        run_id: str,
        run_type: str = "periodic",
        format: str = "html",
        source: str = "consolidated",
    ) -> Dict[str, Any]:
        """
        Get newsletter content for specific run.

        Args:
            run_id: Run identifier (directory name)
            run_type: Type of run (default: "periodic")
            format: Content format ("html", "md", "json")
            source: Source type ("consolidated" or "per_chat")

        Returns:
            NewsletterContentResponse dictionary

        Raises:
            httpx.HTTPStatusError: On API error (404 if not found)
        """
        params = {"run_type": run_type, "format": format, "source": source}
        response = self.client.get(f"{self.base_url}/api/runs/{run_id}/newsletter", params=params)
        response.raise_for_status()
        return response.json()

    def get_batch_job_status(self, job_id: str) -> Dict[str, Any]:
        """
        Check status of batch job.

        Args:
            job_id: Batch job UUID

        Returns:
            BatchJobStatusResponse dictionary

        Raises:
            httpx.HTTPStatusError: On API error (404 if not found)
        """
        response = self.client.get(f"{self.base_url}/api/batch_jobs/{job_id}")
        response.raise_for_status()
        return response.json()

    def list_batch_jobs(
        self,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """
        List batch jobs with optional filtering.

        Args:
            status: Filter by status (queued, processing, completed, failed, cancelled)
            limit: Maximum jobs to return
            offset: Pagination offset

        Returns:
            BatchJobListResponse dictionary

        Raises:
            httpx.HTTPStatusError: On API error
        """
        params = {"limit": limit, "offset": offset}
        if status:
            params["status"] = status

        response = self.client.get(f"{self.base_url}/api/batch_jobs", params=params)
        response.raise_for_status()
        return response.json()

    def cancel_batch_job(self, job_id: str) -> Dict[str, Any]:
        """
        Cancel pending/processing batch job.

        Args:
            job_id: Batch job UUID

        Returns:
            Success message dictionary

        Raises:
            httpx.HTTPStatusError: On API error (400 if cannot cancel, 404 if not found)
        """
        response = self.client.delete(f"{self.base_url}/api/batch_jobs/{job_id}")
        response.raise_for_status()
        return response.json()

    def get_discussion_selection(self, run_directory: str) -> Dict[str, Any]:
        """
        Load ranked discussions for HITL selection.

        Args:
            run_directory: Path to workflow output directory

        Returns:
            DiscussionSelectionResponse dictionary

        Raises:
            httpx.HTTPStatusError: On API error (404 if Phase 1 not run)
        """
        response = self.client.get(f"{self.base_url}/api/discussion_selection/{run_directory}")
        response.raise_for_status()
        return response.json()

    def save_discussion_selections(
        self,
        run_directory: str,
        selected_discussion_ids: List[str],
    ) -> Dict[str, Any]:
        """
        Save user-selected discussion IDs for Phase 2.

        Args:
            run_directory: Path to workflow output directory
            selected_discussion_ids: List of selected discussion IDs

        Returns:
            DiscussionSelectionsSaveResponse dictionary

        Raises:
            httpx.HTTPStatusError: On API error (400 if no selections, 404 if run not found)
        """
        payload = {
            "run_directory": run_directory,
            "selected_discussion_ids": selected_discussion_ids,
        }
        response = self.client.post(f"{self.base_url}/api/save_discussion_selections", json=payload)
        response.raise_for_status()
        return response.json()

    def generate_newsletter_phase2(self, run_directory: str) -> Dict[str, Any]:
        """
        Generate newsletter using selected discussions (Phase 2).

        Args:
            run_directory: Path to workflow output directory

        Returns:
            Phase2GenerationResponse dictionary

        Raises:
            httpx.HTTPStatusError: On API error (404 if selections not found)
        """
        payload = {"run_directory": run_directory}
        response = self.client.post(f"{self.base_url}/api/generate_newsletter_phase2", json=payload)
        response.raise_for_status()
        return response.json()

    def close(self):
        """Close HTTP client connection."""
        self.client.close()

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - close client."""
        self.close()
