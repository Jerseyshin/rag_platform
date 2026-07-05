# 数据库迁移指南

本文档记录 RAG 平台后端数据库迁移的使用方法、脚本结构和验收步骤。当前后端使用 PostgreSQL + pgvector，应用表由 Alembic 管理。

## 1. 前置条件

### 1.1 启动带 pgvector 的 PostgreSQL

推荐使用 Docker 镜像，避免本机 PostgreSQL 缺少 `vector` 扩展。

如果本机 PostgreSQL 已占用 `5432`，使用 `5433` 暴露 Docker PostgreSQL：

```powershell
docker run --name rag-postgres `
  -e POSTGRES_USER=postgres `
  -e POSTGRES_PASSWORD=postgres `
  -e POSTGRES_DB=rag_platform `
  -p 5433:5432 `
  -d pgvector/pgvector:pg16
```

检查容器：

```powershell
docker ps --filter name=rag-postgres
```

### 1.2 配置后端数据库连接

编辑：

```text
backend/.env
```

示例：

```env
DB_HOST=localhost
DB_PORT=5433
DB_NAME=rag_platform
DB_USER=postgres
DB_PASSWORD=postgres
```

如果使用本机 PostgreSQL 的 `5432`，则将 `DB_PORT` 改为 `5432`。

### 1.3 验证 pgvector

```powershell
docker exec rag-postgres psql -U postgres -d rag_platform -c "CREATE EXTENSION IF NOT EXISTS vector;"
docker exec rag-postgres psql -U postgres -d rag_platform -c "SELECT extname, extversion FROM pg_extension WHERE extname='vector';"
```

成功时应看到类似：

```text
 extname | extversion
---------+------------
 vector  | 0.8.4
```

## 2. Alembic 目录结构

当前迁移相关文件：

```text
backend/
├── alembic.ini
├── alembic/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       └── 20260702_0001_initial_app_tables.py
└── app/
    ├── db/session.py
    └── models/
```

关键职责：

- `backend/alembic.ini`：Alembic 主配置。
- `backend/alembic/env.py`：读取 `app.core.config.settings.database_url`，加载 ORM metadata。
- `backend/app/db/session.py`：SQLAlchemy async engine、session、`Base`。
- `backend/app/models/`：ORM 模型定义。
- `backend/alembic/versions/`：迁移脚本目录。

## 3. 执行迁移

所有 Alembic 命令建议在 `backend/` 目录下执行。

```powershell
cd C:\Users\18186\Desktop\huawei\rag_platform\backend
```

执行最新迁移：

```powershell
..\.venv\Scripts\python.exe -m alembic -c alembic.ini upgrade head
```

查看当前 head：

```powershell
..\.venv\Scripts\python.exe -m alembic -c alembic.ini heads
```

查看数据库当前版本：

```powershell
..\.venv\Scripts\python.exe -m alembic -c alembic.ini current
```

生成 SQL 但不执行：

```powershell
..\.venv\Scripts\python.exe -m alembic -c alembic.ini upgrade head --sql
```

## 4. 创建新的迁移脚本

### 4.1 修改 ORM 模型

先修改或新增 `backend/app/models/` 下的 ORM 模型。

例如新增字段、表或索引。

### 4.2 自动生成迁移草稿

```powershell
cd C:\Users\18186\Desktop\huawei\rag_platform\backend
..\.venv\Scripts\python.exe -m alembic -c alembic.ini revision --autogenerate -m "describe change"
```

Alembic 会在：

```text
backend/alembic/versions/
```

生成新的迁移文件。

### 4.3 人工检查迁移脚本

自动生成后必须人工检查：

- 表名是否正确。
- 字段类型是否符合设计。
- nullable/default/server_default 是否正确。
- 索引和外键是否完整。
- downgrade 是否能回滚。
- 是否误删已有表或字段。

### 4.4 执行迁移

```powershell
..\.venv\Scripts\python.exe -m alembic -c alembic.ini upgrade head
```

## 5. 当前初始迁移内容

当前初始迁移脚本：

```text
backend/alembic/versions/20260702_0001_initial_app_tables.py
```

它会创建：

- `files`
- `file_segments`
- `system_configs`
- `scheduler_logs`
- `alembic_version`

并执行：

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

默认插入 13 条 `system_configs`：

- `rag.chunk_size`
- `rag.chunk_overlap`
- `rag.default_top_k`
- `rag.default_threshold`
- `rag.search_mode`
- `rag.llm_model`
- `scheduler.interval_minutes`
- `scheduler.batch_size`
- `scheduler.max_retries`
- `scheduler.retry_interval_minutes`
- `scheduler.processing_timeout_minutes`
- `scheduler.status`
- `scheduler.last_run`

## 6. 迁移验收命令

### 6.1 检查扩展

```powershell
docker exec rag-postgres psql -U postgres -d rag_platform -c "SELECT extname, extversion FROM pg_extension WHERE extname='vector';"
```

### 6.2 检查应用表

```powershell
docker exec rag-postgres psql -U postgres -d rag_platform -c "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename IN ('files','file_segments','system_configs','scheduler_logs','alembic_version') ORDER BY tablename;"
```

期望结果：

```text
alembic_version
file_segments
files
scheduler_logs
system_configs
```

### 6.3 检查迁移版本

```powershell
docker exec rag-postgres psql -U postgres -d rag_platform -c "SELECT version_num FROM alembic_version;"
```

当前期望：

```text
20260702_0001
```

### 6.4 检查默认配置

```powershell
docker exec rag-postgres psql -U postgres -d rag_platform -c "SELECT count(*) AS system_config_count FROM system_configs;"
```

当前期望：

```text
13
```

### 6.5 检查关键索引

```powershell
docker exec rag-postgres psql -U postgres -d rag_platform -c "SELECT indexname FROM pg_indexes WHERE schemaname='public' AND tablename IN ('files','file_segments','scheduler_logs') ORDER BY indexname;"
```

当前关键索引：

- `idx_files_status`
- `idx_files_retry`
- `idx_files_created`
- `idx_segments_file_id`
- `idx_segments_status`
- `idx_scheduler_logs_started`

## 7. 常见问题

### 7.1 `extension "vector" is not available`

说明当前 PostgreSQL 没安装 pgvector。

推荐使用：

```powershell
docker run --name rag-postgres `
  -e POSTGRES_USER=postgres `
  -e POSTGRES_PASSWORD=postgres `
  -e POSTGRES_DB=rag_platform `
  -p 5433:5432 `
  -d pgvector/pgvector:pg16
```

然后将 `backend/.env` 的 `DB_PORT` 改成 `5433`。

### 7.2 数据库连接失败

检查：

- Docker 容器是否运行。
- `backend/.env` 的 `DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD` 是否正确。
- 是否在 `backend/` 目录执行 Alembic 命令。

### 7.3 迁移已部分执行怎么办

PostgreSQL DDL 通常在事务中执行，失败时会回滚本次迁移。可先检查：

```powershell
docker exec rag-postgres psql -U postgres -d rag_platform -c "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename;"
```

确认状态后再重新执行：

```powershell
..\.venv\Scripts\python.exe -m alembic -c alembic.ini upgrade head
```

## 8. 当前 T3 验收记录

T3 已在 Docker PostgreSQL + pgvector 下验收通过：

- PostgreSQL 容器：`rag-postgres`
- 连接端口：`localhost:5433`
- pgvector：`vector 0.8.4`
- Alembic 版本：`20260702_0001`
- 应用表：已创建
- 默认配置：13 条
