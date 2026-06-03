"""In-memory session store for voice mode.

Maps our own ``call_id`` to a ``CallSession`` and reconciles Vapi's ``call.id``
on the first webhook that carries it (see the session-mapping note in the plan).
A production deployment would back this with Redis/DB and add TTL/eviction.
"""

from __future__ import annotations

from threading import Lock

from server.factory import build_session
from server.models import CallRequest, CallResult, CallSession


class SessionStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._sessions: dict[str, CallSession] = {}
        self._vapi_to_call: dict[str, str] = {}
        self._results: dict[str, CallResult] = {}

    def create(self, call_request: CallRequest) -> CallSession:
        session = build_session(call_request)
        with self._lock:
            self._sessions[session.call_id] = session
        return session

    def get(self, call_id: str) -> CallSession | None:
        with self._lock:
            return self._sessions.get(call_id)

    def link_vapi(self, vapi_call_id: str, call_id: str) -> None:
        with self._lock:
            self._vapi_to_call[vapi_call_id] = call_id

    def resolve(self, *, call_id: str | None, vapi_call_id: str | None) -> CallSession | None:
        """Find the session by our call_id (preferred) or Vapi's call id."""
        with self._lock:
            if call_id and call_id in self._sessions:
                if vapi_call_id:
                    self._vapi_to_call[vapi_call_id] = call_id
                return self._sessions[call_id]
            if vapi_call_id:
                mapped = self._vapi_to_call.get(vapi_call_id)
                if mapped:
                    return self._sessions.get(mapped)
        return None

    def save_result(self, result: CallResult) -> None:
        with self._lock:
            self._results[result.call_id] = result

    def get_result(self, call_id: str) -> CallResult | None:
        with self._lock:
            return self._results.get(call_id)


# Process-wide singleton (fine for a single-worker MVP server).
store = SessionStore()
