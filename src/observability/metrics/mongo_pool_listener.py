"""MongoDB connection-pool metrics listener.

Translates ``pymongo.monitoring`` connection-pool events into the Prometheus
series defined on :class:`PrometheusMetricsClient`. Attached at client
construction in ``src/db/connection.py`` via the ``event_listeners`` kwarg.

Purpose: make the shared connection pool observable so pool exhaustion /
head-of-line waiting on checkout can be confirmed or dismissed with data,
rather than guessed at. The saturation alarm is a non-zero
``mongodb_pool_checkout_failures_total`` and a rising
``mongodb_pool_checkout_wait_seconds`` histogram.

All callbacks are fail-soft: a metrics error must never break a DB operation.
"""

import threading
from enum import StrEnum

from pymongo.monitoring import (
    ConnectionPoolListener,
    ConnectionCheckedInEvent,
    ConnectionCheckedOutEvent,
    ConnectionCheckOutFailedEvent,
    ConnectionCheckOutFailedReason,
    ConnectionClosedEvent,
    ConnectionCreatedEvent,
    PoolClearedEvent,
    PoolCreatedEvent,
)

from observability.app import get_logger
from observability.metrics.prometheus_client import get_metrics_client

logger = get_logger(__name__)


class PoolClientLabel(StrEnum):
    """`client` label value distinguishing the two pools in the codebase."""

    ASYNC = "async"  # PyMongo async / AsyncMongoClient — serves API, graphs, RAG, agent
    SYNC = "sync"  # pymongo MongoClient — LangGraph checkpointer only


class PoolConnectionState(StrEnum):
    """`state` label values for the mongodb_pool_connections gauge."""

    CHECKED_OUT = "checked_out"  # in active use by a caller right now
    AVAILABLE = "available"  # created and idle in the pool
    CREATED = "created"  # total sockets the pool has opened (checked_out + available)


class PoolCheckoutFailureReason(StrEnum):
    """`reason` label values for the checkout-failure counter."""

    TIMEOUT = "timeout"  # waited past the wait-queue/server-selection timeout — the saturation signal
    CONN_ERROR = "connection_error"  # socket/handshake error establishing a new connection
    POOL_CLOSED = "pool_closed"  # checkout attempted against a closed pool (shutdown races)
    UNKNOWN = "unknown"  # any reason pymongo introduces that we have not mapped


# pymongo's ConnectionCheckOutFailedReason members are plain string constants;
# map them to our bounded StrEnum so label cardinality and values stay stable.
_REASON_MAP: dict[str, PoolCheckoutFailureReason] = {
    ConnectionCheckOutFailedReason.TIMEOUT: PoolCheckoutFailureReason.TIMEOUT,
    ConnectionCheckOutFailedReason.CONN_ERROR: PoolCheckoutFailureReason.CONN_ERROR,
    ConnectionCheckOutFailedReason.POOL_CLOSED: PoolCheckoutFailureReason.POOL_CLOSED,
}


class MongoPoolMetricsListener(ConnectionPoolListener):
    """Records pool gauges/histograms/counters from pymongo pool events.

    One instance is created per MongoClient and bound to a fixed ``client``
    label (async vs sync). Connection counts are maintained as running totals
    here because pymongo emits deltas (created/closed, checked_out/in), not
    absolute pool sizes.
    """

    def __init__(self, client_label: PoolClientLabel) -> None:
        self._client_label = client_label
        self._created = 0  # total live sockets the pool has opened
        self._checked_out = 0  # sockets currently handed to a caller
        # pymongo delivers checked_out / checked_in callbacks from the multiple
        # worker threads of Motor's executor (and OUTSIDE the pool's own lock),
        # so a plain `+= / -=` would suffer lost updates and `_publish_counts`
        # would read a torn (created, checked_out) pair under concurrency — the
        # exact saturation scenario this metric exists to observe. Guard every
        # mutate-then-snapshot with a lock so the published gauge stays honest.
        self._lock = threading.Lock()

    def _snapshot_and_publish(self) -> None:
        """Read the paired counters atomically, then publish outside the lock."""
        with self._lock:
            created = self._created
            checked_out = self._checked_out
        self._publish_counts(created, checked_out)

    def _publish_counts(self, created: int, checked_out: int) -> None:
        try:
            metrics = get_metrics_client()
            client = str(self._client_label)
            available = max(created - checked_out, 0)
            metrics.set_pool_connections(client, str(PoolConnectionState.CREATED), created)
            metrics.set_pool_connections(client, str(PoolConnectionState.CHECKED_OUT), checked_out)
            metrics.set_pool_connections(client, str(PoolConnectionState.AVAILABLE), available)
        except Exception as e:
            logger.warning(f"Failed to publish mongodb pool counts (client={self._client_label}): {e}")

    # --- connection lifecycle -------------------------------------------------

    def connection_created(self, event: ConnectionCreatedEvent) -> None:
        with self._lock:
            self._created += 1
        self._snapshot_and_publish()

    def connection_closed(self, event: ConnectionClosedEvent) -> None:
        with self._lock:
            self._created = max(self._created - 1, 0)
        self._snapshot_and_publish()

    def connection_ready(self, event) -> None:
        # Connection finished handshake and is available; counts already reflect creation.
        pass

    # --- checkout path --------------------------------------------------------

    def connection_check_out_started(self, event) -> None:
        # Wait duration is delivered on the checked-out / failed events directly
        # (pymongo >= 4.7), so no per-checkout timestamp bookkeeping is needed here.
        pass

    def connection_checked_out(self, event: ConnectionCheckedOutEvent) -> None:
        with self._lock:
            self._checked_out += 1
        self._snapshot_and_publish()
        try:
            duration = getattr(event, "duration", None)
            if duration is not None:
                get_metrics_client().observe_pool_checkout_wait(str(self._client_label), float(duration))
        except Exception as e:
            logger.warning(f"Failed to observe checkout wait (client={self._client_label}): {e}")

    def connection_checked_in(self, event: ConnectionCheckedInEvent) -> None:
        with self._lock:
            self._checked_out = max(self._checked_out - 1, 0)
        self._snapshot_and_publish()

    def connection_check_out_failed(self, event: ConnectionCheckOutFailedEvent) -> None:
        reason = _REASON_MAP.get(getattr(event, "reason", None), PoolCheckoutFailureReason.UNKNOWN)
        try:
            metrics = get_metrics_client()
            metrics.increment_pool_checkout_failure(str(self._client_label), str(reason))
            # A timed-out checkout still waited; record the wait so the histogram
            # reflects the worst cases, not only the successful ones.
            duration = getattr(event, "duration", None)
            if duration is not None:
                metrics.observe_pool_checkout_wait(str(self._client_label), float(duration))
        except Exception as e:
            logger.warning(f"Failed to record checkout failure (client={self._client_label}): {e}")

    # --- pool lifecycle -------------------------------------------------------

    def pool_created(self, event: PoolCreatedEvent) -> None:
        with self._lock:
            self._created = 0
            self._checked_out = 0
        self._snapshot_and_publish()

    def pool_ready(self, event) -> None:
        pass

    def pool_cleared(self, event: PoolClearedEvent) -> None:
        # Pool clear invalidates existing connections; pymongo will emit
        # connection_closed for each, which decrements `_created`. Don't
        # double-count here.
        pass

    def pool_closed(self, event) -> None:
        with self._lock:
            self._created = 0
            self._checked_out = 0
        self._snapshot_and_publish()
