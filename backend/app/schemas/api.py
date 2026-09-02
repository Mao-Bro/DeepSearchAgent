"""HTTP DTOs for the phase-4 FastAPI boundary."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from deepresearch_agent.harness.contracts import SourceMode, WorkflowMode


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ErrorBody(ApiModel):
    """错误详情信息体，包含错误代码、消息和可重试状态。"""
    code: str  # 错误类型代码
    message: str  # 人类可读的错误描述
    retryable: bool = False  # 是否可以重试该请求
    details: dict[str, Any] = Field(default_factory=dict)  # 额外的错误上下文信息


class ErrorResponse(ApiModel):
    """API错误响应外壳，包含错误信息和追踪用的请求ID。"""
    error: ErrorBody  # 错误详情信息体
    request_id: str  # 唯一请求ID用于追踪和调试


class SessionPatch(ApiModel):
    """会话修改请求，用于更新会话标题或状态（激活/归档）。"""
    title: str | None = Field(default=None, min_length=1, max_length=200)  # 新的会话标题
    status: Literal["active", "archived"] | None = None  # 会话状态（激活或已归档）


class MessageSend(ApiModel):
    """发送消息并触发研究任务的请求体，包含用户消息内容和研究配置。"""
    client_message_id: str = Field(min_length=1, max_length=128)  # 客户端生成的消息ID用于幂等性去重
    content: str = Field(min_length=1, max_length=20000)  # 用户输入的消息内容
    source_mode: SourceMode  # 信息源类型（GraphRAG或Web搜索）
    workflow_mode: WorkflowMode = WorkflowMode.DEEP_RESEARCH  # 工作流模式（深度研究或计划执行报告）
    report_type: Literal["brief", "long_document"] = "brief"  # 报告类型（简洁或长文档）


class ClarificationSubmit(ApiModel):
    """澄清问题的提交请求，用于在运行暂停时提供用户反馈。"""
    content: str = Field(min_length=1, max_length=10000)  # 澄清内容或用户补充信息


class RunAccepted(ApiModel):
    """异步任务被接受的响应，返回运行信息和事件流访问URL。"""
    message_id: str  # 创建的消息ID
    run_id: str  # 创建的运行任务ID
    status: str  # 运行任务当前状态
    events_url: str  # 服务端推送事件流URL用于实时监听任务进度
    created: bool  # 是否新创建该运行（False表示幂等重用已存在的运行）


class RunControl(ApiModel):
    """运行任务控制操作的响应，返回任务ID和新状态。"""
    run_id: str  # 运行任务ID
    status: str  # 运行任务的新状态（如queued、cancelling）


class MemoryLifecycleUpdate(ApiModel):
    """内存项目的生命周期更新请求，用于修改内存的内容、状态或过期时间。"""
    content: str | None = Field(default=None, min_length=1, max_length=10000)  # 内存项目内容
    status: Literal["candidate", "active", "rejected", "archived", "expired"] | None = None  # 内存生命周期状态
    expires_at: str | None = Field(default=None, max_length=40)  # ISO 8601格式的过期时间戳


class MemoryCreate(ApiModel):
    """创建新内存项目的请求体，支持用户和项目两种内存类型。"""
    target: Literal["user", "project"]  # 内存归属类型（用户个人或项目共享）
    content: str = Field(min_length=1, max_length=10000)  # 内存项目内容
    kind: Literal["preference", "fact", "decision", "lesson", "note"] = "note"  # 内存分类（偏好、事实、决策、经验或笔记）
    provenance_refs: list[str] = Field(default_factory=list, max_length=20)  # 内存来源的外部引用列表（如代码行、文件路径、URL）
    activate: bool = False  # 是否在创建后立即激活该内存


class SkillActionResponse(ApiModel):
    """技能操作执行的响应，表示操作是否被接受和拒绝原因。"""
    accepted: bool  # 技能操作是否被系统接受执行
    reason: str  # 操作结果或拒绝原因的说明
