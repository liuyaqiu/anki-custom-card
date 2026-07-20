# Anki Custom Card

Anki Custom Card 是一个本地运行的 AI 辅助制卡服务。它面向高级英语学习者，重点支持职场英语和 IT 语境：从单词生成简短中文释义、英文释义、自然例句、用法信息和语音，经人工预览与编辑后保存为 Note，并单向发布到 Anki。

本项目的主要目标不是批量制作更多卡片，而是降低高质量主动输出型卡片的制作成本，让用户保留对最终学习内容的控制。

## 核心流程

```text
word
  -> AI / dictionary / TTS providers
  -> artifacts
  -> editable draft
  -> user confirmation
  -> Note committed to local database
  -> published to Anki
```

AI 生成的内容始终是草稿。用户可以预览和修改，确认后才会成为正式 Note。正式 Note 保存成功与发布到 Anki 成功是两个独立阶段：即使 Anki 未运行，已经确认的内容也不会丢失，并可在之后重试发布。

## 产品原则

### 服务是唯一事实来源

- 由本服务管理的 Note 以本地数据库中的内容为准。
- Anki 是学习终端和发布目标，不是这些 Note 的编辑端。
- 服务不会将 Anki 侧的修改自动导回并覆盖本地内容。
- 服务会检测 Anki 副本是否被修改或删除，并允许用户用本地版本重新发布。
- 产品界面和代码统一使用 `Note` 表示业务数据；Anki Card 仅指由模板生成的复习卡片。

### 单向发布，而非双向同步

发布方向固定为：

```text
local database -> Anki
```

每个 Note 都使用稳定的服务端 ID 和版本号。系统记录已发布版本、Anki Note ID、内容指纹及错误信息，使创建和更新可以安全重试，并避免重复创建。

### 本地优先

- 服务默认仅监听 `127.0.0.1`；可通过 `ACC_HOST` 显式绑定受信任的宿主机私网地址。
- SQLite 保存结构化数据。
- 媒体文件保存在服务管理的本地目录，并按需复制到 Anki。
- 首版通过本机 AnkiConnect 与 Anki 通信。
- 远程部署、多用户和本地 Agent 不属于首版范围。

## 首版范围

### 包含

- 基于 Python 的本地 Web 服务和简单管理界面。
- 输入单词并生成简短中文释义、英文释义、职场/IT 相关例句、例句翻译和语音。
- 缓存获得授权的词典 API 原始数据，并以词典事实约束 AI 生成结果。
- 使用 GPT-5.6 Luna 生成结构化文本草稿，使用 Azure AI Speech 生成音频。
- 保存 AI、词典和 TTS 调用产生的原始 artifacts。
- 草稿预览、人工编辑与确认。
- Note 浏览、修改、归档、彻底删除和重新生成。
- 使用 SQLite 保存 Note、版本、生成记录和发布状态。
- 使用本地文件保存音频等媒体资源。
- 管理一个专用的普通正反面 Note Type；一个 Note 生成一张 Card。
- 将确认后的 Note 单向发布到 Anki。
- 发布失败重试、幂等创建、版本跟踪和 Anki 偏移检测。
- 读取本服务管理的 Anki Note，用于校验和状态展示。

## 本地界面

完成 `.env` 中的 OpenAI、Azure Speech 和 AnkiConnect 配置后，启动：

```bash
make run
```

Vue SPA 位于 <http://127.0.0.1:8000/app/>，访问根路径会自动跳转到该地址。Jinja/HTMX 界面及其依赖已经删除；历史 `/ui/...` 地址只用于把旧书签重定向到 SPA。一次输入默认生成三个不同语义或应用场景的候选 Note，并按词汇聚合浏览；目录会立即显示尚在生成中的词，进入词汇后可按 `word_idx` 切换。SPA 原生支持草稿编辑与确认、Note 编辑、卡片正反面渲染预览、重新生成、发布、检查、归档、彻底删除和失败任务重试。首页的“同步卡片模板到 Anki”操作可显式将当前版本的 HTML/CSS 更新到服务专用 Note Type。

SPA 在 generation、publish、inspect 和 archive 运行期间自动轮询，任务进入终态后刷新相关缓存并停止轮询。

内容优先采用真实的 IT 与职场语境，同时兼顾重要的一般用法。生成请求使用数据库唯一请求键保证多进程幂等，重复提交会复用已有任务。所有英文内容、IPA 和 Azure Speech 音频统一使用美式英语。

JSON API 位于 `/api`，OpenAPI 文档位于 `/docs`。所有状态变更 API 都要求把 `acc_csrf` cookie 的值作为 `X-CSRF-Token` 请求头发送。

前端由 Mise 固定 Node 版本，并使用锁文件安装依赖：

```bash
make frontend-install
make frontend-test
make frontend-build
```

需要前后端热更新时，分别运行 `make run` 和 `make frontend-dev`；Vite 会把 `/api` 代理到 FastAPI。

