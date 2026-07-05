# RAG 平台实施任务清单

本文档用于跟踪 `docs/design.md v3.0` 的落地进度。后续执行规则：

1. 每次只推进一个明确 task。
2. task 完成后，先回到本文档勾选并补充结果说明。
3. 再进入下一个 task。
4. 若实现中发现设计需要调整，先更新 `docs/design.md`，再更新本文档。

## 状态图例

- `[ ]` 未开始
- `[~]` 进行中
- `[x]` 已完成
- `[!]` 阻塞或需要决策

## T0. 项目计划与文档

- [x] T0.1 将讨论后的架构方案更新到 `docs/design.md v3.0`
- [x] T0.2 建立本文档，作为后续 task 跟踪清单
- [x] T0.3 创建 Python 虚拟环境 `.venv`

完成标准：

- `docs/design.md` 明确 retrieve-only、无认证单库、`file_segments`、异步索引、删除过滤、重试恢复和管理配置。
- `docs/tasks.md` 包含可逐项勾选的实施任务。
- `.venv` 已创建，可用于后端依赖安装和本地运行。

## T1. LightRAG Spike 验证

- [x] T1.1 建立最小 Spike 脚本目录和说明
- [x] T1.2 验证插入文本片段时可携带稳定文件身份，并确认 SDK 不支持任意 metadata 直写
- [x] T1.3 验证检索结果能通过内容头部恢复 `segment_id`
- [x] T1.4 验证可按 `doc_id=file_id` 删除索引数据，并保留读路径过滤策略
- [!] T1.5 验证 PostgreSQL/pgvector 存储初始化和查询路径
- [x] T1.6 记录 Spike 结论：真实 SDK 支持项、缺口、兼容策略

完成标准：

- 有可复现的 Spike 记录。
- 明确 `LightRAGClient` 需要暴露的稳定接口。
- 如果 SDK 能力不满足计划，已在 `docs/design.md` 中更新兼容策略。

T1 结果：

- 可复现脚本：`scripts/spikes/lightrag_metadata_spike.py`
- 结论记录：`docs/spikes/lightrag_spike.md`
- 已验证：`ainsert(ids=file_id, file_paths=filename)`、`aquery_data()`、从内容头部恢复 `segment_id`、`adelete_by_doc_id(file_id)`。
- 已修正设计：LightRAG SDK 不按任意 metadata 写入；应用需使用 `file_segments` 作为真源，并通过内容头部或映射恢复 `segment_id`。
- T1.5 阻塞原因：本机无 `psql`、无 PostgreSQL 环境变量、无项目 `.env`，因此未执行真实 PostgreSQL/pgvector 连库验证。

## T2. 后端工程骨架

- [x] T2.1 创建 FastAPI 后端目录结构
- [x] T2.2 添加配置模块、应用启动入口和健康检查
- [x] T2.3 配置 SQLAlchemy async 数据库会话
- [x] T2.4 配置 Alembic 迁移框架
- [x] T2.5 创建基础异常响应和错误码结构

完成标准：

- 后端服务可启动。
- Swagger/OpenAPI 可访问。
- 健康检查接口可返回正常状态。
- 数据库连接配置清晰，可通过环境变量覆盖。

T2 结果：

- 后端入口：`backend/main.py`、`backend/app/main.py`
- 健康检查：`GET /health`
- 配置模块：`backend/app/core/config.py`
- 异常结构：`backend/app/core/errors.py`
- 数据库会话：`backend/app/db/session.py`
- Alembic 配置：`backend/alembic.ini`、`backend/alembic/env.py`
- 验证通过：FastAPI app 可导入，OpenAPI 包含 `/health`，`GET /health` 返回 200，`alembic heads` 可执行。

## T3. 数据模型与迁移

- [x] T3.1 实现 `files` ORM 模型和迁移
- [x] T3.2 实现 `file_segments` ORM 模型和迁移
- [x] T3.3 实现 `system_configs` ORM 模型和默认配置初始化
- [x] T3.4 实现 `scheduler_logs` ORM 模型和迁移
- [x] T3.5 添加基础模型单元测试或迁移校验

完成标准：

- Alembic 可创建全部应用表。
- 文件状态、重试字段、片段引用字段与设计文档一致。
- 默认系统配置可初始化。

T3 结果：

- ORM 模型：`backend/app/models/`
- 初始迁移：`backend/alembic/versions/20260702_0001_initial_app_tables.py`
- 迁移包含 `files`、`file_segments`、`system_configs`、`scheduler_logs` 和默认系统配置。
- 验证通过：`Base.metadata` 包含全部应用表；`alembic heads` 可识别 head；`alembic upgrade head --sql` 可生成 PostgreSQL SQL。

