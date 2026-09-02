"""SQLAlchemy models for the local MVP's durable fact store.

Model 知识：
  • Model：SQLAlchemy ORM 模型，代表数据库表的 Python 对象
  • Mapped[type]：字段类型映射，告诉 SQLAlchemy 字段的 Python 类型和数据库类型
  • mapped_column()：定义表列的配置（类型、约束、索引等）
  • primary_key=True：主键约束，唯一标识每行
  • ForeignKey：外键约束，确保引用的行存在
  • CheckConstraint：检查约束，限制字段值的范围
  • UniqueConstraint：唯一约束，确保字段或字段组合唯一（常用于幂等性）
  • Index：索引，加快查询速度

工作流：DTO → Repository → Model → SQLAlchemy → SQL → Database
"""

from sqlalchemy import CheckConstraint, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """SQLAlchemy ORM 基类，所有 Model 都继承自它。"""
    pass


class SessionModel(Base):
    """研究会话表，存储用户的对话会话元数据和状态。"""
    __tablename__ = "sessions"
    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    summary_json: Mapped[str | None] = mapped_column(Text)
    memory_snapshot_json: Mapped[str | None] = mapped_column(Text)
    memory_snapshot_version: Mapped[int | None] = mapped_column(Integer)
    memory_snapshot_created_at: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(40), nullable=False)
    archived_at: Mapped[str | None] = mapped_column(String(40))
    deleted_at: Mapped[str | None] = mapped_column(String(40))
    __table_args__ = (Index("ix_sessions_status_updated", "status", "updated_at"),)


class MessageModel(Base):
    """消息表，存储会话内的所有消息（用户、AI、系统），支持 client_message_id 幂等性去重。"""
    __tablename__ = "messages"
    message_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.session_id"), nullable=False)
    run_id: Mapped[str | None] = mapped_column(String(64))
    client_message_id: Mapped[str | None] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    __table_args__ = (
        CheckConstraint("role IN ('user','assistant','system')", name="ck_messages_role"),
        UniqueConstraint("session_id", "client_message_id", name="uq_messages_client_id"),
        Index("ix_messages_session_created", "session_id", "created_at"),
        Index("uq_messages_assistant_run", "run_id", unique=True, sqlite_where=text("role = 'assistant' AND run_id IS NOT NULL")),
    )


class RunModel(Base):
    """研究任务表，存储每次研究的配置、状态、预算使用和执行进度。"""
    __tablename__ = "runs"
    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.session_id"), nullable=False)
    trigger_message_id: Mapped[str] = mapped_column(ForeignKey("messages.message_id"), nullable=False, unique=True)
    source_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    workflow_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    current_stage: Mapped[str | None] = mapped_column(String(32))
    config_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    model_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    budget_json: Mapped[str] = mapped_column(Text, nullable=False)
    usage_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    cancellation_requested: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_owner: Mapped[str | None] = mapped_column(String(128))
    lease_expires_at: Mapped[str | None] = mapped_column(String(40))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    started_at: Mapped[str | None] = mapped_column(String(40))
    completed_at: Mapped[str | None] = mapped_column(String(40))
    updated_at: Mapped[str] = mapped_column(String(40), nullable=False)
    __table_args__ = (
        CheckConstraint("source_mode IN ('graphrag','web')", name="ck_runs_source_mode"),
        CheckConstraint("workflow_mode IN ('deep_research','plan_execute_report')", name="ck_runs_workflow_mode"),
        Index("ix_runs_session_created", "session_id", "created_at"),
        Index("ix_runs_status_lease", "status", "lease_expires_at"),
    )


class RunEventModel(Base):
    """运行事件表，记录研究任务执行过程中的所有状态变化事件（用于事件溯源和 SSE 推送）。"""
    __tablename__ = "run_events"
    event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    stage: Mapped[str | None] = mapped_column(String(32))
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    __table_args__ = (Index("ix_events_run_event", "run_id", "event_id"),)


