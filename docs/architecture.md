# 架构设计

## 1. 目标与约束

首版采用本地模块化单体 Web 应用，负责生成、编辑和持久化 Note，并通过 AnkiConnect 将确认后的版本单向发布到本机 Anki。

架构必须满足：

- 本地数据库始终是业务数据的唯一事实来源。
- AI、TTS 或 Anki 失败不影响已有 Note。
- Anki 未启动或发布失败不影响正式 Note 的提交。
- 发布操作可安全重试且不会重复创建 Anki Note。
- 长时间外部调用不持有 SQLite 写事务。
- 首版保持单机、单用户和低运维成本，同时为增加 Provider 和 Note Type 留出边界。
- 内容面向高级英语学习者，以英文释义和自然例句为核心，中文释义保持简短，并优先覆盖职场与 IT 语域。
- 允许多个 Web/worker 进程同时启动；任务执行、版本更新和删除必须依赖数据库协调，不能依赖进程内锁。

## 2. 系统上下文

```text
                         +--------------------+
                         | AI / Dictionary /  |
                         | TTS Providers      |
                         +---------+----------+
                                   ^
                                   |
+---------+     HTTP      +--------+---------+      AnkiConnect     +------+
| Browser | <-----------> | Local Web Service | <-----------------> | Anki |
+---------+               +----+----------+---+                     +------+
                               |          |
                               v          v
                            SQLite    Local Media
```

浏览器只与本地服务通信。Provider 和 AnkiConnect 均由后端调用，密钥不会发送给浏览器。

## 3. 首版技术选择

- Python 3.12 或当前受支持版本。
- FastAPI：HTTP API、依赖注入和请求校验。
- Pydantic：API 与 Provider 边界的数据结构。
- SQLAlchemy 2.x 和 Alembic：持久化与数据库迁移。
- SQLite：本地业务数据和任务状态。
- Jinja2 加少量渐进增强 JavaScript：首版管理界面。
- 应用内后台任务执行器：处理生成和发布；任务必须持久化到 SQLite。
- AnkiConnect：Anki Note、Note Type 和媒体发布。
- OpenAI Responses API：默认使用 `gpt-5.6-luna` 和 Structured Outputs 生成结构化草稿。
- Azure AI Speech：使用神经语音和 SSML 生成单词及例句音频。
- 获得持久化授权的第三方词典 API：提供词义、词性、音标、词形和来源 sense；具体供应商通过 Provider 配置选择。

若前端后续变复杂，可独立为 SPA；领域模型和 HTTP API 不依赖这一选择。

## 4. 模块划分

```text
app/
  api/             HTTP routes and schemas
  application/     use cases and transaction boundaries
  domain/          entities, value objects and state rules
  persistence/     SQLAlchemy models and repositories
  generation/      generation orchestration and provider ports
  media/           local media store and metadata
  publishing/      Anki publication orchestration
  integrations/
    anki_connect/  AnkiConnect adapter
    ai/            AI provider adapters
    dictionary/    dictionary provider adapters
    tts/           Azure Speech and future TTS adapters
  workers/         persistent job polling and execution
  web/             templates and static assets
```

依赖方向为外层适配器指向应用和领域层。领域层不直接依赖 FastAPI、SQLAlchemy、AnkiConnect 或具体 AI SDK。

- **Note**：管理 Note 身份、内容、版本、唯一性和归档；正式内容更新必须增加版本号。
- **Generation**：调用文本、词典和 TTS Provider，保存 artifacts 并形成可编辑草稿，但不自动提交正式 Note。
- **Media**：负责文件校验、SHA-256 寻址、原子写入、去重和 Note 引用关系。
- **Publishing**：把 Note 的特定版本转换为 Anki 字段与媒体，并执行幂等创建或更新。
- **Inspection**：读取本服务管理的 Anki Note，用于健康检查、偏移检测和状态展示，禁止自动反写本地 Note。
- **Dictionary Cache**：以 Provider、查询规范和版本为键保存授权词典的原始响应，默认无期限，支持显式失效与清理。

## 5. 领域模型

### 5.1 Note