## T4. 文件管理 API

- [x] T4.1 实现 `POST /upload` 单文件上传
- [x] T4.2 实现 `GET /files` 文件列表
- [x] T4.3 实现 `GET /files/{file_id}` 单文件状态
- [x] T4.4 实现 `GET /files/{file_id}/download` 原文下载
- [x] T4.5 实现 `DELETE /files/{file_id}` 删除标记和读路径隐藏
- [x] T4.6 补充文件大小、扩展名、空文件等校验

完成标准：

- 文件可上传到本地 `uploads/`。
- 上传后状态为 `pending`。
- 文件列表默认不展示 `deleted`。
- 删除后文件不会参与后续检索响应。

T4 结果：

- 路由：`backend/app/api/routes/upload.py`、`backend/app/api/routes/files.py`
- 服务：`backend/app/services/file_service.py`
- 已实现上传、列表、单文件状态、下载、删除标记。
- 上传校验包含文件名、扩展名、空文件、大小限制。
- 验证通过：OpenAPI 包含 `/upload`、`/files`、`/files/{file_id}`、`/files/{file_id}/download`。
- 运行时验收通过：使用真实 uvicorn + HTTP 请求验证上传、列表、单文件状态、下载、删除标记、不支持类型和空文件错误；已修复并验证删除后下载返回 404 FILE_NOT_FOUND；测试数据已清理。

## T5. 文档解析与应用层分片

- [x] T5.1 实现 TXT/MD 解析
- [x] T5.2 实现 PDF 解析并保留页码
- [x] T5.3 实现 DOCX 解析并保留段落序号
- [x] T5.4 实现 token 分片和 overlap
- [x] T5.5 将分片写入 `file_segments`
- [x] T5.6 区分不可重试解析错误：加密 PDF、空内容、不支持类型
- [x] T5.7 将 `TokenChunker` 改为可插拔 tokenizer，避免继续使用 `text.split()`
- [x] T5.8 MVP 默认使用 `BAAI/bge-m3` tokenizer，并补充离线缓存文档

完成标准：

- 支持 PDF、DOCX、TXT、MD。
- 每个 segment 包含内容、位置类型、位置值、顺序号。
- 解析失败能写入明确 `error_code/error_msg`。
- 中文文本按 MVP embedding tokenizer 进行 token 计数和 overlap。
- LightRAG 与应用层分片的 tokenizer 策略明确，不依赖 LightRAG 默认 `gpt-4o-mini` tokenizer。

T5 结果：

- 解析器：`backend/app/infrastructure/document_parser.py`
- 分片器：`backend/app/infrastructure/token_chunker.py`
- Segment 写库服务：`backend/app/services/segment_service.py`
- 支持 TXT/MD、PDF、DOCX；PDF 保留页码，DOCX/TXT/MD 保留段落序号。
- 解析失败会写回 `files.index_status/error_code/error_msg`。
- 运行时验收通过：使用临时 TXT/MD/DOCX/PDF 文件验证解析和引用位置；使用 `chunk_size=3/chunk_overlap=1` 验证 overlap；使用本地 PostgreSQL 写入并清理 `file_segments`，本次成功写入 14 条测试 segment。
- 错误验收通过：空 TXT、加密 PDF、不支持类型分别返回 `EMPTY_CONTENT`、`PARSE_ENCRYPTED_PDF`、`FILE_TYPE_NOT_ALLOWED`；`SegmentService` 会将解析失败写回 `files.failed/error_code/error_msg`。
- 已实现 `backend/app/infrastructure/tokenizers.py`，提供 `HuggingFaceTokenizer`、`MixedTextTokenizer` fallback 和 `get_tokenizer()` 缓存工厂。
- `TokenChunker` 已改为依赖 tokenizer `encode/decode`，支持注入测试 tokenizer；默认尝试从 `DEFAULT_TOKENIZER_MODEL=BAAI/bge-m3` 和 `TOKENIZER_CACHE_DIR` 本地加载。
- 当前本地环境未安装 `transformers` 且未缓存 `BAAI/bge-m3`，验证时按设计回退到 `mixed-text-fallback`；生产/验收环境可设置 `TOKENIZER_STRICT=true` 强制缺缓存时报错。
- 验证通过：自定义中文字符 tokenizer 能按 token window 分片并 overlap；默认 tokenizer fallback 可正常处理中文/英文混合文本；`python -m compileall backend/app` 通过。
- 已缓存 `BAAI/bge-m3` 到 `offline_cache/tokenizers/BAAI/bge-m3`，约 4.27GB；已验证 tokenizer 可在 `local_files_only=True/strict=True` 下离线加载。
- 已新增 `backend/app/infrastructure/embedding_client.py`，支持 `EMBEDDING_PROVIDER=local` 和后续 `EMBEDDING_PROVIDER=api`；当前本地 embedding 真正运行还需安装 `sentence-transformers/torch` 或改用内部 embedding API。

