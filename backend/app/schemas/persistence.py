"""Validated DTOs for the stage 1 persistence boundary.

Pydantic BaseModel 知识：
  • BaseModel：Pydantic 核心基类，提供数据验证和序列化功能
  • 自动验证：根据字段类型注解自动进行类型检查和范围验证
  • Field()：定义字段约束（min_length、max_length、default 等）
  • ConfigDict：配置容器，通过 model_config 设置 DTO 行为
  • from_attributes=True：允许从 SQLAlchemy ORM 对象直接初始化 DTO（无需手动转换）
  • model_dump()：将 DTO 转换为字典
  • model_validate()：从字典/ORM 对象验证并创建 DTO 实例

分层设计：
  ApiModel (api.py) ← HTTP 请求/响应的验证边界
  PersistenceDTO (本文件) ← 数据库操作的验证边界
  优点：多层防护、格式转换清晰、问题追踪容易
"""

from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from deepresearch_agent.harness.contracts import SourceMode, WorkflowMode


class PersistenceDTO(BaseModel):
    """数据库持久化层 DTO 基类。from_attributes=True 允许从 SQLAlchemy ORM 对象直接初始化。"""
    model_config = ConfigDict(from_attributes=True)


class SessionCreate(PersistenceDTO):
    """创建会话的请求，对应数据库 INSERT 操作。"""
    title: str = Field(default="新对话", min_length=1, max_length=200)  # 会话标题


class SessionRead(PersistenceDTO):
    """读取会话的响应，对应数据库 SELECT 查询结果。from_attributes=True 使其可直接从 ORM 对象初始化。"""
    session_id: str  # 唯一会话标识
    title: str  # 会话标题
    status: str  # 会话状态（active/archived）
    summary_json: Optional[str] = None  # 会话内容摘要（JSON字符串）
    memory_snapshot_version: Optional[int] = None  # 内存快照版本号
    memory_snapshot_created_at: Optional[str] = None  # 内存快照创建时间
    created_at: str  # 会话创建时间戳
    updated_at: str  # 会话最后更新时间戳
    archived_at: Optional[str] = None  # 会话归档时间（未归档时为空）


class MessageCreate(PersistenceDTO):
    """创建消息的请求，对应数据库 INSERT 操作（user/assistant/system 三种角色）。"""
    session_id: str  # 消息所属的会话ID
    role: Literal["user", "assistant", "system"]  # 消息角色（用户/AI/系统）
    content: str = Field(min_length=1)  # 消息内容文本
    run_id: Optional[str] = None  # 消息关联的运行ID（可选）
    client_message_id: Optional[str] = None  # 客户端生成的消息ID用于幂等性
    metadata: Dict[str, Any] = Field(default_factory=dict)  # 消息元数据（源模式、工作流等）


class MessageRead(PersistenceDTO):
    """读取消息的响应，对应数据库 SELECT 查询结果。"""
    message_id: str  # 唯一消息标识
    session_id: str  # 消息所属的会话ID
    run_id: Optional[str] = None  # 消息关联的运行ID
    client_message_id: Optional[str] = None  # 客户端消息ID用于追踪
    role: str  # 消息角色（user/assistant/system）
    content: str  # 消息内容文本
    metadata_json: str  # 消息元数据（JSON字符串格式存储）
    created_at: str  # 消息创建时间戳


class RunCreate(PersistenceDTO):
    """创建运行任务的请求，对应数据库 INSERT 操作。包含研究配置和预算。"""
    session_id: str  # 运行所属的会话ID
    trigger_message_id: str  # 触发该运行的消息ID
    source_mode: SourceMode  # 信息源类型（GraphRAG或Web）
    workflow_mode: WorkflowMode  # 工作流模式（深度研究或计划执行报告）
    config_snapshot: Dict[str, Any] = Field(default_factory=dict)  # 研究配置快照（证据要求、报告类型等）
    budget: Dict[str, Any] = Field(default_factory=dict)  # 运行预算配置（工具调用次数、token限制等）


class RunRead(PersistenceDTO):
    """读取运行任务的响应，对应数据库 SELECT 查询结果。"""
    run_id: str  # 唯一运行标识
    session_id: str  # 运行所属的会话ID
    trigger_message_id: str  # 触发该运行的消息ID
    source_mode: str  # 信息源类型
    workflow_mode: str  # 工作流模式
    status: str  # 运行状态（queued/executing/reporting等）
    current_stage: Optional[str] = None  # 当前执行阶段（context_building/planning等）
    created_at: str  # 运行创建时间戳
    updated_at: str  # 运行最后更新时间戳


class RunEventCreate(PersistenceDTO):
    """创建运行事件的请求，对应数据库 INSERT 操作。记录运行执行过程中的状态变化。"""
    run_id: str  # 事件所属的运行ID
    event_type: str  # 事件类型（stage_changed/tool_called/verification_done等）
    stage: Optional[str] = None  # 事件发生时的阶段
    payload: Dict[str, Any] = Field(default_factory=dict)  # 事件详情数据（描述、结果、错误等）


class CheckpointRead(PersistenceDTO):
    """读取检查点的响应，对应数据库 SELECT 查询结果。保存运行状态用于故障恢复。"""
    checkpoint_id: str  # 唯一检查点标识
    run_id: str  # 检查点所属的运行ID
    version: int  # 检查点版本号（用于区分同一运行的多个检查点）
    stage: str  # 检查点对应的执行阶段
    state_json: str  # 当前运行状态的JSON序列化（用于恢复执行）
    state_hash: str  # 状态的SHA256哈希值（用于完整性校验）
    created_at: str  # 检查点创建时间戳