```text
notes
  id                    UUID / ULID, primary key
  language              e.g. "en"
  word_display
  word_normalized
  word_idx
  variant               nullable
  domain                general | workplace | it
  part_of_speech        nullable
  source_sense_ids      JSON
  definition_en
  definition_zh
  example
  example_zh
  pronunciation         nullable
  collocations          JSON
  usage_notes           nullable
  extra                 nullable
  status                active | archive_pending | archived
  version               integer
  created_at
  updated_at

note_revisions
  note_id
  version
  content                JSON, immutable snapshot
  content_hash
  created_at
```

约束：

```text
UNIQUE(language, word_normalized, word_idx)
CHECK(word_idx >= 0)
CHECK(version >= 1)
UNIQUE(note_id, version)
```

`notes` 保存当前可查询状态，`note_revisions` 保存每次确认后的不可变内容快照。发布任务只读取其目标 revision，不能从可能已经更新的 `notes` 行临时重建旧版本。

`word_idx` 从 `0` 开始。`word_normalized` 由语言相关的 Normalizer 生成。首版英文采用 Unicode NFKC、去除首尾空白、折叠连续空白和大小写归一化；展示始终使用 `word_display`。

### 5.2 Dictionary Cache

```text
dictionary_cache_entries
  id
  provider
  provider_dataset      nullable
  request_key           unique with provider/dataset
  provider_config_version
  prompt_version         nullable for non-AI providers
  schema_version
  model                  nullable for non-AI providers
  normalized_query      JSON
  response_payload      JSON
  response_hash
  source_entry_ids      JSON
  fetched_at
  expires_at            nullable, null means no automatic expiry
  invalidated_at        nullable
```

只有明确允许长期保存 API 数据及派生数据的 Provider 才能启用持久缓存。缓存命中时不重复请求；用户可主动失效或清除缓存。缓存记录与 Note/Artifact 的证据引用分离，即使多个生成任务使用同一结果，也只保存一份原始响应。

### 5.3 Generation、Artifact 与 Draft

```text
generation_jobs
  id
  input_word
  language
  source_note_id         nullable
  status                pending | running | succeeded | failed
  provider_config       JSON
  error_code            nullable
  error_message         nullable
  created_at
  started_at             nullable
  finished_at            nullable

artifacts
  id
  generation_job_id
  dictionary_cache_id    nullable
  artifact_type         definition | example | translation | audio | raw_response
  provider
  model                  nullable
  prompt_version         nullable
  structured_content     JSON, nullable
  raw_content            text, nullable
  media_id               nullable
  created_at

drafts
  id
  generation_job_id
  source_note_id         nullable
  content                JSON
  status                 editable | confirmed
  version
  confirmed_note_id      nullable
  created_at
  updated_at
```

Artifact 是外部调用的原始产物；Draft 是经过校验、可编辑的候选数据；Note 是用户确认后的正式数据。更新 Note 时，只有确认 Draft 才会以乐观锁更新正式内容。

Artifacts 默认无限期保存。`generation_jobs -> artifacts`、`drafts -> generation_jobs` 等所有权外键使用明确的级联删除或等价应用事务；硬删除所属业务记录后不得留下孤儿 artifact。共享的词典缓存不因某个生成任务删除而级联删除，只能显式清理。

### 5.4 Media

```text
media
  id
  sha256                 unique
  media_type             audio | image
  mime_type
  byte_size
  relative_path
  created_at

note_media
  note_id
  media_id
  usage                  word_audio | example_audio | image
```

文件写入流程为：写临时文件、校验并计算哈希、原子移动到哈希路径、提交元数据。数据库只保存相对路径。

Azure Speech 的音频缓存键由规范化文本、locale、voice、完整 SSML、输出格式和 Provider 配置版本共同计算。默认输出使用 Anki 广泛支持的 MP3；初始建议 `audio-24khz-96kbitrate-mono-mp3`，作为可配置项。SSML 用于固定美式或英式 voice、适中的学习语速，以及 IT 缩写或专有名词的发音。

```text
speech_cache_entries
  cache_key              unique
  provider
  config_version
  text
  locale
  voice
  ssml
  output_format
  media_id
  created_at
```

### 5.5 Anki Publication

