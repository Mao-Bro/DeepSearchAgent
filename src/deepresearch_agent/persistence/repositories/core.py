"""Session, message, run and event repositories."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.exc import IntegrityError

from backend.app.schemas import MessageCreate, RunCreate, RunEventCreate, SessionCreate
from deepresearch_agent.harness.errors import AppError, ErrorCode
from deepresearch_agent.harness.versioning import EVENT_SCHEMA_VERSION
from deepresearch_agent.persistence.database import Database
from deepresearch_agent.persistence.models import ContractCheckModel, MessageModel, RunEventModel, RunModel, SessionModel

from .utils import json_text, new_id, utc_now_iso


class SessionRepository:
    """管理研究会话的持久化操作（创建、读取、更新、删除）。"""
    def __init__(self, database: Database):
        self.database = database

    async def create(self, data: SessionCreate) -> SessionModel:
        """创建新的研究会话，返回持久化后的会话对象。"""
        now = utc_now_iso()
        model = SessionModel(session_id=new_id("ses"), title=data.title, status="active", created_at=now, updated_at=now)
        async with self.database.transaction() as session:
            session.add(model)
        return model

    async def freeze_memory_snapshot(self, session_id: str, snapshot: dict[str, Any], version: int) -> Optional[SessionModel]:
        """持久化会话的首个策划内存快照，条件更新确保后续内存写入不影响稳定的提示前缀。"""
        async with self.database.transaction() as session:
            await session.execute(
                update(SessionModel)
                .where(SessionModel.session_id == session_id, SessionModel.memory_snapshot_json.is_(None))
                .values(
                    memory_snapshot_json=json_text(snapshot),
                    memory_snapshot_version=version,
                    memory_snapshot_created_at=utc_now_iso(),
                    updated_at=utc_now_iso(),
                )
            )
            return await session.get(SessionModel, session_id)

    async def get(self, session_id: str, *, include_deleted: bool = False) -> Optional[SessionModel]:
        """获取单个会话，可选包含软删除的会话。"""
        async with self.database.sessions() as session:
            query = select(SessionModel).where(SessionModel.session_id == session_id)
            if not include_deleted:
                query = query.where(SessionModel.deleted_at.is_(None))
            return (await session.execute(query)).scalar_one_or_none()

    async def list(self, *, limit: int = 30, offset: int = 0, include_archived: bool = False) -> list[SessionModel]:
        """分页列表会话，可选包含已归档的会话。"""
        limit = max(1, min(limit, 100))
        async with self.database.sessions() as session:
            query = select(SessionModel).where(SessionModel.deleted_at.is_(None))
            if not include_archived:
                query = query.where(SessionModel.status == "active")
            result = await session.execute(query.order_by(SessionModel.updated_at.desc()).limit(limit).offset(max(0, offset)))
            return list(result.scalars())

    async def count(self, *, include_archived: bool = False) -> int:
        """统计会话总数，可选包含已归档的会话。"""
        async with self.database.sessions() as session:
            query = select(func.count()).select_from(SessionModel).where(SessionModel.deleted_at.is_(None))
            if not include_archived:
                query = query.where(SessionModel.status == "active")
            return int((await session.execute(query)).scalar_one())

    async def rename(self, session_id: str, title: str) -> bool:
        """修改会话标题，返回是否成功更新。"""
        if not title.strip():
            raise ValueError("Session 标题不能为空")
        async with self.database.transaction() as session:
            result = await session.execute(update(SessionModel).where(SessionModel.session_id == session_id, SessionModel.deleted_at.is_(None)).values(title=title.strip()[:200], updated_at=utc_now_iso()))
            return result.rowcount == 1

    async def archive(self, session_id: str) -> bool:
        """归档会话（标记为已归档），返回是否成功更新。"""
        now = utc_now_iso()
        async with self.database.transaction() as session:
            result = await session.execute(update(SessionModel).where(SessionModel.session_id == session_id, SessionModel.deleted_at.is_(None)).values(status="archived", archived_at=now, updated_at=now))
            return result.rowcount == 1

    async def restore(self, session_id: str) -> bool:
        """从已归档状态恢复会话，返回是否成功更新。"""
        async with self.database.transaction() as session:
            result = await session.execute(
                update(SessionModel)
                .where(SessionModel.session_id == session_id, SessionModel.deleted_at.is_(None))
                .values(status="active", archived_at=None, updated_at=utc_now_iso())
            )
            return result.rowcount == 1

    async def soft_delete(self, session_id: str) -> bool:
        """软删除会话（标记 deleted_at，保留数据），返回是否成功更新。"""
        now = utc_now_iso()
        async with self.database.transaction() as session:
            result = await session.execute(update(SessionModel).where(SessionModel.session_id == session_id, SessionModel.deleted_at.is_(None)).values(status="deleted", deleted_at=now, updated_at=now))
            return result.rowcount == 1

    async def search(self, query: str, *, limit: int = 20) -> list[SessionModel]:
        """全文搜索会话（基于 FTS 索引），返回匹配的会话列表。"""
        async with self.database.sessions() as session:
            ids = (await session.execute(text("SELECT session_id FROM sessions_fts WHERE sessions_fts MATCH :query LIMIT :limit"), {"query": query, "limit": limit})).scalars().all()
            if not ids:
                return []
            return list((await session.execute(select(SessionModel).where(SessionModel.session_id.in_(ids), SessionModel.deleted_at.is_(None)))).scalars())

    async def update_summary(self, session_id: str, summary: dict[str, Any]) -> bool:
        """更新会话摘要，返回是否成功更新。"""
        async with self.database.transaction() as session:
            result = await session.execute(update(SessionModel).where(SessionModel.session_id == session_id, SessionModel.deleted_at.is_(None)).values(summary_json=json_text(summary), updated_at=utc_now_iso()))
            return result.rowcount == 1


class MessageRepository:
    """管理消息的持久化操作（创建、读取、搜索）。"""
    def __init__(self, database: Database):
        self.database = database

    async def append(self, data: MessageCreate) -> tuple[MessageModel, bool]:
        """追加消息到数据库，支持 client_message_id 幂等性去重，返回（消息, 是否新建）。"""
        async with self.database.transaction() as session:
            if data.client_message_id:
                existing = (await session.execute(select(MessageModel).where(MessageModel.session_id == data.session_id, MessageModel.client_message_id == data.client_message_id))).scalar_one_or_none()
                if existing:
                    return existing, False
            model = MessageModel(message_id=new_id("msg"), session_id=data.session_id, run_id=data.run_id, client_message_id=data.client_message_id, role=data.role, content=data.content, metadata_json=json_text(data.metadata), created_at=utc_now_iso())
            session.add(model)
            return model, True

    async def get(self, message_id: str) -> Optional[MessageModel]:
        """获取单个消息。"""
        async with self.database.sessions() as session:
            return await session.get(MessageModel, message_id)

    async def list_for_session(self, session_id: str, *, limit: int = 100, offset: int = 0) -> list[MessageModel]:
        """获取会话内的消息列表，按创建时间排序。"""
        async with self.database.sessions() as session:
            result = await session.execute(select(MessageModel).where(MessageModel.session_id == session_id).order_by(MessageModel.created_at).limit(max(1, min(limit, 500))).offset(max(0, offset)))
            return list(result.scalars())

    async def get_assistant_for_run(self, run_id: str) -> Optional[MessageModel]:
        """获取运行关联的 AI 回复消息。"""
        async with self.database.sessions() as session:
            return (await session.execute(
                select(MessageModel).where(MessageModel.run_id == run_id, MessageModel.role == "assistant")
            )).scalar_one_or_none()

    async def search(self, query: str, *, session_id: Optional[str] = None, limit: int = 20) -> list[MessageModel]:
        """全文搜索消息（可选按会话过滤），返回按搜索排名排序的消息列表。"""
        clause = "messages_fts MATCH :query"
        params: dict[str, Any] = {"query": query, "limit": limit}
        if session_id:
            clause += " AND session_id = :session_id"
            params["session_id"] = session_id
        async with self.database.sessions() as session:
            ids = (await session.execute(text(f"SELECT message_id FROM messages_fts WHERE {clause} LIMIT :limit"), params)).scalars().all()
            if not ids:
                return []
            rows = list((await session.execute(select(MessageModel).where(MessageModel.message_id.in_(ids)))).scalars())
            rank = {message_id: index for index, message_id in enumerate(ids)}
            rows.sort(key=lambda item: rank.get(item.message_id, len(rank)))
            return rows


class RunRepository:
    """管理研究任务的持久化操作（创建、读取、状态更新、租约管理）。"""
    ACTIVE_STATUSES = ("queued", "context_building", "planning", "executing", "reporting", "verifying", "retrying", "replanning", "cancelling")

    def __init__(self, database: Database):
        self.database = database

    async def create(self, data: RunCreate) -> RunModel:
        """创建新的研究任务，返回持久化后的任务对象。"""
        now = utc_now_iso()
        model = RunModel(run_id=new_id("run"), session_id=data.session_id, trigger_message_id=data.trigger_message_id, source_mode=data.source_mode.value, workflow_mode=data.workflow_mode.value, status="queued", config_snapshot_json=json_text(data.config_snapshot), model_snapshot_json="{}", budget_json=json_text(data.budget), usage_json="{}", created_at=now, updated_at=now)
        try:
            async with self.database.transaction() as session:
                session.add(model)
        except IntegrityError as exc:
            raise AppError(ErrorCode.CONFLICT, "该消息已经关联 Run") from exc
        return model

    async def create_for_user_message(self, message: MessageCreate, run: RunCreate) -> tuple[MessageModel, RunModel, bool]:
        """原子操作：创建用户消息、研究任务和初始事件，支持 client_message_id 幂等性，返回（消息, 任务, 是否新建）。"""
        if message.role != "user" or message.session_id != run.session_id:
            raise ValueError("原子创建仅接受同一 Session 的 user message")
        async with self.database.transaction() as session:
            if message.client_message_id:
                existing_message = (await session.execute(select(MessageModel).where(MessageModel.session_id == message.session_id, MessageModel.client_message_id == message.client_message_id))).scalar_one_or_none()
                if existing_message:
                    existing_run = (await session.execute(select(RunModel).where(RunModel.trigger_message_id == existing_message.message_id))).scalar_one()
                    if existing_message.content != message.content or existing_run.source_mode != run.source_mode.value or existing_run.workflow_mode != run.workflow_mode.value:
                        raise AppError(ErrorCode.IDEMPOTENCY_CONFLICT, "client_message_id 已被不同的消息或运行参数使用")
                    return existing_message, existing_run, False
            now = utc_now_iso()
            message_model = MessageModel(message_id=new_id("msg"), session_id=message.session_id, client_message_id=message.client_message_id, role="user", content=message.content, metadata_json=json_text(message.metadata), created_at=now)
            run_model = RunModel(run_id=new_id("run"), session_id=run.session_id, trigger_message_id=message_model.message_id, source_mode=run.source_mode.value, workflow_mode=run.workflow_mode.value, status="queued", config_snapshot_json=json_text(run.config_snapshot), model_snapshot_json="{}", budget_json=json_text(run.budget), usage_json="{}", created_at=now, updated_at=now)
            event_model = RunEventModel(run_id=run_model.run_id, event_type="run.queued", stage="queued", payload_json=json_text({"run_id": run_model.run_id, "schema_version": EVENT_SCHEMA_VERSION}), schema_version=EVENT_SCHEMA_VERSION, created_at=now)
            session.add(message_model)
            await session.flush()
            session.add(run_model)
            await session.flush()
            session.add(event_model)
            await session.flush()
            return message_model, run_model, True

    async def get(self, run_id: str) -> Optional[RunModel]:
        """获取单个研究任务。"""
        async with self.database.sessions() as session:
            return (await session.execute(select(RunModel).where(RunModel.run_id == run_id))).scalar_one_or_none()

    async def list_for_session(self, session_id: str, *, limit: int = 50, offset: int = 0) -> list[RunModel]:
        """获取会话内的研究任务列表，按创建时间倒序。"""
        async with self.database.sessions() as session:
            result = await session.execute(select(RunModel).where(RunModel.session_id == session_id).order_by(RunModel.created_at.desc()).limit(max(1, min(limit, 200))).offset(max(0, offset)))
            return list(result.scalars())

    async def update_status(self, run_id: str, *, status: str, current_stage: Optional[str] = None, error_code: Optional[str] = None, error_message: Optional[str] = None, usage: Optional[dict[str, Any]] = None) -> bool:
        """更新任务状态（非完成状态），同时更新阶段、错误信息和 token 使用量，返回是否成功更新。"""
        if status == "completed":
            raise ValueError("completed 只能由 complete_verified() 在 Contract 门禁后写入")
        values: dict[str, Any] = {"status": status, "updated_at": utc_now_iso(), "error_code": error_code, "error_message": error_message}
        if current_stage is not None:
            values["current_stage"] = current_stage
        if usage is not None:
            values["usage_json"] = json_text(usage)
        if status == "context_building":
            values["started_at"] = utc_now_iso()
        if status in {"failed", "budget_exhausted", "cancelled"}:
            values["completed_at"] = utc_now_iso()
        async with self.database.transaction() as session:
            result = await session.execute(update(RunModel).where(RunModel.run_id == run_id).values(**values))
            return result.rowcount == 1

    async def update_usage(self, run_id: str, usage: dict[str, Any]) -> bool:
        """更新任务的 token 使用量，不改变状态或错误信息，返回是否成功更新。"""
        async with self.database.transaction() as session:
            result = await session.execute(
                update(RunModel)
                .where(RunModel.run_id == run_id)
                .values(usage_json=json_text(usage), updated_at=utc_now_iso())
            )
            return result.rowcount == 1

    async def complete_verified(self, run_id: str, *, assistant_content: str, usage: dict[str, Any]) -> tuple[MessageModel, bool]:
        """原子操作：验证完成合同通过后完成任务并追加 AI 回复消息，返回（消息, 是否新建）。"""
        async with self.database.transaction() as session:
            run = await session.get(RunModel, run_id)
            if run is None:
                raise ValueError(f"Run 不存在: {run_id}")
            checks = list((await session.execute(select(ContractCheckModel).where(ContractCheckModel.run_id == run_id, ContractCheckModel.required == 1))).scalars())
            if not checks or any(check.passed != 1 for check in checks):
                raise ValueError("required Completion Contract 未全部通过")
            existing = (await session.execute(select(MessageModel).where(MessageModel.run_id == run_id, MessageModel.role == "assistant"))).scalar_one_or_none()
            now = utc_now_iso()
            run.status = "completed"
            run.current_stage = "completed"
            run.usage_json = json_text(usage)
            run.completed_at = now
            run.updated_at = now
            if existing is not None:
                return existing, False
            message = MessageModel(
                message_id=new_id("msg"), session_id=run.session_id, run_id=run_id,
                client_message_id=None, role="assistant", content=assistant_content,
                metadata_json=json_text({"verified": True}), created_at=now,
            )
            session.add(message)
            await session.flush()
            return message, True

    async def update_model_snapshot(self, run_id: str, snapshot: dict[str, Any]) -> bool:
        """更新模型快照（LLM 模型版本等信息），返回是否成功更新。"""
        async with self.database.transaction() as session:
            result = await session.execute(update(RunModel).where(RunModel.run_id == run_id).values(model_snapshot_json=json_text(snapshot), updated_at=utc_now_iso()))
            return result.rowcount == 1

    async def list_recoverable(self) -> list[RunModel]:
        """获取所有可恢复的任务（活跃或被中断的任务），用于启动时恢复。"""
        async with self.database.sessions() as session:
            return list((await session.execute(select(RunModel).where(RunModel.status.in_(self.ACTIVE_STATUSES + ("interrupted",))))).scalars())

    async def mark_expired_leases_interrupted(self) -> list[str]:
        """标记过期租约的任务为中断，并记录中断事件，返回中断的任务 ID 列表。"""
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        async with self.database.transaction() as session:
            rows = list((await session.execute(select(RunModel).where(
                RunModel.status.in_(self.ACTIVE_STATUSES),
                or_(RunModel.lease_expires_at.is_(None), RunModel.lease_expires_at < now),
            ))).scalars())
            for run in rows:
                run.status = "interrupted"
                run.current_stage = "interrupted"
                run.lease_owner = None
                run.lease_expires_at = None
                run.updated_at = now
                session.add(RunEventModel(
                    run_id=run.run_id,
                    event_type="run.interrupted",
                    stage="interrupted",
                    payload_json=json_text({
                        "reason": "startup_recovery",
                        "schema_version": EVENT_SCHEMA_VERSION,
                    }),
                    schema_version=EVENT_SCHEMA_VERSION,
                    created_at=now,
                ))
            return [run.run_id for run in rows]

    async def request_cancel(self, run_id: str) -> bool:
        """标记任务待取消，返回是否成功更新。"""
        async with self.database.transaction() as session:
            result = await session.execute(update(RunModel).where(RunModel.run_id == run_id, RunModel.status.in_(self.ACTIVE_STATUSES)).values(cancellation_requested=1, updated_at=utc_now_iso()))
            return result.rowcount == 1

    async def resume(self, run_id: str, *, clarification: Optional[str] = None) -> bool:
        """恢复被中断或等待输入的任务，可选追加用户澄清信息，返回是否成功恢复。"""
        async with self.database.transaction() as session:
            run = await session.get(RunModel, run_id)
            if run is None or run.status not in {"interrupted", "needs_user_input"}:
                return False
            snapshot = json.loads(run.config_snapshot_json or "{}")
            if clarification:
                entries = list(snapshot.get("clarifications", []))
                entries.append({"content": clarification, "created_at": utc_now_iso()})
                snapshot["clarifications"] = entries
            # Interrupted Runs keep their marker until Harness loads the latest
            # checkpoint and selects the safe continuation stage. Clarification
            # resumes intentionally rebuild context from queued.
            if run.status == "needs_user_input":
                run.status = "queued"
                run.current_stage = "queued"
            run.cancellation_requested = 0
            run.error_code = None
            run.error_message = None
            run.config_snapshot_json = json_text(snapshot)
            run.updated_at = utc_now_iso()
            return True

    async def acquire_lease(self, run_id: str, owner: str, *, ttl_seconds: int = 60) -> bool:
        """获取任务租约（防止并发执行），设置所有者和过期时间，返回是否获取成功。"""
        now = datetime.now(timezone.utc)
        now_text = now.isoformat().replace("+00:00", "Z")
        expires = (now + timedelta(seconds=ttl_seconds)).isoformat().replace("+00:00", "Z")
        async with self.database.transaction() as session:
            result = await session.execute(update(RunModel).where(RunModel.run_id == run_id, or_(RunModel.lease_owner.is_(None), RunModel.lease_expires_at < now_text, RunModel.lease_owner == owner)).values(lease_owner=owner, lease_expires_at=expires, updated_at=now_text))
            return result.rowcount == 1

    async def release_lease(self, run_id: str, owner: str) -> bool:
        """释放任务租约（清空所有者和过期时间），返回是否释放成功。"""
        async with self.database.transaction() as session:
            result = await session.execute(update(RunModel).where(RunModel.run_id == run_id, RunModel.lease_owner == owner).values(lease_owner=None, lease_expires_at=None, updated_at=utc_now_iso()))
            return result.rowcount == 1


class EventRepository:
    """管理研究任务事件的持久化操作（追加事件、读取事件流）。"""
    def __init__(self, database: Database):
        self.database = database

    async def append(self, data: RunEventCreate) -> RunEventModel:
        """追加事件到数据库，自动添加 schema_version，返回持久化后的事件对象。"""
        model = RunEventModel(run_id=data.run_id, event_type=data.event_type, stage=data.stage, payload_json=json_text({**data.payload, "schema_version": EVENT_SCHEMA_VERSION}), schema_version=EVENT_SCHEMA_VERSION, created_at=utc_now_iso())
        async with self.database.transaction() as session:
            session.add(model)
            await session.flush()
        return model

    async def list_after(self, run_id: str, *, after_event_id: int = 0, limit: int = 500) -> list[RunEventModel]:
        """获取指定任务指定 ID 之后的事件列表，用于事件流推送（支持断点续传）。"""
        async with self.database.sessions() as session:
            result = await session.execute(select(RunEventModel).where(RunEventModel.run_id == run_id, RunEventModel.event_id > after_event_id).order_by(RunEventModel.event_id).limit(max(1, min(limit, 1000))))
            return list(result.scalars())
