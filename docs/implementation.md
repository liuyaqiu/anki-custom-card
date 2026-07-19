# 实施记录

本文档跟踪架构设计的分阶段实现。每一阶段先定义可观察行为和测试，再添加最小实现，最后执行完整质量门禁。

## 工程约定

- mise 锁定并安装 Python 与 uv。
- uv 解析、锁定并安装 Python 依赖，`uv.lock` 必须提交。
- Makefile 是本地开发、测试和容器操作的统一入口。
- Docker 构建部署镜像，Docker Compose 管理本地运行和隔离测试。
- 新功能或缺陷修复必须先添加能失败的测试，再实现并通过 `make check`。
- 单元测试不访问网络、Anki 或真实云服务；外部集成使用 adapter contract test 和受控 integration test。

## 阶段一：领域与运行基础

### 1A：工程骨架（已完成）

- [x] 锁定 Python 3.12.13 与 uv 0.11.29。
- [x] 建立 `src` layout 和 uv 依赖锁。
- [x] 建立 FastAPI application factory 与 `/api/health`。
- [x] 建立 `ACC_` 配置边界，并拒绝本地模式监听非 loopback 地址。
- [x] 建立 SQLAlchemy engine factory。
- [x] 为 SQLite 启用 foreign keys、WAL 和 5 秒 busy timeout。
- [x] 提供 Makefile、Dockerfile、Compose 运行服务和 Compose 测试服务。
- [x] 添加首批单元测试和覆盖率门禁。

### 1B：领域模型与迁移（已完成）

- [x] 配置 Alembic，并提供 `make migrate` 与 `make migration`。
- [x] 以测试定义 Note、NoteRevision 和业务唯一性。
- [x] 实现 `word_idx` 从 0 开始及 NFKC/空白折叠/casefold 英文规范化规则。
- [x] 实现基于 `expected_version` 的乐观版本更新和不可变 revision 快照。
- [x] 定义 GenerationJob、Draft、Artifact 和数据库级级联删除所有权。
- [x] 添加 Repository contract tests 和 Alembic upgrade/downgrade/upgrade 迁移测试。
- [x] 将 Alembic 与 SQLAlchemy metadata 纳入生产镜像，并支持 `ACC_DATABASE_URL`。
- [x] 生产容器启动时先执行 `alembic upgrade head`，迁移失败则不启动服务。

### 1C：媒体与任务基础（已完成）

- [x] 以测试定义 SHA-256 内容寻址、MIME 白名单、安全路径和原子文件写入。
- [x] 实现 Media 与 NoteMedia 引用关系，以 SQLite upsert 支持多进程内容去重。
- [x] 实现无引用媒体的事务化记录清理，并在提交后删除对应本地文件。
- [x] 实现持久化 Job、数据库原子租约、所有者校验、重试和过期恢复。
- [x] 以测试覆盖多 worker 竞争、过期租约、最终失败和媒体垃圾回收。

## 阶段二：内容生成与确认

### 2A：结构化生成边界与词典缓存（已完成）

- [x] 定义严格、Provider 中立的 DictionaryOutput schema。
- [x] 定义纯数据 CardDraft 与 Azure Speech 文本计划，拒绝模型生成 HTML。
- [x] 定义 DictionaryProvider 与 CardComposer 两阶段协议。
- [x] 建立包含 Provider、模型、prompt/schema/config 版本的确定性缓存键。
- [x] 实现多进程安全的 SQLite Dictionary Cache、显式失效和 Artifact 证据引用。
- [x] 添加 schema、缓存键、Repository 和迁移测试。

### 2B：OpenAI 两阶段生成（已完成）

- [x] 实现 OpenAIDictionaryProvider，并以 Responses API Structured Outputs 生成 synthetic DictionaryOutput。
- [x] 实现 OpenAICardComposer，将显式、已持久化的 DictionaryOutput 整合为 CardDraft。
- [x] 实现 generation orchestration、缓存复用、两阶段 artifact 保存和独立恢复。
- [x] 实现 Provider response ID 审计、可重试/不可重试 OpenAI 错误分类和任务失败状态。
- [x] 使用 fake client 完成无网络 contract tests，并提供必须显式启用的 `make smoke-openai`。

### 2C：Azure Speech 与草稿确认（已完成）

- [x] 实现 Azure Speech REST adapter、SSML 安全转义、请求错误分类和 MP3 输出。
- [x] 实现按文本、locale、voice、格式和配置版本寻址的语音缓存。
- [x] 实现可恢复的单词/例句音频生成、Artifact 媒体证据和缓存引用保护。
- [x] 实现 Draft 乐观版本编辑与只允许一次确认的状态转换。
- [x] 实现确认时创建或乐观更新 Note、写 revision 并原子绑定音频。

## 后续阶段

- 阶段三：AnkiConnect、专用 Note Type、幂等发布和归档删除。
- 阶段四：偏移检测、恢复、安全加固与端到端验收。