```text
anki_publications
  note_id                primary key
  anki_note_id           nullable, unique
  target_deck
  target_note_type
  published_version      nullable
  publishing_version     nullable
  published_hash         nullable
  observed_anki_hash     nullable
  status                 pending | publishing | published | failed | drifted | missing |
                         deleting | deletion_failed | deleted
  last_error_code        nullable
  last_error_message     nullable
  attempt_count
  last_attempt_at        nullable
  published_at           nullable
  updated_at
```

发布记录与 Note 分离，因此发布失败不会污染 Note 的领域状态。

### 5.6 Persistent Job

```text
jobs
  id
  job_type               generate | publish | inspect | delete_anki
  aggregate_id
  target_version         nullable
  payload                JSON
  status                 pending | running | succeeded | failed
  available_at
  attempts
  max_attempts
  locked_by              nullable
  locked_at              nullable
  lease_expires_at       nullable
  last_error             nullable
  created_at
  updated_at
```

`jobs` 是进程重启后的恢复依据，不依赖 Redis 或外部队列。任意多个 worker 都可轮询，但必须通过 SQLite 原子条件更新抢占租约；每个 job 同一时刻只能有一个有效 owner。

## 6. Note 版本与并发控制

用户打开编辑页面时获得 Note 当前版本。确认保存时执行条件更新：

```sql
UPDATE notes
SET ..., version = version + 1
WHERE id = :id AND version = :expected_version;
```

未更新任何行表示内容已经变化，应返回冲突并要求重新加载。SQLite 事务只覆盖本地数据更新和任务写入，不覆盖 Provider 或 AnkiConnect 调用。

发布任务固定绑定 `target_version`，并从 `note_revisions` 读取不可变快照。若 v3 发布过程中 Note 已更新为 v4，v3 可以完成并记录为 Anki 当前版本，但系统不能把 Note 标记为最新；v4 仍须发布。只有 `published_version == note.version` 才表示完全发布。

## 7. 关键流程

### 7.1 内容生成策略

```text
1. 规范化 word、language、word_idx 和目标 domain。
2. 以 Provider、规范化查询、配置版本、prompt/schema 版本和模型构造缓存键。
3. 查询 Dictionary Cache；未命中时调用 DictionaryProvider 得到严格 DictionaryOutput。
4. 首版由 OpenAIDictionaryProvider 使用 GPT-5.6 Luna 模拟词典；未来可替换为获得持久化授权的词典 API。
5. 持久化完整 DictionaryOutput 后，将其作为显式输入交给独立的 CardComposer。
6. OpenAICardComposer 根据 word_idx、职场/IT 偏好和严格 CardDraft Schema 整合最终字段。
7. 程序验证字段完整性、sense 引用、例句、长度和禁止 HTML 等业务规则。
8. Azure Speech 根据候选 CardDraft 中的 speech plan 生成单词与例句音频。
9. 分别保存两次模型调用的 artifacts，并形成 editable draft。
```

DictionaryOutput 是 Provider 中立的词汇证据结构。由 GPT 模拟时必须标记为 synthetic，不能表示成权威词典事实。词典输出与 CardDraft 分开保存，第二次调用显式读取已持久化 JSON，而不依赖隐式会话状态；因此可以单独重试、重放或替换任一 Provider。例句优先使用职场和 IT 语境，但不能为了贴合领域而扭曲目标词义。AI 只返回纯字段数据，最终 Anki HTML/CSS 始终由服务端版本化模板渲染。

### 7.2 创建 Note

```text
1. 用户输入 word、language 和可选 variant。
2. 服务规范化 word 并建议可用 word_idx。
3. 在短事务中创建 generation job。
4. worker 按内容生成策略调用 Dictionary、OpenAI 和 Azure Speech，并逐项保存 artifacts。
5. 校验成功后创建 editable draft。
6. 用户预览并修改 draft。
7. 用户确认后，在单个事务中：
   - 检查业务唯一约束；
   - 创建正式 Note version 1 及其 revision 快照；
   - 建立媒体引用；
   - 创建 publication 记录和 publish job。
8. 事务提交后立即返回 Note 已保存。
9. worker 异步发布；界面展示发布进度或错误。
```

### 7.3 更新 Note