### 暂不包含

- 从 Anki 双向同步内容。
- 在 Anki 中编辑由本服务管理的 Note。
- Cloze、反向卡片或其他 Note Type。
- 多用户、远程部署和跨设备协作。
- 完全复刻 Anki 的渲染环境。
- 学习效果分析和自动反馈闭环。
- 自动解决内容冲突。

## Note 标识规则

同一个单词允许对应多个 Note。业务唯一性由以下组合确定：

```text
(language, word_normalized, word_idx)
```

- `word_display` 保留用户输入的原始形式。
- `word_normalized` 用于比较和唯一性约束。
- `word_idx` 从 `0` 开始，是创建后保持稳定的整数，不因其他 Note 删除而重新编号。
- 可选的 `variant` 用于向用户说明词性、词义或场景等区别。
- 数据库内部 ID 才是 Note 的稳定技术身份；`word + word_idx` 不用于替代主键或 Anki 映射。

## 媒体管理

- 服务目录中的媒体是权威副本，Anki 媒体是发布副本。
- 文件按内容哈希命名，避免重名并支持去重。
- 数据库保存哈希、MIME 类型、大小和相对路径，不保存机器相关的绝对路径。
- Note 与媒体采用显式关联；归档 Note 不会立即永久删除服务侧媒体。
- 无引用媒体可由后续垃圾回收机制清理。

## 生命周期约定

- 词典 API 原始数据和生成 artifacts 默认无限期保存，用于减少确定性查询和保留生成依据。
- 删除本地业务条目时，其独占 artifacts 必须级联删除；共享媒体只有在无引用后才能回收。
- 归档 Note 会产生删除 Anki 副本的持久化任务。只有 Anki 确认删除后，归档才算完成。
- Anki 不可用时 Note 保持 `archive_pending`，服务保存删除意图并持续重试，避免遗忘远端副本。
- 只有 `archived` Note 才允许彻底删除。该操作不可撤销，并清除其 revisions、发布记录、关联生成任务、drafts、artifacts、队列历史，以及不再被其他 Note 使用的媒体缓存和本地文件；共享缓存数据仍会保留。

## Anki 使用约定

服务维护专用的 Note Type、字段、模板、标签和稳定来源标识，不依赖用户可能已经修改的内置 `Basic` 类型。首版仍属于普通 Basic 模式：一个 Note 通过一个正反面模板生成一张 Card。

当前模板 v4 的正面采用垂直和水平居中布局，显示词汇、词性、美式音标、单词音频、英文例句及例句音频，但不显示例句中文翻译；背面使用独立答案布局，不嵌入完整正面，仅展示释义、例句答案、翻译、搭配和用法。Web 预览直接使用同一套服务端模板与 CSS 渲染，便于发布前核对。

由于 Anki 本身无法对单个 Note 提供可靠的只读锁，“不在 Anki 中编辑”是一项使用约定。服务通过内容指纹检测偏移；发现 Anki 副本与最近发布版本不一致时，将其标记为异常并由用户决定是否重新发布本地版本。

## 架构设计

首版的模块边界、数据模型、状态机和关键发布流程见 [架构设计](docs/architecture.md)。

本地数据库、媒体备份和失败恢复流程见 [运维与恢复](docs/operations.md)。

## 开发

项目使用 mise 管理 Python 与 uv，使用 uv 管理 Python 依赖，并通过 Makefile 提供统一入口：

```bash
mise trust
make setup
make migrate
make check
make run
```

配置 `ACC_OPENAI_API_KEY` 后，可显式执行会产生 API 费用的两阶段真实调用检查：

```bash
make smoke-openai
```

配置 `ACC_AZURE_SPEECH_KEY` 和 `ACC_AZURE_SPEECH_REGION` 后，可验证真实 MP3 语音合成：

```bash
make smoke-azure
```

修改 SQLAlchemy schema 后生成迁移：

```bash
make migration MESSAGE="describe the schema change"
make migrate
```

容器化操作：

```bash
make docker-build
make docker-up
make docker-test
make docker-down
```

Compose 将数据库和媒体保存在仓库的 `data/` 目录。迁移到另一台机器时需要在应用
停止后复制整个 `data/`；仅复制 Git 跟踪的文件不会包含 Notes。旧版 Compose
命名卷的迁移步骤及一致性备份方法见 [运维与恢复](docs/operations.md)。

环境变量示例见 `.env.example`，实施进度见 [实施记录](docs/implementation.md)。服务默认只通过宿主机的 `127.0.0.1:8000` 暴露。若需要从可信局域网访问，可设置例如 `ACC_HOST=192.168.88.9` 后执行 `docker compose up -d --build app`；Compose 不再覆盖该值。出于安全考虑，服务拒绝公网地址、主机名和 `0.0.0.0`，且当前没有用户认证，不应暴露到不可信网络。
