"""Data shapes for the GTM agent.

These types are defined before any logic. GtmDeps owns identity and
configuration. MarketReport owns researcher output. GtmStrategy owns
the orchestrator output. ContentBrief and ContentTask own async
content work. Workspace files own artifacts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

# The researcher report path, kept exactly as the Deep Agents source
# defined it. The workspace-relative path is what tools use; the
# public path is what the researcher returns in full_report_path.
REPORT_WORKSPACE_PATH = 'memories/subagents/market-researcher/market-research-report.md'
REPORT_PUBLIC_PATH = f'/{REPORT_WORKSPACE_PATH}'


@dataclass
class GtmDeps:
    """Identity, service clients, and config for a run.

    Deps are never checkpointed state. Keep per-run inputs here, never
    in globals, so a run can move to another worker.
    """

    user_id: str
    exa_api_key: str | None = None


### [market-report]
class MarketReport(BaseModel):
    """Concise extracts from the researcher's full markdown report."""

    full_report_path: str = Field(
        description='Path of the full markdown report, as returned to the parent.'
    )
    tam_sam_som: str = Field(description='TAM/SAM/SOM estimates with methodology.')
    competitors: list[str] = Field(default_factory=list)
    audiences: list[str] = Field(default_factory=list)
    trends: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(
        default_factory=list,
        description='Areas where data is missing or estimates are uncertain.',
    )


### [/market-report]
### [strategy]
class GtmStrategy(BaseModel):
    """The orchestrator's GTM strategy, grounded in researcher evidence."""

    positioning: str
    pricing: str
    channels: list[str] = Field(default_factory=list)
    rationale: list[str] = Field(
        default_factory=list,
        description='Each item states its reasoning and cites researcher evidence.',
    )
    evidence_refs: list[str] = Field(
        default_factory=list,
        description='Report paths or source URLs backing the rationale.',
    )


### [/strategy]
### [content]
class ContentBrief(BaseModel):
    """A brief for one content deliverable, written by the orchestrator."""

    kind: Literal['blog', 'landing', 'copy']
    audience: str
    key_messages: list[str] = Field(default_factory=list)
    tone: str = 'clear, direct, confident'
    source_report_path: str


class ContentTask(BaseModel):
    """One async content task. Status is a state machine, one field."""

    id: str
    brief: ContentBrief
    status: Literal[
        'running',
        'pending',
        'waiting',
        'success',
        'error',
        'cancelled',
        'timeout',
        'interrupted',
    ]
    deliverable_path: str | None = None


class ContentDeliverable(BaseModel):
    """What the content-writer delegate returns after writing a file."""

    task_id: str
    deliverable_path: str
    summary: str


### [/content]
### [grounding]
def grounding_violations(strategy: GtmStrategy) -> list[str]:
    """Check every rationale item cites researcher evidence.

    An item counts as citing evidence when it names one of the
    evidence refs or refers to the report. Returns one message per
    violation, empty when the strategy is grounded.
    """
    violations: list[str] = []
    if not strategy.rationale:
        violations.append('strategy has no rationale items')
    if not strategy.evidence_refs:
        violations.append('strategy has no evidence refs')
    for item in strategy.rationale:
        cited = any(ref in item for ref in strategy.evidence_refs) or (
            'report' in item.lower()
        )
        if not cited:
            violations.append(f'rationale item cites no evidence: {item!r}')
    return violations


### [/grounding]