```text
1. 用户基于 expected_version 编辑或重新生成草稿。
2. 确认时使用乐观锁更新 Note，版本加一，并写入对应的不可变 revision 快照。
3. 同一事务中写入目标版本的 publish job。
4. 已运行的旧版本发布可以结束，但不能覆盖新版本状态。
5. worker 最终将最新版本发布到 Anki。
```

不在用户编辑期间持有数据库锁。“锁定条目”由版本检查、每个 Note 同时最多一个有效发布任务，以及目标版本判断共同实现。

### 7.4 发布到 Anki

```text
1. 从 `note_revisions` 加载 Note 的 target_version 快照和关联媒体。
2. 确保服务专用 Note Type、字段和模板存在且兼容。
3. 使用内容哈希文件名上传缺少的媒体。
4. 若已有 anki_note_id，则更新该 Anki Note。
5. 否则先按稳定来源 ID 查找：
   - 找到唯一结果：恢复映射后更新；
   - 未找到：创建 Anki Note；
   - 找到多个：停止并报告数据异常。
6. 重新读取 Anki Note，计算规范化内容哈希。
7. 在短事务中记录 anki_note_id、版本和哈希。
```

稳定来源 ID 写入专用的 `SourceId` 字段，并同时增加服务标签。幂等判定不能只依靠 word，因为一个 word 可以有多个 Note。

### 7.5 归档与删除 Anki 副本

SQLite 与 AnkiConnect 不能参与同一个原子事务，因此本项目所称的“一致”是持久化删除意图驱动的可恢复收敛，而不是跨系统瞬时强一致：

```text
1. 用户归档 active Note。
2. 单个 SQLite 事务将状态改为 archive_pending，并创建 delete_anki job。
3. 若没有 anki_note_id，直接完成 archived。
4. worker 按 anki_note_id 删除 Anki Note；“已经不存在”也视为幂等成功。
5. 再次查询确认不存在后，将 publication 标记 deleted，Note 标记 archived。
6. Anki 不可用或删除失败时保持 archive_pending/deletion_failed 并按策略重试。
```

`archive_pending` Note 不允许编辑或重新发布，但允许用户查看和手动重试。删除任务和 tombstone 在确认 Anki 删除前不得被垃圾回收。只有本地硬删除才级联删除 revisions、generation jobs、drafts、独占 artifacts 和 Note-media 关联；媒体文件在引用数归零后由垃圾回收删除。

### 7.6 偏移检测

- active Note 的 Anki 副本不存在：标记 `missing`，允许重新创建；`archive_pending`/`archived` Note 不得触发重建。
- 内容哈希与最近发布哈希相同：保持 `published`。
- 内容不同：标记 `drifted`，展示差异摘要并允许用本地版本覆盖。
- AnkiConnect 不可用：只报告连接状态，不改变已有发布结论。

偏移检测只观察 Anki，不自动反向修改本地 Note。

## 8. Anki Note Type 与渲染

服务维护一个带版本的专用 Note Type，不复用用户的内置 `Basic`。初始字段建议为：

```text
SourceId
Word
Domain
PartOfSpeech
Pronunciation
DefinitionEn
DefinitionZh
Example
ExampleZh
Collocations
UsageNotes
WordAudio
ExampleAudio
Extra
```

`SourceId` 是稳定幂等标识，`Domain`、`Collocations` 和 `UsageNotes` 支持职场/IT 学习，两个音频字段分别允许复习单词和完整例句。字段只保存数据；HTML 结构和展示逻辑集中在模板中。

模板遵循 Anki 的常见 Basic 结构：正面突出 `Word`、词性、音标和单词音频；背面先使用 `{{FrontSide}}`，再展示英文释义、简短中文释义、例句、翻译、搭配、用法提示和例句音频。共享 CSS 使用 `.card` 作为根样式，采用系统字体、有限宽度、响应式间距和 `nightMode` 兼容，不依赖外部网络资源或复杂 JavaScript。

模板、CSS 和字段 schema 在代码中明确版本。升级模板必须有显式迁移，不在每次发布时无条件覆盖用户环境。Anki 官方模板采用字段替换的 HTML 和共享 CSS，本设计保持这一惯例。

Web 预览使用与 Anki 模板共享的内容结构和 CSS，但只承诺语义接近；最终渲染仍以 Anki 为准，尤其是音频和 Anki 特有行为。

