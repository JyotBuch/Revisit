from typing import Dict, Optional

from pydantic import BaseModel


class TelemetryMetrics(BaseModel):
    total_llm_calls: int
    total_tokens: int
    estimated_cost_usd: Optional[float] = None
    average_llm_latency_ms: Optional[float] = None
    failed_agent_steps: int
    retrieval_events: int
    average_retrieval_latency_ms: Optional[float] = None


class PipelineMetrics(BaseModel):
    total_captures: int
    captures_by_status: Dict[str, int]
    captures_by_source_type: Dict[str, int]
    total_extracted: int
    total_failed_extraction: int
    total_embeddings: int
    total_clusters: int
    total_cluster_items: int
    singleton_clusters: int
    average_cluster_size: Optional[float] = None
    active_clusters: int
    archived_clusters: int
    cluster_reuse_count: Optional[int] = None
    new_clusters_created: Optional[int] = None
    archived_clusters_count: Optional[int] = None


class RevisitCardMetrics(BaseModel):
    total_revisit_cards: int
    cards_by_type: Dict[str, int]
    cards_by_generation_method: Dict[str, int]
    llm_card_count: int
    rule_based_card_count: int


class FeedbackMetrics(BaseModel):
    total_feedback_events: int
    feedback_counts_by_action: Dict[str, int]
    average_rating: Optional[float] = None
    useful_rate: Optional[float] = None
    dismiss_rate: Optional[float] = None
    next_action_taken_rate: Optional[float] = None


class EvalMetrics(BaseModel):
    latest_eval_report_path: Optional[str] = None
    latest_eval_timestamp: Optional[str] = None
    latest_rule_based_pass_rate: Optional[float] = None
    latest_llm_pass_rate: Optional[float] = None


class JobMetrics(BaseModel):
    total_jobs: int
    jobs_by_status: Dict[str, int]
    latest_daily_batch_status: Optional[str] = None
    latest_daily_batch_started_at: Optional[str] = None
    latest_daily_batch_completed_at: Optional[str] = None


class ResourceMetrics(BaseModel):
    total_resources: int
    resources_by_provider: Dict[str, int]
    average_resource_validation_score: Optional[float] = None
    clusters_with_resources: int
    total_card_resource_links: int
    cards_with_resources: int
    average_resources_per_resource_aware_card: Optional[float] = None


class ObservabilityMetrics(BaseModel):
    pipeline: PipelineMetrics
    revisit_cards: RevisitCardMetrics
    feedback: FeedbackMetrics
    eval: EvalMetrics
    jobs: JobMetrics
    resources: ResourceMetrics
    telemetry: TelemetryMetrics