class CheckpointModel(Base):
    """检查点表，保存研究任务执行状态的持久化快照，用于故障恢复和断点续传。"""
    __tablename__ = "checkpoints"
    checkpoint_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    state_json: Mapped[str] = mapped_column(Text, nullable=False)
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    __table_args__ = (UniqueConstraint("run_id", "version", name="uq_checkpoints_run_version"), Index("ix_checkpoints_run_version", "run_id", "version"))


class PlanModel(Base):
    """计划表，存储 Plan-Execute-Report 工作流中的研究计划版本和内容。"""
    __tablename__ = "plans"
    plan_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    plan_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(40), nullable=False)
    __table_args__ = (UniqueConstraint("run_id", "version", name="uq_plans_run_version"),)


class TaskModel(Base):
    """任务表，存储计划中每个具体的执行任务（检索、总结等）的元数据和状态。"""
    __tablename__ = "tasks"
    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id"), nullable=False)
    plan_id: Mapped[str] = mapped_column(ForeignKey("plans.plan_id"), nullable=False)
    task_type: Mapped[str] = mapped_column(String(48), nullable=False)
    source_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    task_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(40), nullable=False)
    __table_args__ = (Index("ix_tasks_run_status", "run_id", "status"), CheckConstraint("source_mode IN ('graphrag','web')", name="ck_tasks_source_mode"))


class ToolCallModel(Base):
    """工具调用表，记录每次工具调用（GraphRAG 查询、Web 搜索）的参数、结果和执行状态。"""
    __tablename__ = "tool_calls"
    tool_call_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id"), nullable=False)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.task_id"))
    tool_name: Mapped[str] = mapped_column(String(80), nullable=False)
    source_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    args_json: Mapped[str] = mapped_column(Text, nullable=False)
    result_json: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    completed_at: Mapped[str | None] = mapped_column(String(40))
    __table_args__ = (Index("ix_tool_calls_run_task", "run_id", "task_id"), CheckConstraint("source_mode IN ('graphrag','web')", name="ck_tool_calls_source_mode"))


class EvidenceModel(Base):
    """证据表，存储研究过程中收集的所有证据材料（引文、查询结果等）和评分。"""
    __tablename__ = "evidence"
    evidence_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id"), nullable=False)
    task_id: Mapped[str | None] = mapped_column(String(64))
    tool_call_id: Mapped[str | None] = mapped_column(String(64))
    source_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_id: Mapped[str | None] = mapped_column(String(64))
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    invalidated_at: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    __table_args__ = (Index("ix_evidence_run_source", "run_id", "source_mode"), Index("ix_evidence_content_hash", "content_hash"), CheckConstraint("source_mode IN ('graphrag','web')", name="ck_evidence_source_mode"))


class ContractCheckModel(Base):
    """完成合同检查表，记录每个研究任务的验证项目（最小证据数、格式等）和验证结果。"""
    __tablename__ = "contract_checks"
    check_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(48), nullable=False)
    required: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    threshold_json: Mapped[str | None] = mapped_column(Text)
    verifier: Mapped[str] = mapped_column(String(80), nullable=False)
    verifier_version: Mapped[str] = mapped_column(String(32), nullable=False)
    passed: Mapped[int | None] = mapped_column(Integer)
    evidence_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    __table_args__ = (Index("ix_contract_checks_run", "run_id"),)


class ArtifactModel(Base):
    """工件表，存储研究过程中生成的报告、代码等工件的元数据和文件路径。"""
    __tablename__ = "artifacts"
    artifact_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.run_id"))
    relative_path: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)


class MemoryModel(Base):
    """内存表，存储用户和项目级别的持久化记忆（偏好、决策、经验教训等）。"""
    __tablename__ = "memories"
    memory_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("sessions.session_id"))
    target: Mapped[str | None] = mapped_column(String(32))
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    provenance_json: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    valid_from: Mapped[str] = mapped_column(String(40), nullable=False)
    expires_at: Mapped[str | None] = mapped_column(String(40))
    supersedes: Mapped[str | None] = mapped_column(ForeignKey("memories.memory_id"))
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    created_by: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(40), nullable=False)
    deleted_at: Mapped[str | None] = mapped_column(String(40))
    archived_at: Mapped[str | None] = mapped_column(String(40))
    __table_args__ = (Index("ix_memories_status_scope_expiry", "status", "scope", "expires_at"),)