## T6. LightRAGClient 与检索链路

- [x] T6.1 实现 `LightRAGClient.insert_segments()`
- [x] T6.2 实现 `LightRAGClient.query()`
- [x] T6.3 实现 `LightRAGClient.delete_file()`
- [x] T6.4 实现 `POST /retrieve`
- [x] T6.5 检索结果通过 `segment_id` 回查 `file_segments + files`
- [x] T6.6 过滤非 `completed/indexed` 的文件和片段

完成标准：

- 检索接口只返回片段，不生成答案。
- 响应包含 `segment_id/content/score/rank/citation`。
- `search_mode` 使用管理员配置，不由普通请求传入。

T6 结果：

- LightRAG 适配层：`backend/app/infrastructure/lightrag_client.py`
- LLM API 适配层：`backend/app/infrastructure/llm_client.py`
- Embedding 适配层：`backend/app/infrastructure/embedding_client.py`
- 检索服务：`backend/app/services/retrieve_service.py`
- 检索接口：`backend/app/api/routes/retrieve.py`
- 已实现真实 provider：本地 `BAAI/bge-m3` embedding function、OpenAI-compatible LLM API function。
- 已验证真实 LightRAG 链路：使用本地 `BAAI/bge-m3` embedding + DeepSeek LLM 完成 `insert_segments()`、`query()` 恢复 `segment_id`、`delete_file()`。
- 已验证应用层回查过滤：候选结果通过 `segment_id` 回查 `file_segments + files`，低分结果、`deleting` 文件、非 `indexed/completed` 数据不会返回。
- 已验证 OpenAPI 包含 `POST /retrieve`；接口只暴露 `question/top_k/threshold`，不暴露 `search_mode`。

## T7. 调度器与索引任务

- [x] T7.1 内嵌 APScheduler
- [x] T7.2 实现 PostgreSQL advisory lock
- [x] T7.3 实现 pending 文件扫描和批处理
- [x] T7.4 实现 processing 超时回收
- [x] T7.5 实现可重试失败策略：`retry_count/next_retry_at/max_retries`
- [x] T7.6 实现 `scheduler_logs` 写入
- [x] T7.7 实现管理员立即触发索引任务

完成标准：

- 定时任务可自动索引 pending 文件。
- 手动触发和定时触发不会并发执行。
- 可重试错误会有限次自动重试。
- 卡住的 processing 文件可被回收。

T7 结果：

- 调度服务：`backend/app/services/scheduler_service.py`
- APScheduler 入口：`backend/app/scheduler/index_job.py`
- FastAPI lifespan 已启动/关闭 APScheduler。
- 已实现 pending/可重试 failed 扫描、processing 超时回收、PostgreSQL advisory lock、`scheduler_logs` 记录。
- 已验证真实调度链路：创建 pending TXT 文件后，手动触发调度，文件变为 `completed`，segment 变为 `indexed`，LightRAG 写入成功，日志状态为 `success`。
- 已验证并发锁：占用 advisory lock 后再次触发调度，结果为 `skipped`。
- 已验证 processing 超时回收：超时文件重置为 `pending`，`retry_count` 增加并写入 `PROCESSING_TIMEOUT`。

## T8. 管理 API

- [x] T8.1 实现 `GET /admin/status`
- [x] T8.2 实现 `GET /admin/configs`
- [x] T8.3 实现 `PUT /admin/configs`
- [x] T8.4 实现 `GET /admin/scheduler/status`
- [x] T8.5 实现 `POST /admin/scheduler/trigger`
- [x] T8.6 实现 `GET /admin/scheduler/logs`

完成标准：

- 管理端可查看文件统计、segment 统计、调度状态和最近日志。
- 管理端可修改索引、检索、调度、LLM 配置。
- 配置生效范围与 `docs/design.md` 一致。

T8 结果：

