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

- [ ] T3.1 实现 `files` ORM 模型和迁移
- [ ] T3.2 实现 `file_segments` ORM 模型和迁移
- [ ] T3.3 实现 `system_configs` ORM 模型和默认配置初始化
- [ ] T3.4 实现 `scheduler_logs` ORM 模型和迁移
- [ ] T3.5 添加基础模型单元测试或迁移校验

完成标准：

- Alembic 可创建全部应用表。
- 文件状态、重试字段、片段引用字段与设计文档一致。
- 默认系统配置可初始化。

## T4. 文件管理 API

- [ ] T4.1 实现 `POST /upload` 单文件上传
- [ ] T4.2 实现 `GET /files` 文件列表
- [ ] T4.3 实现 `GET /files/{file_id}` 单文件状态
- [ ] T4.4 实现 `GET /files/{file_id}/download` 原文下载
- [ ] T4.5 实现 `DELETE /files/{file_id}` 删除标记和读路径隐藏
- [ ] T4.6 补充文件大小、扩展名、空文件等校验

完成标准：

- 文件可上传到本地 `uploads/`。
- 上传后状态为 `pending`。
- 文件列表默认不展示 `deleted`。
- 删除后文件不会参与后续检索响应。

## T5. 文档解析与应用层分片

- [ ] T5.1 实现 TXT/MD 解析
- [ ] T5.2 实现 PDF 解析并保留页码
- [ ] T5.3 实现 DOCX 解析并保留段落序号
- [ ] T5.4 实现 token 分片和 overlap
- [ ] T5.5 将分片写入 `file_segments`
- [ ] T5.6 区分不可重试解析错误：加密 PDF、空内容、不支持类型

完成标准：

- 支持 PDF、DOCX、TXT、MD。
- 每个 segment 包含内容、位置类型、位置值、顺序号。
- 解析失败能写入明确 `error_code/error_msg`。

## T6. LightRAGClient 与检索链路

- [ ] T6.1 实现 `LightRAGClient.insert_segments()`
- [ ] T6.2 实现 `LightRAGClient.query()`
- [ ] T6.3 实现 `LightRAGClient.delete_file()`
- [ ] T6.4 实现 `POST /retrieve`
- [ ] T6.5 检索结果通过 `segment_id` 回查 `file_segments + files`
- [ ] T6.6 过滤非 `completed/indexed` 的文件和片段

完成标准：

- 检索接口只返回片段，不生成答案。
- 响应包含 `segment_id/content/score/rank/citation`。
- `search_mode` 使用管理员配置，不由普通请求传入。

## T7. 调度器与索引任务

- [ ] T7.1 内嵌 APScheduler
- [ ] T7.2 实现 PostgreSQL advisory lock
- [ ] T7.3 实现 pending 文件扫描和批处理
- [ ] T7.4 实现 processing 超时回收
- [ ] T7.5 实现可重试失败策略：`retry_count/next_retry_at/max_retries`
- [ ] T7.6 实现 `scheduler_logs` 写入
- [ ] T7.7 实现管理员立即触发索引任务

完成标准：

- 定时任务可自动索引 pending 文件。
- 手动触发和定时触发不会并发执行。
- 可重试错误会有限次自动重试。
- 卡住的 processing 文件可被回收。

## T8. 管理 API

- [ ] T8.1 实现 `GET /admin/status`
- [ ] T8.2 实现 `GET /admin/configs`
- [ ] T8.3 实现 `PUT /admin/configs`
- [ ] T8.4 实现 `GET /admin/scheduler/status`
- [ ] T8.5 实现 `POST /admin/scheduler/trigger`
- [ ] T8.6 实现 `GET /admin/scheduler/logs`

完成标准：

- 管理端可查看文件统计、segment 统计、调度状态和最近日志。
- 管理端可修改索引、检索、调度、LLM 配置。
- 配置生效范围与 `docs/design.md` 一致。

## T9. 前端工作台

- [ ] T9.1 创建 Vue 前端工程
- [ ] T9.2 实现多文件选择，逐个调用 `POST /upload`
- [ ] T9.3 实现文件列表、状态、错误原因、下载、删除
- [ ] T9.4 实现检索输入和可选 `top_k/threshold`
- [ ] T9.5 实现检索结果片段、分数、文件名、页码/段落展示

完成标准：

- 用户可在一个页面完成上传、查看状态、下载、删除、检索。
- 检索结果引用可回到原文件下载核验。

## T10. 前端管理页

- [ ] T10.1 实现系统状态卡片
- [ ] T10.2 实现配置表单
- [ ] T10.3 实现调度状态和立即执行按钮
- [ ] T10.4 实现任务日志和失败明细

完成标准：

- 管理页可完成状态查看、配置修改、任务触发和失败排障。

## T11. 全链路测试与验收

- [ ] T11.1 后端单元测试和接口测试
- [ ] T11.2 文件解析异常测试
- [ ] T11.3 删除后检索过滤测试
- [ ] T11.4 调度器并发锁测试
- [ ] T11.5 前端上传到检索闭环验证
- [ ] T11.6 整理 README 启动说明和演示步骤

完成标准：

- 从上传文件到索引完成再到检索片段的链路可演示。
- 失败、删除、重试、配置变更都有明确验证。
- README 能指导新开发者启动项目。

## 当前进度

- 当前阶段：T2 后端工程骨架已完成，下一步进入 T3 数据模型与迁移。
- 最近更新：2026-07-02，完成 FastAPI 后端骨架、健康检查、SQLAlchemy async 会话、Alembic 配置和基础错误响应。