class SkillVersionModel(Base):
    """技能版本表，存储可复用的工作流技能（工作流片段）的版本历史和内容。"""
    __tablename__ = "skill_versions"
    skill_version_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    content_path: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_run_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    __table_args__ = (UniqueConstraint("name", "version", name="uq_skill_name_version"), Index("ix_skill_name_status", "name", "status"))


class SkillCandidateModel(Base):
    """技能候选表，存储由研究任务提议的新技能候选版本（待评估和推广）。"""
    __tablename__ = "skill_candidates"
    candidate_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id"), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    proposed_version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)


class EvalRunModel(Base):
    """评估运行表，记录对技能候选的评估执行过程和评估指标。"""
    __tablename__ = "eval_runs"
    eval_run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("skill_candidates.candidate_id"), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    metrics_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    completed_at: Mapped[str | None] = mapped_column(String(40))


class LearningReviewJobModel(Base):
    """学习评审表，存储从完成的研究任务中学习和提议新技能的评审作业。"""
    __tablename__ = "learning_review_jobs"
    review_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id"), nullable=False)
    terminal_event_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    policy_version: Mapped[str] = mapped_column(String(32), nullable=False, default="1")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    checkpoint_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    review_pack_json: Mapped[str | None] = mapped_column(Text)
    proposal_json: Mapped[str | None] = mapped_column(Text)
    critic_json: Mapped[str | None] = mapped_column(Text)
    validation_json: Mapped[str | None] = mapped_column(Text)
    candidate_id: Mapped[str | None] = mapped_column(ForeignKey("skill_candidates.candidate_id"))
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    revision_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(40), nullable=False)
    completed_at: Mapped[str | None] = mapped_column(String(40))
    __table_args__ = (
        UniqueConstraint("run_id", "terminal_event_id", "policy_version", name="uq_learning_review_idempotency"),
        Index("ix_learning_review_status", "status", "updated_at"),
    )


class SkillReadMarkModel(Base):
    """技能已读标记表，记录学习评审中已读过的技能版本（用于避免重复评审）。"""
    __tablename__ = "skill_read_marks"
    read_mark_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    review_id: Mapped[str] = mapped_column(ForeignKey("learning_review_jobs.review_id"), nullable=False)
    skill_version_id: Mapped[str] = mapped_column(ForeignKey("skill_versions.skill_version_id"), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    __table_args__ = (UniqueConstraint("review_id", "skill_version_id", name="uq_skill_read_mark"),)


class SkillDeploymentModel(Base):
    """技能部署表，记录技能版本在不同环境中的部署状态和流量分配。"""
    __tablename__ = "skill_deployments"
    deployment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    skill_version_id: Mapped[str] = mapped_column(ForeignKey("skill_versions.skill_version_id"), nullable=False)
    stage: Mapped[str] = mapped_column(String(24), nullable=False)
    allocation_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    metrics_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    started_at: Mapped[str] = mapped_column(String(40), nullable=False)
    stopped_at: Mapped[str | None] = mapped_column(String(40))


class AuditEventModel(Base):
    """审计事件表，记录所有重要操作的审计日志（用于合规和问题追踪）。"""
    __tablename__ = "audit_events"
    audit_event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(48), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    __table_args__ = (Index("ix_audit_entity", "entity_type", "entity_id"),)
    __tablename__ = "sessions"
    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    summary_json: Mapped[str | None] = mapped_column(Text)
    memory_snapshot_json: Mapped[str | None] = mapped_column(Text)
    memory_snapshot_version: Mapped[int | None] = mapped_column(Integer)
    memory_snapshot_created_at: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(40), nullable=False)
    archived_at: Mapped[str | None] = mapped_column(String(40))
    deleted_at: Mapped[str | None] = mapped_column(String(40))
    __table_args__ = (Index("ix_sessions_status_updated", "status", "updated_at"),)


