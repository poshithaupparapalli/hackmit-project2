"""Pydantic models mirroring MIA_CONTRACTS.md v1.1 exactly. Field names are frozen."""
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field

EventType = Literal[
    "nav", "click", "edit", "submit", "copy", "paste",
    "shortcut", "tabopen", "tabclose", "scroll", "focus",
]

DetailValue = Union[str, int, float, bool, None]


class EventContext(BaseModel):
    sectionLabel: Optional[str] = Field(default=None, max_length=80)
    formLabel: Optional[str] = Field(default=None, max_length=80)
    targetLabel: Optional[str] = Field(default=None, max_length=80)


class MiaEvent(BaseModel):
    schemaVersion: Literal[1] = 1
    id: str
    installId: str
    sessionId: str
    timestamp: int
    sequence: int
    tabId: int
    frameId: int
    type: EventType
    host: str = Field(max_length=500)
    path: str = Field(max_length=500)
    title: Optional[str] = Field(default=None, max_length=160)
    detail: Optional[Dict[str, DetailValue]] = None
    context: Optional[EventContext] = None


class EventBatchRequest(BaseModel):
    schemaVersion: Literal[1] = 1
    installId: str
    sentAt: int
    events: List[Dict[str, Any]] = Field(max_length=250)


class RejectedEvent(BaseModel):
    id: str
    reason: str


class EventBatchResponse(BaseModel):
    accepted: List[str]
    rejected: List[RejectedEvent]
    serverTime: int


class InstallResponse(BaseModel):
    installId: str
    installToken: str


WorkflowKey = Literal["gmail_to_sheet"]
SuggestionKind = Literal["workflow", "automation", "rule"]
SuggestionStatus = Literal["proposed", "accepted", "dismissed", "built"]


class Suggestion(BaseModel):
    id: str
    kind: SuggestionKind
    title: str = Field(max_length=60)
    summary: str = ""
    evidence: List[str] = []
    steps: List[str] = []
    trigger: str = ""
    action: str = ""
    buildPrompt: str = ""
    workflowKey: Optional[str] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    timeSavedPerWeekMinutes: float = 0.0
    status: SuggestionStatus = "proposed"
    createdAt: int
    updatedAt: int


class SuggestionPatchRequest(BaseModel):
    status: SuggestionStatus


class SuggestionFeedbackRequest(BaseModel):
    decision: Literal["accept", "dismiss", "edit"]
    userEdits: Optional[str] = Field(default=None, max_length=2000)


class StatusResponse(BaseModel):
    observerOnline: bool
    paused: bool
    lastEventAt: Optional[int]
    lastAnalysisAt: Optional[int]
    newEventsPending: int


class AnalyzeResponse(BaseModel):
    queued: bool = True
