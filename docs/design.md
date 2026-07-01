# RAG 文件知识库服务设计文档 v3.0

| 文档版本 | 修改日期 | 作者 | 说明 |
|:---|:---|:---|:---|
| v1.0 | 2026-06-30 | AI 架构师 | 初始版本：多知识库 + 双引擎 |
| v2.0 | 2026-07-01 | AI 架构师 | 精简为单知识库 + LightRAG Only + 定时任务 |
| v3.0 | 2026-07-01 | AI 架构师 / Codex | 架构修订：无用户隔离、retrieve-only、应用层分片、文件级状态、可恢复索引 |

## 1. 概述

### 1.1 需求背景

公司内部存在大量非结构化文档，例如研报、技术规范、会议纪要等，信息分散且难以复用。公司已具备内源大模型服务平台，统一提供 Embedding 和 Chat/LLM 能力。

本平台面向内部可信网络，建设一个轻量级、易维护、面向文件的 RAG 检索服务。服务只负责文件管理、索引构建和片段检索，不负责生成最终答案。

### 1.2 产品目标

核心能力：

- 用户上传文件，系统异步解析并索引。
- 用户通过自然语言检索，获得相关片段、相关性分数和引用出处。
- 用户可查看文件索引状态，并下载原始文件核验引用。
- 管理员可查看系统状态、调度任务日志、失败明细，并动态调整索引和检索参数。

核心设计原则：

- **Retrieve-only**：只返回检索片段，不生成答案，答案生成由上层 Agent 或业务系统负责。
- **单知识库**：所有文件进入同一个共享知识库，不做知识库 CRUD 和权限隔离。
- **无认证 MVP**：部署在可信内网，不做登录、JWT、API Key 或 `X-User-ID`。
- **引用可控**：应用层先解析和分片，保存 `file_segments`，最终检索响应由应用表组装。
- **最终一致删除**：删除后读路径立即过滤，LightRAG 内部数据异步清理。
- **可恢复索引**：失败可分类、可重试；长时间 `processing` 可超时回收。

### 1.3 需求单号

AR10001AQL

## 2. 项目范围

| 类别 | 包含（In Scope） | 不包含（Out of Scope） |
|:---|:---|:---|
| RAG 引擎 | LightRAG 单引擎，后端内嵌 SDK | 双引擎切换、多 RAG 框架路由 |
| 服务输出 | 检索片段、分数、引用出处 | 直接生成最终答案 |
| 知识库 | 单一共享知识库 | 多知识库、权限隔离、租户隔离 |
| 用户体系 | 无登录、无认证、无 `X-User-ID` | 注册登录、JWT、API Key、RBAC |
| 文件处理 | PDF、DOCX、TXT、MD，单文件小于 20MB | OCR、PPT、Excel、大文件断点续传 |
| 上传体验 | 前端支持多选，后端单文件上传接口 | 后端批量上传事务 |
| 索引触发 | APScheduler 定时扫描 + 管理员立即执行 | 普通用户实时索引触发 |
| 原文访问 | 长期保留原文件，支持下载 | 在线预览、页码跳转预览 |
| 配置管理 | 索引、检索、调度、LLM 配置 | 在线修改 Embedding 模型并自动重建 |
| 数据库 | PostgreSQL + pgvector，应用表使用 Alembic 管理 | Milvus/Qdrant |

## 3. 系统架构

### 3.1 整体架构

```text
前端工作台 / 外部 Agent / 脚本
        |
        v
FastAPI 表现层
  - POST /upload
  - GET /files
  - GET /files/{file_id}
  - GET /files/{file_id}/download
  - DELETE /files/{file_id}
  - POST /retrieve
  - /admin/status
  - /admin/configs
  - /admin/scheduler/*
        |
        v
应用服务层
  - FileService：上传、文件状态、下载、删除标记
  - SegmentService：解析文本、token 分片、引用元数据
  - RetrieveService：调用 LightRAG，回查 file_segments，过滤删除文件
  - ConfigService：系统配置读写和默认值
  - SchedulerService：索引调度、锁、重试、日志
        |
        v
核心基础设施
  - LightRAGClient：LightRAG SDK 适配层
  - DocumentParser：PDF/DOCX/TXT/MD 解析
  - TokenChunker：按 token 分片
  - Postgres：应用表、pgvector、LightRAG 存储
        |
        v
APScheduler
  - 定时扫描待索引文件
  - 管理员立即执行一次
  - PostgreSQL advisory lock 防止并发执行
```