- 管理路由：`backend/app/api/routes/admin.py`
- 已实现系统状态、配置列表/更新、调度状态、手动触发、调度日志。
- 已验证 OpenAPI 包含 `/admin/status`、`/admin/configs`、`/admin/scheduler/status`、`/admin/scheduler/trigger`、`/admin/scheduler/logs`。
- 已验证管理 GET 接口返回 200；配置 PUT 接口可写入配置并已清理临时测试 key。

## T9. 前端工作台

- [x] T9.1 创建 Vue 前端工程
- [x] T9.2 实现多文件选择，逐个调用 `POST /upload`
- [x] T9.3 实现文件列表、状态、错误原因、下载、删除
- [x] T9.4 实现检索输入和可选 `top_k/threshold`
- [x] T9.5 实现检索结果片段、分数、文件名、页码/段落展示

完成标准：

- 用户可在一个页面完成上传、查看状态、下载、删除、检索。
- 检索结果引用可回到原文件下载核验。

T9 结果：

- 前端工程：`frontend/`
- API 封装：`frontend/src/api.js`
- 工作台页面：`frontend/src/App.vue`
- 已实现多文件选择后逐个上传；文件列表展示状态、失败原因、重试次数、下载和删除入口。
- 已实现 retrieve-only 检索表单，支持 `question/top_k/threshold`。
- 已实现结果展示：片段内容、分数、rank、文件名、页码/段落位置和下载入口。
- 已验证 `npm run build` 通过，Vite dev server 可在 `http://127.0.0.1:5173/` 打开。

## T10. 前端管理页

- [x] T10.1 实现系统状态卡片
- [x] T10.2 实现配置表单
- [x] T10.3 实现调度状态和立即执行按钮
- [x] T10.4 实现任务日志和失败明细

完成标准：

- 管理页可完成状态查看、配置修改、任务触发和失败排障。

T10 结果：

- 管理页集成在 `frontend/src/App.vue` 的“管理”视图。
- 已实现系统状态卡片：文件状态统计、segment 统计、LightRAG 工作目录和 search mode。
- 已实现配置表单：读取 `/admin/configs`，编辑后通过 `PUT /admin/configs` 保存。
- 已实现调度状态和“立即执行”按钮，对接 `/admin/scheduler/status` 和 `/admin/scheduler/trigger`。
- 已实现最近调度日志展示：触发方式、状态、处理数、失败数、耗时、错误信息和 details。
- 已通过真实后端 HTTP 冒烟验证管理接口可访问。

## T11. 全链路测试与验收

- [x] T11.1 后端单元测试和接口测试
- [x] T11.2 文件解析异常测试
- [x] T11.3 删除后检索过滤测试
- [x] T11.4 调度器并发锁测试
- [x] T11.5 前端上传到检索闭环验证
- [x] T11.6 整理 README 启动说明和演示步骤

完成标准：

- 从上传文件到索引完成再到检索片段的链路可演示。
- 失败、删除、重试、配置变更都有明确验证。
- README 能指导新开发者启动项目。

T11 结果：

- 自动化测试：新增 `backend/tests/test_parser_and_chunker.py`，覆盖 TXT/MD 解析、空文件错误、不支持格式错误和注入 tokenizer 的 overlap 分片；`python -m pytest tests` 已通过，4 passed。
- 后端接口验证：`GET /health`、`POST /upload`、`GET /files`、`GET /files/{file_id}`、`GET /files/{file_id}/download`、`DELETE /files/{file_id}`、`POST /retrieve`、`/admin/*` 已通过真实 HTTP 或 TestClient 验证。
- 文件解析异常验证：空 TXT、加密 PDF、不支持格式分别进入明确错误路径；解析失败会写回 `files.failed/error_code/error_msg`。
- 删除过滤验证：删除后文件状态进入 `deleting`，segment 变为 `deleted`，retrieve 响应层只返回 `completed/indexed`，因此删除文件立即不可见；调度清理后进入 `deleted`。
- 调度器验证：pending 文件可完成真实 LightRAG 索引；PostgreSQL advisory lock 被占用时任务返回 `skipped`；processing 超时文件可回收。
- 前端闭环验证：后端和前端服务已启动，上传、手动触发索引、文件完成、检索返回引用、删除和后台清理链路已完成。
- README 已补充环境准备、数据库迁移、启动服务、演示流程和常用命令。

## 当前进度

- 当前阶段：T0-T11 已完成，进入人工验收和后续优化阶段。
- 最近更新：2026-07-06，完成前端工作台、管理页、README、真实 LightRAG 检索闭环、删除清理和最终构建验收。