class MessageModel(Base):
    __tablename__ = "messages"
    message_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.session_id"), nullable=False)
    run_id: Mapped[str | None] = mapped_column(String(64))
    client_message_id: Mapped[str | None] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    __table_args__ = (
        CheckConstraint("role IN ('user','assistant','system')", name="ck_messages_role"),
        UniqueConstraint("session_id", "client_message_id", name="uq_messages_client_id"),
        Index("ix_messages_session_created", "session_id", "created_at"),
        Index("uq_messages_assistant_run", "run_id", unique=True, sqlite_where=text("role = 'assistant' AND run_id IS NOT NULL")),
    )


class RunModel(Base):
    __tablename__ = "runs"
    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.session_id"), nullable=False)
    trigger_message_id: Mapped[str] = mapped_column(ForeignKey("messages.message_id"), nullable=False, unique=True)
    source_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    workflow_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    current_stage: Mapped[str | None] = mapped_column(String(32))
    config_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    model_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    budget_json: Mapped[str] = mapped_column(Text, nullable=False)
    usage_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    cancellation_requested: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_owner: Mapped[str | None] = mapped_column(String(128))
    lease_expires_at: Mapped[str | None] = mapped_column(String(40))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    started_at: Mapped[str | None] = mapped_column(String(40))
    completed_at: Mapped[str | None] = mapped_column(String(40))
    updated_at: Mapped[str] = mapped_column(String(40), nullable=False)
    __table_args__ = (
        CheckConstraint("source_mode IN ('graphrag','web')", name="ck_runs_source_mode"),
        CheckConstraint("workflow_mode IN ('deep_research','plan_execute_report')", name="ck_runs_workflow_mode"),
        Index("ix_runs_session_created", "session_id", "created_at"),
        Index("ix_runs_status_lease", "status", "lease_expires_at"),
    )


class RunEventModel(Base):
    __tablename__ = "run_events"
    event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    stage: Mapped[str | None] = mapped_column(String(32))
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    __table_args__ = (Index("ix_events_run_event", "run_id", "event_id"),)


class CheckpointModel(Base):
    __tablename__ = "checkpoints"
    checkpoint_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    state_json: Mapped[str] = mapped_column(Text, nullable=False)
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    __table_args__ = (UniqueConstraint("run_id", "version", name="uq_checkpoints_run_version"), Index("ix_checkpoints_run_version", "run_id", "version"))


class PlanModel(Base):
    __tablename__ = "plans"
    plan_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    plan_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(40), nullable=False)
    __table_args__ = (UniqueConstraint("run_id", "version", name="uq_plans_run_version"),)


class TaskModel(Base):
    __tablename__ = "tasks"
    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id"), nullable=False)
    plan_id: Mapped[str] = mapped_column(ForeignKey("plans.plan_id"), nullable=False)
    task_type: Mapped[str] = mapped_column(String(48), nullable=False)
    source_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    task_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(40), nullable=False)
    __table_args__ = (Index("ix_tasks_run_status", "run_id", "status"), CheckConstraint("source_mode IN ('graphrag','web')", name="ck_tasks_source_mode"))


class ToolCallModel(Base):
    __tablename__ = "tool_calls"
    tool_call_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id"), nullable=False)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.task_id"))
    tool_name: Mapped[str] = mapped_column(String(80), nullable=False)
    source_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    args_json: Mapped[str] = mapped_column(Text, nullable=False)
    result_json: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    completed_at: Mapped[str | None] = mapped_column(String(40))
    __table_args__ = (Index("ix_tool_calls_run_task", "run_id", "task_id"), CheckConstraint("source_mode IN ('graphrag','web')", name="ck_tool_calls_source_mode"))


class EvidenceModel(Base):
    __tablename__ = "evidence"
    evidence_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id"), nullable=False)
    task_id: Mapped[str | None] = mapped_column(String(64))
    tool_call_id: Mapped[str | None] = mapped_column(String(64))
    source_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_id: Mapped[str | None] = mapped_column(String(64))
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    invalidated_at: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    __table_args__ = (Index("ix_evidence_run_source", "run_id", "source_mode"), Index("ix_evidence_content_hash", "content_hash"), CheckConstraint("source_mode IN ('graphrag','web')", name="ck_evidence_source_mode"))