### 3.2 关键边界

#### 3.2.1 应用层与 LightRAG 的边界

应用层负责：

- 保存原始文件。
- 解析文件内容。
- 生成 canonical chunks。
- 保存 `file_segments` 和引用元数据。
- 控制文件状态、删除过滤和失败恢复。
- 组装稳定的 API 响应。

LightRAG 负责：

- 接收以 `file_id` 作为 `doc_id` 的文本内容，`filename` 作为 `file_paths`。
- 建立向量/图谱索引。
- 根据问题召回候选片段。
- 通过 `aquery_data()` 返回 retrieve-only 结构化结果，包含 `chunk_id`、`file_path` 和 `content`。

当前 LightRAG SDK 不直接支持任意 metadata 写入。应用层必须把 `segment_id` 作为稳定标识写入 chunk 内容头部，或维护 `chunk_id -> segment_id` 映射。最终 API 响应不直接透传 LightRAG 原始结果。后端必须恢复 `segment_id` 后回查 `file_segments + files`，只返回仍然有效的片段。

#### 3.2.2 删除一致性

删除采用最终一致策略：

1. 用户调用 `DELETE /files/{file_id}`。
2. 后端将 `files.index_status` 更新为 `deleting`，并将对应 `file_segments.status` 更新为 `deleted`。
3. 检索响应层立即过滤非 `completed/indexed` 数据，因此被删除文件马上不可见。
4. 后台异步调用 LightRAG 删除该文件相关索引。
5. 清理成功后将文件状态更新为 `deleted`。

即使 LightRAG 在异步清理前仍召回旧 segment，响应层也必须过滤，避免删除文件继续出现在检索结果中。

## 4. 数据库设计

### 4.1 应用表

