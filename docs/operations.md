# 本地运维与恢复

## 备份边界

SQLite 数据库与媒体目录共同构成服务的事实来源，必须作为一个备份集合保存。Anki 只是发布副本，不能替代本地备份；`.env` 包含 Provider 密钥，应单独使用受限权限的密码管理或加密备份，不应放入普通归档。

默认布局为：

```text
data/app.db
data/media/
```

Docker Compose 也将仓库中的 `data/` 绑定到容器的 `/app/data`，而不是使用位于
Docker 内部、复制仓库时不会被带走的命名卷。因此迁移机器时必须复制完整的
`data/` 目录；仅 `git clone` 不会恢复业务数据，因为 `data/` 有意不纳入 Git。

Compose 默认以宿主机常见的 `1000:1000` 用户运行。若你的用户 ID 不同，在 `.env`
中设置 `ACC_UID` 和 `ACC_GID`（可分别用 `id -u`、`id -g` 查询），确保容器可写
`data/`。

容器将 uv 缓存放在可写的 `/tmp/uv-cache`，避免该 UID 在镜像内没有 home
目录时尝试写入 `/.cache`。

## 一致性备份

最简单可靠的方法是先停止所有 Web/worker 进程，确认没有进程写入 `data/`，再复制整个目录。SQLite 使用 WAL，因此不要只复制正在运行时的 `app.db` 而忽略 `app.db-wal`。离线复制整个 `data/` 可以同时覆盖数据库与媒体的一致时间点。

Docker Compose 部署可执行：

```bash
docker compose stop app
tar -C data -czf backups/anki-custom-card-data.tar.gz .
docker compose start app
```

应预先创建 `backups/`，限制备份文件的读取权限，并定期复制到另一块磁盘。

### 从旧版 Docker 命名卷迁移

旧版 Compose 使用名为 `app-data` 的命名卷。升级配置前，先把卷中数据复制到
仓库的 `data/`；否则新配置会看到一个空的绑定目录。保持应用停止，并将下面的
卷名替换为 `docker volume ls` 显示的实际名称：

```bash
docker compose stop app
mkdir -p data
docker run --rm \
  -e TARGET_UID="$(id -u)" \
  -e TARGET_GID="$(id -g)" \
  -v anki-custom-card_app-data:/source:ro \
  -v "$PWD/data:/target" \
  alpine sh -c 'cp -R /source/. /target/ && chown -R "$TARGET_UID:$TARGET_GID" /target'
docker compose up -d app
```

迁移完成并确认 Notes、媒体均正常后，旧命名卷可保留一段时间作为恢复副本。

## 恢复验证

恢复应先在隔离目录或临时数据目录中演练：

1. 保持服务停止，将完整归档解压到仓库的空 `data/` 目录。
2. 检查数据库和媒体文件的所有者、权限及路径。
3. 运行 `make migrate`，只执行向前兼容的缺失迁移。
4. 运行 `make check`，启动服务并检查 `/api/health` 与 `/api/health/anki`。
5. 抽查 Note、媒体和 publication 状态；Anki 副本缺失时通过发布任务重建，不从 Anki 反向覆盖 SQLite。

## 失败任务恢复

任务租约过期后可由其他 worker 重新领取。网络类错误采用退避重试；Note Type 不兼容、重复 `SourceId` 和数据校验错误会直接进入 `failed`，避免无限重试。修复根因后，可通过 `JobRepository.retry_failed()` 将明确选定的失败任务重新置为 `pending`。

归档删除失败时 Note 保持 `archive_pending`，在 Anki 确认副本不存在前不得硬删除本地 tombstone。

## Docker 与本机 Anki

Compose 的应用服务使用 host network，默认监听 `127.0.0.1`。这是因为 AnkiConnect 默认只监听本机 loopback；普通容器 bridge 网络无法安全访问宿主机的 `127.0.0.1:8765`。需要从可信局域网访问 Web 服务时，可在 `.env` 设置宿主机的明确私网地址，例如 `ACC_HOST=192.168.88.9`，然后重新创建容器。Web 监听地址和 `ACC_ANKI_CONNECT_URL` 相互独立，后者仍保持 loopback。

服务有意拒绝 `0.0.0.0`、公网地址和任意主机名，避免无意中扩大暴露面。局域网模式目前没有登录认证，只应在受信任且有防火墙保护的网络使用。部署后可在宿主机执行 `curl http://192.168.88.9:8000/api/health`，并从另一台局域网设备访问 `http://192.168.88.9:8000/app/`。如果宿主机本地访问成功而其他设备失败，应检查操作系统防火墙是否允许 TCP 8000 入站。