class ContractCheckModel(Base):
    __tablename__ = "contract_checks"
    check_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(48), nullable=False)
    required: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    threshold_json: Mapped[str | None] = mapped_column(Text)
    verifier: Mapped[str] = mapped_column(String(80), nullable=False)
    verifier_version: Mapped[str] = mapped_column(String(32), nullable=False)
    passed: Mapped[int | None] = mapped_column(Integer)
    evidence_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    __table_args__ = (Index("ix_contract_checks_run", "run_id"),)


class ArtifactModel(Base):
    __tablename__ = "artifacts"
    artifact_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.run_id"))
    relative_path: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)


class MemoryModel(Base):
    __tablename__ = "memories"
    memory_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("sessions.session_id"))
    target: Mapped[str | None] = mapped_column(String(32))
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    provenance_json: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    valid_from: Mapped[str] = mapped_column(String(40), nullable=False)
    expires_at: Mapped[str | None] = mapped_column(String(40))
    supersedes: Mapped[str | None] = mapped_column(ForeignKey("memories.memory_id"))
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    created_by: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(40), nullable=False)
    deleted_at: Mapped[str | None] = mapped_column(String(40))
    archived_at: Mapped[str | None] = mapped_column(String(40))
    __table_args__ = (Index("ix_memories_status_scope_expiry", "status", "scope", "expires_at"),)


class SkillVersionModel(Base):
    __tablename__ = "skill_versions"
    skill_version_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    content_path: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_run_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    __table_args__ = (UniqueConstraint("name", "version", name="uq_skill_name_version"), Index("ix_skill_name_status", "name", "status"))


class SkillCandidateModel(Base):
    __tablename__ = "skill_candidates"
    candidate_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id"), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    proposed_version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)


class EvalRunModel(Base):
    __tablename__ = "eval_runs"
    eval_run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("skill_candidates.candidate_id"), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    metrics_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    completed_at: Mapped[str | None] = mapped_column(String(40))


class LearningReviewJobModel(Base):
    __tablename__ = "learning_review_jobs"
    review_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id"), nullable=False)
    terminal_event_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    policy_version: Mapped[str] = mapped_column(String(32), nullable=False, default="1")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    checkpoint_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    review_pack_json: Mapped[str | None] = mapped_column(Text)
    proposal_json: Mapped[str | None] = mapped_column(Text)
    critic_json: Mapped[str | None] = mapped_column(Text)
    validation_json: Mapped[str | None] = mapped_column(Text)
    candidate_id: Mapped[str | None] = mapped_column(ForeignKey("skill_candidates.candidate_id"))
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    revision_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(40), nullable=False)
    completed_at: Mapped[str | None] = mapped_column(String(40))
    __table_args__ = (
        UniqueConstraint("run_id", "terminal_event_id", "policy_version", name="uq_learning_review_idempotency"),
        Index("ix_learning_review_status", "status", "updated_at"),
    )


class SkillReadMarkModel(Base):
    __tablename__ = "skill_read_marks"
    read_mark_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    review_id: Mapped[str] = mapped_column(ForeignKey("learning_review_jobs.review_id"), nullable=False)
    skill_version_id: Mapped[str] = mapped_column(ForeignKey("skill_versions.skill_version_id"), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    __table_args__ = (UniqueConstraint("review_id", "skill_version_id", name="uq_skill_read_mark"),)


class SkillDeploymentModel(Base):
    __tablename__ = "skill_deployments"
    deployment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    skill_version_id: Mapped[str] = mapped_column(ForeignKey("skill_versions.skill_version_id"), nullable=False)
    stage: Mapped[str] = mapped_column(String(24), nullable=False)
    allocation_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    metrics_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    started_at: Mapped[str] = mapped_column(String(40), nullable=False)
    stopped_at: Mapped[str | None] = mapped_column(String(40))


class AuditEventModel(Base):
    __tablename__ = "audit_events"
    audit_event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(48), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    __table_args__ = (Index("ix_audit_entity", "entity_type", "entity_id"),)
