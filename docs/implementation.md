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

## 阶段三：Anki 发布（已完成）

- [x] 实现 AnkiConnect v6 HTTP adapter、稳定错误分类和只读 smoke 检查。
- [x] 实现带版本的专用 Basic Note Type、字段 schema、模板和 night mode CSS。
- [x] 实现内容寻址媒体文件名、SourceId 恢复映射、幂等创建与更新。
- [x] 实现发布 read-back 校验、发布状态、错误记录和固定 revision 发布。
- [x] 将确认 Note、publication intent 和 publish job 纳入同一 SQLite 事务。
- [x] 实现 worker 指数退避、发布期间版本变化后的最新版本追赶。
- [x] 实现 archive_pending、删除任务、幂等删除、确认读取和删除 tombstone。

本地安装并启用 AnkiConnect 后，可运行 `make smoke-anki` 检查端点；该检查不修改 Anki 数据。

## 阶段四：校验与完善（已完成）

- [x] 实现只读 Anki inspection，以规范化字段哈希区分 published、drifted 和 missing。
- [x] 返回字段级差异摘要；Anki 不可用时保留已有判断，且不反向修改本地 Note。
- [x] 将 inspect 纳入持久化 job handler，保留租约、多 worker 与重试约束。
- [x] 区分可重试和不可重试发布错误，并支持显式重置选定的 failed job。
- [x] 增加媒体大小限制、已知文件签名与声明 MIME 不匹配检测。
- [x] 增加 `/api/health/anki`，只暴露连接状态、协议版本和稳定错误码。
- [x] 增加 SQLite 与媒体目录的一体化备份、恢复演练和失败任务运维说明。
- [x] 以受控 Fake Anki 完成发布、版本追赶、偏移、缺失、重建和归档删除验收。

阶段四不增加双向同步：inspection 始终只观察 Anki。

## 阶段五：可操作的本地应用（已完成）

- [x] 使用 FastAPI lifespan 装配 SQLite、媒体、OpenAI、Azure Speech 和 AnkiConnect。
- [x] 实现轮询持久化 jobs 的本地 worker，继续使用数据库租约支持多进程竞争与重启恢复。
- [x] 实现 generation、draft、note、publication、inspection、archive 和 job retry JSON API。
- [x] 曾以 Jinja2/HTMX 完成 MVP 验证；该实现已在阶段六完成后移除。
- [x] 实现草稿预览/编辑/确认、Note 编辑、发布、检查、归档和失败任务重试界面。
- [x] 为状态变更 API 和 HTML 表单加入 cookie 绑定 CSRF 校验，并加入基础安全响应头。
- [x] 添加真实 FastAPI TestClient 工作流与 worker 生命周期测试。

阶段五的服务端模板仅作为历史实施记录；当前构建不再包含 Jinja2、HTMX 或远程前端 CDN。

## 阶段五改进：多语义与美式英语（已完成）

- [x] 移除生成和 Note 编辑中的领域选择，改由模型分类；内容策略固定为 IT、职场优先并兼顾一般语义。
- [x] 新词默认创建三个不同 `word_idx` 的生成任务，prompt 要求候选按语义或实际应用场景去重。
- [x] Dashboard 和词汇详情页按规范化词汇聚合展示多个 Note 与生成草稿。
- [x] 支持重新生成某个词汇的全部 active Note，或只重新生成指定 Note；确认后沿用乐观版本更新。
- [x] Dictionary、Card prompt 强制 General American IPA、美国拼写与自然美式例句。
- [x] 配置层拒绝非 `en-US` Azure locale/voice，确保单词和例句音频均为美语。
- [x] Anki 模板升级到 v2，增加语义标签、分区卡面、例句强调、可选字段和 night mode。
- [x] 已有同词归档记录不会复用 `word_idx`，避免重新创建候选时触发业务唯一键冲突。
- [x] 为 `archived` Note 提供带 CSRF 和确认提示的彻底删除入口，级联清理专属生成数据、作业历史及无引用媒体；活动或归档中的 Note 拒绝删除。
- [x] Notes 目录展示全部历史 Note 并按词汇聚合，详情页按 `word_idx` 切换；生成与重新生成使用数据库唯一请求键实现跨进程幂等复用。

## 阶段六：Vue SPA 迁移（已完成）

- [x] 通过 Mise 固定 Node，使用 npm lockfile、Vue 3、TypeScript、Vite、Vue Router 和 TanStack Query 建立 `frontend/`。
- [x] 增加聚合 words API，使尚未生成 Note 的 generation 也立即出现在词汇目录。
- [x] 迁移 Notes 目录、Word/idx、Draft 编辑确认和 Note 完整管理界面。
- [x] generation 与 job 在 active 状态每秒轮询；publish、inspect、archive 终态后自动刷新 Note 和词汇缓存。
- [x] FastAPI 支持 `/app/` 入口、静态哈希资源和 SPA 深链接回退。
- [x] Docker 使用 Node 构建阶段并只向 Python 运行镜像复制 `dist`；Makefile 统一前后端安装、测试、类型检查和构建入口。
- [x] 添加前端轮询/CSRF 测试，以及 words API、SPA 入口、静态资源和深链接集成测试。
- [x] 将 Draft 编辑、Note 编辑、失败任务重试及彻底删除迁移为原生 Vue 组件。
- [x] 删除 Jinja/HTMX 路由、模板、CSS、Python 依赖及所有 SPA 内旧 UI 链接；根路径与历史 `/ui/...` 地址统一进入 SPA。

## 阶段七：卡片预览与模板同步（已完成）

- [x] 将服务专用 Basic 模板升级到 v3，正面采用居中布局并加入英文例句与例句音频，保持例句中文翻译仅在背面展示。
- [x] 增加基于同一份模板、CSS 和字段映射的服务端预览 API，以及 Vue 正反面 iframe 预览页面。
- [x] 为预览音频提供按 Note 关联读取的只读媒体端点。
- [x] 增加显式、CSRF 保护的模板同步 API 和首页操作；同步前校验 Note Type 字段兼容性。
- [x] 使用模板单元测试、Web API 集成测试、前端 API 与预览文档测试约束上述行为。
- [x] 将模板升级到 v4，移除背面的 `{{FrontSide}}` 嵌入，使答案面保持独立且不重复整块正面内容。