## 9. 事务与可靠性

采用本地事务加持久化任务实现最终一致性：

```text
SQLite transaction:
  save Note
  save publication intent/job
commit

worker:
  call AnkiConnect
  record result in a new transaction
```

核心规则：

- 不在数据库事务中调用外部服务。
- Provider 和 Anki 错误使用稳定错误码，并保留可读详情。
- 网络错误和 Anki 未运行可指数退避重试。
- 数据校验失败、Note Type 不兼容和重复 SourceId 不自动无限重试。
- worker 启动时恢复超时的 `running` job。
- 创建和更新 API 支持请求幂等键，避免浏览器重复提交。

### 9.1 多进程与 SQLite

- SQLite 启用 WAL、foreign keys 和合理的 `busy_timeout`；写事务保持短小。
- Web 与 worker 进程都不维护影响正确性的内存锁或唯一调度状态。
- job 抢占使用单条原子条件更新，并设置 `locked_by` 与有限租约；失联 worker 的租约过期后可被重新领取。
- worker 完成任务时必须同时校验 job owner、租约和 Note `target_version`，迟到结果不能覆盖新状态。
- 对同一 Note 的有效 publish/delete job 建立数据库唯一约束；归档优先于尚未开始的发布任务。
- SQLite 仍然串行化写入。若实际负载出现持续锁竞争，再迁移 PostgreSQL；首版不为了理论吞吐提前增加运维复杂度。

## 10. 安全与本地运行

- 默认绑定 `127.0.0.1`，不默认暴露到局域网。
- Provider API Key 不写入 Note、artifact 原始响应或前端日志。
- 日志对密钥、请求头和敏感内容脱敏。
- 媒体路径由服务生成，拒绝路径穿越和任意本地文件读取。
- 限制媒体大小并校验实际文件类型。
- 即使首版不登录，状态变更 API 也应考虑 CSRF 防护。
- 未来非 localhost 访问应作为独立部署模式增加认证、HTTPS 和本地 Agent，而不是简单开放监听地址。

## 11. 可观测性与运维

首版至少提供：

- AnkiConnect 健康状态与版本。
- Provider 配置检查，但不暴露密钥。
- Dictionary Cache 命中率、来源数据集和最近抓取时间。
- Azure Speech voice、locale、输出格式和连接状态。
- generation/publish job 的状态、耗时和最近错误。
- Note 当前版本与已发布版本。
- 失败任务手动重试入口。
- SQLite 和媒体目录的一体化备份说明。

结构化日志至少包含 `request_id`、`job_id`、`note_id` 和 `target_version`。

## 12. API 草案

```text
POST   /api/generations
GET    /api/generations/{id}
POST   /api/generations/{id}/retry

GET    /api/drafts/{id}
PATCH  /api/drafts/{id}
POST   /api/drafts/{id}/confirm

GET    /api/notes
GET    /api/notes/{id}
PATCH  /api/notes/{id}
POST   /api/notes/{id}/archive
DELETE /api/notes/{id}                 # only after archived; explicit hard delete
POST   /api/notes/{id}/publish
POST   /api/notes/{id}/inspect-anki

GET    /api/dictionary-cache
DELETE /api/dictionary-cache/{id}

GET    /api/jobs/{id}
POST   /api/jobs/{id}/retry

GET    /api/health
GET    /api/health/anki
```

修改正式 Note 的请求携带 `expected_version`。确认草稿的响应表示本地提交结果，并单独返回 publication/job 状态，不能把 Anki 暂时不可用误报为 Note 保存失败。

## 13. 实施阶段

### 阶段一：领域基础

- 建立 Python 项目、配置、SQLite 和迁移。
- 实现 Note、版本控制、唯一性和草稿确认。
- 实现本地媒体存储及哈希去重。
- 建立基础管理界面和测试结构。

### 阶段二：生成流水线

- 定义 AI、词典和 TTS Provider 接口。
- 实现授权词典缓存、GPT-5.6 Luna Structured Outputs 和 Azure Speech adapter。
- 实现持久化 job worker。
- 保存 artifacts，完成生成、预览、编辑和确认流程。

### 阶段三：Anki 发布