应用表由 Alembic 迁移管理。LightRAG 自动创建和维护的内部表不由应用直接操作。

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE files (
    id VARCHAR(36) PRIMARY KEY,
    filename VARCHAR(255) NOT NULL,
    file_path TEXT NOT NULL,
    file_size_bytes BIGINT NOT NULL,
    content_type VARCHAR(100),
    file_ext VARCHAR(20),
    index_status VARCHAR(20) NOT NULL DEFAULT 'pending',
    error_code VARCHAR(100),
    error_msg TEXT,
    retry_count INT NOT NULL DEFAULT 0,
    next_retry_at TIMESTAMP WITH TIME ZONE,
    processing_started_at TIMESTAMP WITH TIME ZONE,
    indexed_at TIMESTAMP WITH TIME ZONE,
    deleted_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_files_status ON files(index_status);
CREATE INDEX idx_files_retry ON files(index_status, next_retry_at);
CREATE INDEX idx_files_created ON files(created_at);

CREATE TABLE file_segments (
    id VARCHAR(36) PRIMARY KEY,
    file_id VARCHAR(36) NOT NULL REFERENCES files(id),
    segment_index INT NOT NULL,
    content TEXT NOT NULL,
    token_count INT,
    location_type VARCHAR(30) NOT NULL,
    location_value VARCHAR(100) NOT NULL,
    location_start INT,
    location_end INT,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_segments_file_id ON file_segments(file_id);
CREATE INDEX idx_segments_status ON file_segments(status);

CREATE TABLE system_configs (
    key VARCHAR(100) PRIMARY KEY,
    value TEXT NOT NULL,
    description VARCHAR(255),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE scheduler_logs (
    id VARCHAR(36) PRIMARY KEY,
    trigger_type VARCHAR(20) NOT NULL,
    started_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    finished_at TIMESTAMP WITH TIME ZONE,
    status VARCHAR(20) NOT NULL,
    total_files INT DEFAULT 0,
    processed_files INT DEFAULT 0,
    failed_files INT DEFAULT 0,
    skipped_files INT DEFAULT 0,
    error_msg TEXT,
    details JSONB
);

CREATE INDEX idx_scheduler_logs_started ON scheduler_logs(started_at);
```

### 4.2 文件状态机

```text
pending
  -> processing
       -> completed
       -> failed
  -> deleting
       -> deleted

completed
  -> deleting
       -> deleted

failed
  -> pending      可重试错误到达 next_retry_at 后自动重试
  -> deleting
       -> deleted
```

状态说明：

| 状态 | 说明 | 是否可检索 |
|:---|:---|:---|
| `pending` | 已上传，等待索引 | 否 |
| `processing` | 正在解析或索引 | 否 |
| `completed` | 已完成索引 | 是 |
| `failed` | 索引失败 | 否 |
| `deleting` | 用户已删除，后台清理中 | 否 |
| `deleted` | 已删除 | 否 |

### 4.3 片段状态

| 状态 | 说明 | 是否可返回 |
|:---|:---|:---|
| `pending` | 已生成，待写入 LightRAG | 否 |
| `indexed` | 已写入 LightRAG | 是，但文件也必须是 `completed` |
| `deleted` | 已逻辑删除 | 否 |

### 4.4 默认系统配置

```sql
INSERT INTO system_configs (key, value, description) VALUES
    ('rag.chunk_size', '1024', '新文件默认分片大小，单位 tokens'),
    ('rag.chunk_overlap', '200', '新文件默认分片重叠，单位 tokens'),
    ('rag.default_top_k', '5', '检索默认返回片段数'),
    ('rag.default_threshold', '0.7', '检索默认相关性阈值'),
    ('rag.search_mode', 'global', 'LightRAG 检索模式，由管理员配置'),
    ('rag.llm_model', 'Qwen2.5-72B-Internal', 'LightRAG 索引和查询使用的 LLM 模型'),
    ('scheduler.interval_minutes', '5', '定时任务执行间隔'),
    ('scheduler.batch_size', '100', '单次任务最大处理文件数'),
    ('scheduler.max_retries', '3', '可重试错误最大重试次数'),
    ('scheduler.retry_interval_minutes', '30', '失败后再次重试间隔'),
    ('scheduler.processing_timeout_minutes', '30', 'processing 超时回收阈值'),
    ('scheduler.status', 'idle', '调度器状态'),
    ('scheduler.last_run', '', '上次执行时间戳');
```

## 5. API 设计

### 5.1 通用错误响应

```json
{
  "detail": "错误描述信息",
  "code": "FILE_PARSE_ERROR",
  "timestamp": "2026-07-01T14:30:00Z"
}
```

### 5.2 错误码

| 错误码 | HTTP 状态码 | 是否可重试 | 说明 |
|:---|:---|:---|:---|
| `FILE_TOO_LARGE` | 413 | 否 | 文件超过大小限制 |
| `FILE_TYPE_NOT_ALLOWED` | 415 | 否 | 文件类型不支持 |
| `FILE_NOT_FOUND` | 404 | 否 | 文件不存在 |
| `EMPTY_CONTENT` | 422 | 否 | 文件未解析出有效文本 |
| `PARSE_ENCRYPTED_PDF` | 422 | 否 | PDF 加密或无法解析 |
| `LLM_TIMEOUT` | 503 | 是 | LLM 网关超时 |
| `EMBEDDING_GATEWAY_503` | 503 | 是 | Embedding 网关不可用 |
| `DB_TRANSIENT_ERROR` | 503 | 是 | 数据库临时错误 |
| `SCHEDULER_ALREADY_RUNNING` | 409 | 是 | 已有索引任务运行中 |

### 5.3 接口总览

| 方法 | 路径 | 描述 |
|:---|:---|:---|
| POST | `/upload` | 上传单个文件 |
| GET | `/files` | 查看文件列表 |
| GET | `/files/{file_id}` | 查看单文件状态 |
| GET | `/files/{file_id}/download` | 下载原始文件 |
| DELETE | `/files/{file_id}` | 删除文件，检索立即不可见 |
| POST | `/retrieve` | 检索相关片段 |
| GET | `/admin/status` | 获取系统状态 |
| GET | `/admin/configs` | 获取系统配置 |
| PUT | `/admin/configs` | 更新系统配置 |
| GET | `/admin/scheduler/status` | 获取调度器状态 |
| POST | `/admin/scheduler/trigger` | 管理员立即执行一次索引任务 |
| GET | `/admin/scheduler/logs` | 获取调度日志和失败明细 |

### 5.4 上传文件

```http
POST /upload
Content-Type: multipart/form-data

file=<binary>
```

响应：

```json
{
  "file_id": "f_001",
  "filename": "report.pdf",
  "size": 2048576,
  "index_status": "pending",
  "message": "文件上传成功，将由后台任务完成索引"
}
```

说明：

- 后端接口只接收单文件。
- 前端支持多选文件，并对每个文件分别调用 `POST /upload`。
- 上传接口只保存文件和元数据，不等待解析或索引。

### 5.5 文件列表

```http
GET /files?status=completed&limit=50&offset=0
```

响应：

```json
{
  "items": [
    {
      "file_id": "f_001",
      "filename": "report.pdf",
      "size": 2048576,
      "index_status": "completed",
      "error_code": null,
      "error_msg": null,
      "retry_count": 0,
      "indexed_at": "2026-07-01T14:35:00Z",
      "created_at": "2026-07-01T14:30:00Z"
    }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0
}
```

默认列表不展示 `deleted` 文件。

### 5.6 单文件状态

```http
GET /files/{file_id}
```

响应：

```json
{
  "file_id": "f_001",
  "filename": "report.pdf",
  "size": 2048576,
  "index_status": "processing",
  "error_code": null,
  "error_msg": null,
  "retry_count": 0,
  "segment_count": 32,
  "indexed_at": null,
  "created_at": "2026-07-01T14:30:00Z"
}
```

### 5.7 下载原文

```http
GET /files/{file_id}/download
```

响应为原始文件流。`deleted` 文件不可下载。

### 5.8 删除文件

```http
DELETE /files/{file_id}
```

响应：

```json
{
  "success": true,
  "file_id": "f_001",
  "index_status": "deleting",
  "message": "文件已从检索结果中隐藏，后台将异步清理索引"
}
```

删除语义：

- 接口返回时，该文件已不会出现在检索结果中。
- LightRAG 物理清理异步完成。
- 原始文件可在 `deleted` 后由后台清理策略处理；MVP 默认长期保留或人工清理。

### 5.9 检索片段

```http
POST /retrieve
Content-Type: application/json

{
  "question": "去年 AI 芯片的市场格局如何？",
  "top_k": 5,
  "threshold": 0.7
}
```

请求说明：

- `question` 必填。
- `top_k` 可选，缺省使用 `rag.default_top_k`。
- `threshold` 可选，缺省使用 `rag.default_threshold`。
- 不暴露 `search_mode`，统一使用管理员配置的 `rag.search_mode`。

响应：

```json
{
  "chunks": [
    {
      "segment_id": "seg_001",
      "rank": 1,
      "score": 0.92,
      "content": "英伟达在训练市场占据较高份额，AMD 在推理市场增长...",
      "citation": {
        "file_id": "f_001",
        "filename": "2026-Q2-行业趋势报告.pdf",
        "location_type": "page",
        "location": "23",
        "download_url": "/files/f_001/download"
      }
    }
  ],
  "retrieval_time_ms": 45
}
```

响应组装规则：

1. 调用 LightRAG `aquery_data()` 检索候选结果。
2. 从候选结果的 `content` 头部或 `chunk_id` 映射恢复 `segment_id`。
3. 回查 `file_segments` 和 `files`。
4. 只返回 `files.index_status = 'completed'` 且 `file_segments.status = 'indexed'` 的片段。
5. 对剩余结果按分数排序和截断。

### 5.10 管理员配置

```http
GET /admin/configs
PUT /admin/configs
```

可配置项：

```json
{
  "rag": {
    "chunk_size": 1024,
    "chunk_overlap": 200,
    "default_top_k": 5,
    "default_threshold": 0.7,
    "search_mode": "global",
    "llm_model": "Qwen2.5-72B-Internal"
  },
  "scheduler": {
    "interval_minutes": 5,
    "batch_size": 100,
    "max_retries": 3,
    "retry_interval_minutes": 30,
    "processing_timeout_minutes": 30
  }
}
```

配置生效规则：

- `chunk_size` 和 `chunk_overlap` 只影响新文件，不自动重建旧文件。
- `default_top_k`、`default_threshold`、`search_mode` 影响后续检索。
- `llm_model` 影响后续新文件索引和后续检索。
- Embedding 模型固定在环境变量，不允许后台修改。

### 5.11 调度器接口

```http
GET /admin/scheduler/status
POST /admin/scheduler/trigger
GET /admin/scheduler/logs?limit=20
```

`POST /admin/scheduler/trigger` 响应：

```json
{
  "success": true,
  "message": "索引任务已启动",
  "task_id": "task_20260701_143000",
  "pending_files": 38
}
```

如果已有任务运行：

```json
{
  "detail": "已有索引任务运行中",
  "code": "SCHEDULER_ALREADY_RUNNING",
  "timestamp": "2026-07-01T14:30:00Z"
}
```

## 6. 索引流程

### 6.1 正常流程

```text
用户上传文件
  -> 保存原始文件到 uploads/
  -> 写入 files，状态 pending
  -> 返回 file_id

APScheduler 定时触发或管理员手动触发
  -> 获取 PostgreSQL advisory lock
  -> 回收超时 processing 文件
  -> 扫描 pending 或可重试 failed 文件
  -> 批量处理文件
      -> 状态改为 processing，记录 processing_started_at
      -> 解析 PDF/DOCX/TXT/MD
      -> 按 token 分片，写入 file_segments
      -> 调用 LightRAG 写入文档，doc_id=file_id，内容头部包含 segment_id
      -> segments 改为 indexed
      -> files 改为 completed
  -> 写入 scheduler_logs
  -> 释放 advisory lock
```

### 6.2 失败分类

不可重试失败：

- 文件类型不支持。
- 文件超过大小限制。
- 加密 PDF。
- 文件为空或未解析出有效文本。
- 文档结构严重损坏。

可重试失败：

- LLM 网关超时。
- Embedding 网关临时不可用。
- PostgreSQL 临时连接错误。
- LightRAG 临时写入失败。

可重试失败处理：

1. `retry_count += 1`。
2. 如果 `retry_count < scheduler.max_retries`，设置 `next_retry_at`。
3. 到达 `next_retry_at` 后调度器重新处理。
4. 超过最大次数后保持 `failed`，等待人工处理或重新上传。

### 6.3 processing 超时回收

每次调度任务开始前，先扫描：

```text
index_status = 'processing'
AND processing_started_at < now() - processing_timeout_minutes
```

处理规则：

- 未超过最大重试次数：重置为 `pending`，等待重新索引。
- 已超过最大重试次数：标记为 `failed`，写入 `PROCESSING_TIMEOUT`。

### 6.4 并发控制

定时任务和管理员手动触发都必须先获取 PostgreSQL advisory lock。未获取锁时不得启动新任务。

推荐锁名：

```text
rag_platform_index_scheduler
```

实现可用 `pg_try_advisory_lock(hashtext('rag_platform_index_scheduler'))`。

## 7. 前端设计

### 7.1 普通用户工作台

一个页面完成：

- 多文件选择上传。
- 每个文件逐个调用后端 `POST /upload`。
- 文件列表展示：文件名、大小、状态、失败原因、重试次数、下载按钮、删除按钮。
- 检索输入框：只要求输入问题，可选调整 `top_k` 和 `threshold`。
- 检索结果展示：片段内容、分数、文件名、页码/段落、下载入口。

状态展示建议：

| 文件状态 | 展示文案 |
|:---|:---|
| `pending` | 等待索引 |
| `processing` | 索引中 |
| `completed` | 已入库 |
| `failed` | 索引失败 |
| `deleting` | 删除中 |
| `deleted` | 已删除 |

### 7.2 管理后台

一个页面包含：

- 系统状态：文件总数、已索引、待索引、索引中、失败、删除中。
- 检索状态：segment 数量、LightRAG 工作目录、当前 search mode。
- 配置表单：索引、检索、调度、LLM。
- 调度控制：当前状态、上次执行时间、立即执行按钮。
- 最近任务日志：执行时间、耗时、处理数、失败数、失败文件明细。

## 8. 环境配置

```env
APP_NAME=RAG-File-Service
APP_ENV=development
DEBUG=true

HOST=0.0.0.0
PORT=8000

DB_HOST=localhost
DB_PORT=5432
DB_NAME=rag_platform
DB_USER=postgres
DB_PASSWORD=postgres
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20

INTERNAL_LLM_BASE_URL=https://llm-gateway.internal.company.com/v1
INTERNAL_LLM_API_KEY=sk-internal-xxxxxxxxxxxxx
INTERNAL_LLM_TIMEOUT=60

DEFAULT_EMBEDDING_MODEL=bge-large-zh-v1.5
DEFAULT_LLM_MODEL=Qwen2.5-72B-Internal
VECTOR_DIMENSION=1024

LIGHTRAG_WORKING_DIR=/data/lightrag

MAX_UPLOAD_SIZE_MB=20
UPLOAD_DIR=./uploads
ALLOWED_EXTENSIONS=.pdf,.docx,.txt,.md

SCHEDULER_ENABLED=true
```

## 9. 技术验证 Spike

正式开发前先验证 LightRAG 适配层，目标是确认真实 SDK 能满足以下契约：

1. 插入文本时可指定 `ids=file_id` 和 `file_paths=filename`。
2. `aquery_data()` 可返回 retrieve-only 结构化结果。
3. 检索结果可通过 `content` 头部或 `chunk_id` 映射恢复 `segment_id`。
4. 可按 `doc_id=file_id` 删除索引数据。
5. PostgreSQL/pgvector 存储可正常初始化和查询。
6. `search_mode` 可通过配置切换。

如果 LightRAG SDK 无法直接支持某项能力，适配层必须提供兼容策略：

- 无法写入任意 metadata：使用 `doc_id=file_id`、`file_paths=filename`，并将 `segment_id` 嵌入 chunk 内容头部。
- 无法直接返回 `segment_id`：从返回内容头部解析，或维护 LightRAG `chunk_id` 与应用 `segment_id` 的映射。
- 删除以 `adelete_by_doc_id(file_id)` 为主；读路径过滤仍必须保留，保证删除立即生效。
- 无法按应用 chunk 精确插入时，优先使用 LightRAG 支持的文本输入方式，仍保留应用层 `file_segments` 作为响应真源。

## 10. 项目目录建议

```text
rag-platform/
├── backend/
│   ├── app/
│   │   ├── api/routes/
│   │   │   ├── upload.py
│   │   │   ├── files.py
│   │   │   ├── retrieve.py
│   │   │   └── admin.py
│   │   ├── core/
│   │   │   ├── config.py
│   │   │   ├── errors.py
│   │   │   └── schemas.py
│   │   ├── db/session.py
│   │   ├── infrastructure/
│   │   │   ├── document_parser.py
│   │   │   ├── token_chunker.py
│   │   │   └── lightrag_client.py
│   │   ├── models/
│   │   │   ├── file.py
│   │   │   ├── file_segment.py
│   │   │   ├── system_config.py
│   │   │   └── scheduler_log.py
│   │   ├── scheduler/index_job.py
│   │   └── services/
│   │       ├── file_service.py
│   │       ├── retrieve_service.py
│   │       ├── config_service.py
│   │       └── scheduler_service.py
│   ├── alembic/
│   ├── tests/
│   └── main.py
├── frontend/
│   └── src/
│       ├── views/
│       │   ├── WorkspaceView.vue
│       │   └── AdminView.vue
│       ├── components/
│       └── api/
├── uploads/
├── docs/
│   └── design.md
└── README.md
```

## 11. 开发任务拆解

| 阶段 | 后端任务 | 前端任务 | 验收产出 |
|:---|:---|:---|:---|
| Day 1 | FastAPI 骨架、Alembic、应用表、配置服务 | Vue 项目初始化 | Swagger 可访问，迁移可执行 |
| Day 2 | 上传、文件列表、状态、下载、删除标记 | 工作台上传和文件列表 | 文件可上传、查状态、下载、删除 |
| Day 3 | Parser、Chunker、`file_segments`、LightRAG Spike | 检索结果组件 | 可解析文件并生成片段 |
| Day 4 | LightRAGClient 插入/检索/删除适配 | 检索页面联调 | 能返回片段、分数和引用 |
| Day 5 | APScheduler、DB lock、重试、超时回收、日志 | 管理后台状态和日志 | 自动索引 pending 文件 |
| Day 6 | 管理配置、立即执行、失败明细 | 管理配置表单 | 管理员可调参数和触发任务 |
| Day 7 | 全链路测试、异常场景、文档完善 | 联调和演示数据 | MVP 演示闭环 |

## 12. 验收标准

### 12.1 后端

- 可上传 PDF、DOCX、TXT、MD。
- 上传后立即返回 `file_id`，文件状态为 `pending`。
- 定时任务或管理员触发后，文件可进入 `completed`。
- 检索接口只返回片段，不生成答案。
- 每条检索结果包含 `segment_id`、`content`、`score`、`rank` 和 `citation`。
- 删除文件后，该文件立即不会出现在检索结果中。
- 可重试失败会自动重试有限次数。
- `processing` 超时文件可被回收。
- 并发触发索引任务时只有一个任务实际执行。

### 12.2 前端

- 用户可一次选择多个文件上传。
- 每个文件有独立状态展示。
- 用户可下载原始文件核验引用。
- 检索结果展示文件名、页码/段落、分数和片段内容。
- 管理后台可查看状态、任务日志和失败明细。
- 管理后台可修改索引、检索、调度和 LLM 配置。

## 13. 演进路径

| 组件 | MVP | 后续演进 |
|:---|:---|:---|
| 调度器 | FastAPI 内嵌 APScheduler + DB lock | 独立 worker / Celery Beat |
| LightRAG | 后端内嵌 SDK | 独立 LightRAG 服务 |
| 文件存储 | 本地磁盘长期保留 | OSS/S3 对象存储 |
| 权限 | 可信内网无认证 | 接入公司网关 / JWT / RBAC |
| 预览 | 下载原文 | PDF 在线预览和定位 |
| 重建索引 | 不支持旧文件自动 reindex | 管理员手动 reindex |
| 向量库 | PostgreSQL + pgvector | Milvus/Qdrant |

## 14. 总结

v3.0 将系统明确收敛为一个内部共享的 retrieve-only RAG 服务：

- 上传和检索体验面向普通用户。
- 索引、失败恢复和参数调优面向管理员。
- 应用层掌握文件、分片、引用和删除过滤。
- LightRAG 专注检索能力，通过适配层接入，避免业务代码绑定框架细节。

这套架构在 MVP 阶段尽量简单，但保留了生产化所需的关键余地：可观测、可恢复、可替换、引用可核验。
