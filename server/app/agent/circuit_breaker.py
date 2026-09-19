"""Lightweight in-memory circuit breaker for external LLM API calls."""
import logging
import os
import threading
import time
from enum import StrEnum

logger = logging.getLogger("agent.circuit_breaker")


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    def __init__(self, failure_threshold: int | None = None, recovery_timeout: float | None = None):
        self._threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._lock = threading.Lock()
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_state_change = 0.0

    @property
    def failure_threshold(self) -> int:
        if self._threshold is not None:
            return self._threshold
        return max(1, int(os.getenv("LLM_CIRCUIT_FAILURE_THRESHOLD", "3")))

    @property
    def recovery_timeout(self) -> float:
        if self._recovery_timeout is not None:
            return self._recovery_timeout
        return max(5.0, float(os.getenv("LLM_CIRCUIT_RECOVERY_SECONDS", "30.0")))

    @property
    def state(self) -> CircuitState:
        with self._lock:
            return self._state

    def allow_request(self) -> bool:
        """Return True if an LLM request is permitted, False if fast-fallback is required."""
        with self._lock:
            now = time.monotonic()
            if self._state == CircuitState.CLOSED:
                return True
            if self._state == CircuitState.OPEN:
                if now - self._last_state_change >= self.recovery_timeout:
                    self._state = CircuitState.HALF_OPEN
                    self._last_state_change = now
                    logger.info("circuit breaker half-open: probing upstream LLM")
                    return True
                return False
            if self._state == CircuitState.HALF_OPEN:
                # In half-open state, only allow the active probe
                return False
            return True

    def record_success(self) -> None:
        """Record successful call to reset circuit."""
        with self._lock:
            if self._state != CircuitState.CLOSED:
                logger.info("circuit breaker closed: upstream LLM recovered")
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._last_state_change = time.monotonic()

    def record_failure(self, error: Exception | str | None = None) -> None:
        """Record error (timeout/network/5xx) to trip circuit if threshold reached."""
        with self._lock:
            self._failure_count += 1
            now = time.monotonic()
            if self._state == CircuitState.HALF_OPEN or self._failure_count >= self.failure_threshold:
                if self._state != CircuitState.OPEN:
                    logger.warning(
                        "circuit breaker opened (failures=%d, reason=%s), tripping fast-fallback for %ss",
                        self._failure_count, error or "unspecified", self.recovery_timeout
                    )
                self._state = CircuitState.OPEN
                self._last_state_change = now

    def reset(self) -> None:
        """Reset to initial closed state."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._last_state_change = time.monotonic()


llm_circuit_breaker = CircuitBreaker()