- 实现专用 Note Type 和模板版本。
- 实现媒体上传、SourceId 查找、幂等创建和更新。
- 实现发布状态、重试和版本追赶。
- 实现 archive_pending、幂等 Anki 删除和删除 tombstone。

### 阶段四：校验与完善

- 实现 Anki 偏移和缺失检测。
- 加入失败恢复、安全限制、备份说明和端到端测试。
- 根据实际使用调整模板与生成策略。

## 14. 首版验收条件

- Anki 未启动时，用户仍能生成、编辑并确认 Note。
- Anki 恢复后，待发布 Note 可成功发布，重复重试不会产生副本。
- 同一 `(language, word_normalized, word_idx)` 不能创建两个有效 Note。
- 同一 word 使用不同 `word_idx` 可以创建多个 Note。
- 并发更新时，旧版本提交被拒绝或明确提示。
- v3 发布过程中产生 v4 时，最终能够正确追赶到 v4。
- 手动修改或删除 Anki Note 后，服务能检测 `drifted` 或 `missing`，且不反向覆盖本地数据。
- 相同媒体内容只保存一个服务副本，Anki 使用稳定且无冲突的文件名。
- AI、TTS 或 AnkiConnect 失败均可观察和重试，不损坏正式 Note。
- 词典缓存命中时不发生外部查询；显式失效后可以重新获取并保存新响应。
- GPT 输出不包含最终 HTML，且无法通过 schema 或内容校验的结果不能形成可确认 Draft。
- Azure Speech 相同输入与配置复用相同媒体；voice、SSML 或输出格式变化会产生新缓存键。
- 归档已发布 Note 后，只有确认 Anki Note 不存在才进入 `archived`；Anki 离线时删除意图跨进程重启保留。
- 多个 worker 并发运行时，同一 job 不会被同时有效执行，过期租约可安全恢复。
- 硬删除业务记录后不存在孤儿 artifact；共享媒体只有在最后一个引用删除后才可回收。

## 15. 已确定的架构决策

1. 文本生成默认使用 OpenAI `gpt-5.6-luna`，通过 Structured Outputs 返回领域数据；复杂词条未来可配置升级模型，但不改变领域接口。
2. 词典 Provider 必须允许 API 原始数据和派生数据长期保存；缓存默认无限期，支持主动失效和删除。具体供应商是部署配置，不构成领域耦合。
3. TTS 默认使用 Azure AI Speech，输出可配置 MP3，并用 SSML 固定 voice、locale、语速和特殊发音。
4. 内容面向高级英语学习者，英文释义和自然例句优先，中文释义保持简短；默认偏好职场和 IT 语境。
5. 首版 Note Type 是服务专用的单卡 Basic 模式，使用字段化数据、HTML 模板和共享 CSS。
6. `word_idx` 从 `0` 开始，创建后稳定。
7. 归档必须删除 Anki 副本；跨 SQLite/Anki 使用持久删除意图、幂等删除和确认读取实现可恢复收敛。
8. 允许多进程启动；SQLite job 租约、乐观版本和数据库唯一约束负责协调。
9. Artifacts 默认无限期保存；所属业务记录硬删除时级联删除独占 artifacts，禁止孤儿记录。

## 16. 外部配置与未来演进

下列事项保留为配置或后续演进，不阻碍首版实现：

- 获得合适授权后的具体词典供应商和数据集。
- 默认 Azure voice、英式/美式 locale 及语速，可由用户设置覆盖。
- 对歧义、多义或校验失败词条是否路由到更高能力模型。
- 是否增加 Sketch Engine 等语料 Provider，为搭配和 IT/职场语域提供额外证据。
- 运行负载超过 SQLite 写并发能力后迁移 PostgreSQL。

## 17. 官方技术参考

- [OpenAI GPT-5.6 Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna)：Responses API、Structured Outputs 和模型能力。
- [Azure AI Speech Text to Speech](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/text-to-speech)：神经语音、音频输出和服务能力。
- [Azure Speech SSML](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/speech-synthesis-markup)：voice、locale、语速和发音控制。
- [Anki Card Templates](https://docs.ankiweb.net/templates/intro.html)：字段替换、HTML 模板和共享 CSS 的官方惯例。
