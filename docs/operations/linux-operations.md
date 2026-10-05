# Linux 安装、升级和锁定恢复

E12 实现范围：Linux amd64 版本镜像、离线归档、依赖与摘要清单、独立运维 O01、维护窗口加密备份、新实例锁定恢复和显式重新授权。下列命令是交付工具，实际部署及恢复结果以 Q5 记录为准。本任务没有新增或运行自动化测试。

## 分发与安装

受支持目标是 Linux amd64。主机预装 Docker Engine 28+、Compose 2.24+、Python 3.11+、GnuPG 2.2+；镜像内为项目锁定的 Python 3.13 和前端产物。OS 工具须在离线前安装。Mac 为开发机器，不是首版服务器安装目标。

`Linux amd64 release` 工作流仅手动触发，输入 `v0.1.0` 或 `v0.1.0-rc.2` 形式的版本，不做测试。它发布 `ghcr.io/zssggle-rgb/openform:<版本>`，同时保存含应用/数据库镜像的离线归档和 SHA-256。工作流存在不代表已经发布：本轮实际生成的是主机上的 `v0.1.0-rc.2` 离线包，未执行 GHCR 发布。依赖锁为 `uv.lock`、`apps/web/package-lock.json`，镜像摘要与 OS 前置工具见 `release.json`。人工签名/供应链认证不在本轮交付范围；下载渠道与旁路摘要应由运维可信保管。实际摘要及演练范围见 [Q5](../reviews/qa-q5-2026-10-06.md)，有安装问题的 rc.1 包不作为交付版本。

构建主机也可以将已带当前提交修订标签的镜像打包（不重新构建镜像）：

```sh
sudo python3 deploy/release.py --image openform:v0.1.0-rc.2 --version v0.1.0-rc.2 --output /srv/openform/packages/openform-v0.1.0-rc.2-linux-amd64.tar
```

安装端先核对发布归档的外部摘要，再解包核对内部清单，加载已有镜像，不联网拉取依赖。将解包目录作为独立安装目录：

```sh
sha256sum -c openform-v0.1.0-rc.2-linux-amd64.tar.sha256
tar -xf openform-v0.1.0-rc.2-linux-amd64.tar
cd openform
python3 deploy/release.py --verify --image unused --version unused --output .
sudo docker load --input images.tar
sudo python3 deploy/admin.py --project openform-campus init --image openform:v0.1.0-rc.2 --origin https://classroom.example.edu --runtime-origin https://activity.example.edu
sudo python3 deploy/admin.py --project openform-campus install
```

`init` 拒绝已有凭据、`.env`、同名容器或卷。初始化四个独立数据库角色密码及独立运维凭据。主机凭据目录为 root/0700；数据库凭据是该私有目录内的 0444 文件，供 PostgreSQL 和业务不同 UID 在各自的选择性只读 secret 挂载中读取，普通主机用户无法遍历该目录。运维与模型凭据为 UID 10001/0600。业务端口仅绑定 loopback。初始模型密钥为空；按[模型配置说明](authoring.md)单独写入，未配置模型不阻断课堂收集。API 不挂载 Docker socket。

默认网络下，前置 HTTPS 网关将两个独立主机名分别代理到 `127.0.0.1:18800` 与 `127.0.0.1:18801`，可以参考 [QA Caddy 配置](../../deploy/test/openform-test.caddy)，正式安装须换成自己的主机名与证书。**每台学生设备都要解析两个域并信任证书**；校内证书或内网 DNS 由学校部署方配置。不得关闭 TLS 校验作为正式步骤。`--development` 仅用于本机 loopback HTTP 的隔离演练，不代表校园离线部署验收。

开通学校继续使用[独立运维学校激活命令](identity.md)。O01 在 `/#O01`，运维凭据为 `.local/secrets/operator-key.txt`。与教师会话使用不同 cookie，仅展示实例、备份与任务状态，没有学生原始内容；学校管理员不能通过业务账号授权 O01。轮换独立凭据文件会立即使已有运维会话无效。

受控命令中的 Compose 启动禁用自动 pull/build，缺少镜像会停止。校内隔离安装可在 `init` 增加 `--offline`，使用内部容器网络，模型公网调用不可用。Docker 内部网络不发布上述主机端口：主机上的网关须改为代理 API/运行服务的实际容器地址和 8000/8001 端口，或由部署方接入该内部网络；不能直接沿用默认 loopback 上游。可以用 `sudo docker inspect openform-campus-api-1 --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'` 及对应 runtime 容器查询地址，重建容器后重新核对并更新上游。本轮以 SSH 转发直接连接内部地址验证安装，没有验收校园离线 HTTPS 网关、主机断公网或全部学生设备。

## 备份与实例外保管

`admin.py` 必须由独立部署负责人以 sudo 执行；不属于校园管理员权限。维护锁拒绝新业务请求/新任务，等待已有任务持久化落定，随后停止 API/运行服务/worker/清理服务，确保数据库与文件是同一静止时间点。维护期间业务入口不可用，提前通知教师安排课间窗口；网关可以配置 502/503 的维护提示页。最长等待 360 秒，超时保留维护锁，核对未知调用，不能偷偷恢复写入。

先在独立密钥存储位置创建随机备份口令，不能与备份、镜像、Git 或模型密钥放在一起：

```sh
sudo install -d -m 700 /root/openform-backup-keys
sudo python3 -c "import os,secrets; p='/root/openform-backup-keys/key.txt'; f=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600); os.write(f,secrets.token_urlsafe(48).encode()); os.close(f)"
sudo python3 deploy/admin.py --project openform-campus backup --file /srv/openform/backups/20261006.gpg --key-file /root/openform-backup-keys/key.txt
```

备份包含 PostgreSQL 自定义 dump、文件卷副本、记录数量、图片引用摘要、schema、应用镜像 ID 与快照时间；不包含部署数据库角色密码、独立运维凭据或模型 key。GnuPG AES-256 带完整性保护加密，生成后实际解密核对一次文件清单与摘要；无历史覆盖。成功后恢复写入，失败保留维护状态和上次备份。

加密文件的 `.gpg.json` 回执含编号、时间与密文摘要，不含密钥。复制加密文件及回执到实例外，核对收件位置 SHA-256，之后用核对后的回执记录异机副本已确认：

```sh
sudo python3 deploy/admin.py --project openform-campus ack-offsite --receipt /secure/verified/20261006.gpg.json
```

`ack-offsite` 是运维对已完成外部拷贝的确认，程序不能替人证明远端保管；未确认就明确展示“尚未确认”。本机加密备份不等于异机灾难恢复保证。备份周期和旧备份保留由负责人按磁盘容量明确安排，本工具不自行清除历史文件。

## 只能恢复到新实例

使用备份时的**同一镜像 ID**和版本归档，将目录放在全新路径，使用新实例名及未占用端口。不能使用原实例的数据库卷、目录、运维凭据或模型 key；程序拒绝已有容器和卷。先 `init`（生成新凭据，模型为空），再恢复，不能先 `install` 创建业务表：

```sh
sudo python3 deploy/admin.py --project openform-recovery init --image openform:v0.1.0-rc.2 --origin https://recovery.example.edu --runtime-origin https://recovery-activity.example.edu --api-port 18900 --runtime-port 18901
sudo python3 deploy/admin.py --project openform-recovery restore --file /secure/verified/20261006.gpg --key-file /root/openform-backup-keys/key.txt
sudo python3 deploy/admin.py --project openform-recovery status
```

先核对密文及解密文件的摘要、图片引用、镜像和架构，再事务恢复数据库与文件，核对 schema 和资料数量。随后更新实例 UUID/授权代次，撤销旧 staff/student/guest/runtime/operator 会话、学生个人码、学校邀请、成员与协作授权、任教分配；教师账号也暂停，开放中的课堂变暂停，进入码全部更换。保留实际提交、活动版本、图片、档案和原归属记录。旧导出/待确认导入失效，已确认的档案保留。未发出的模型任务取消并释放额度，可能已发出的结果未知任务继续保留预留，不自动重试。

仅启动 API/运行服务以展示恢复锁定和 O01，业务 readiness 为 503；worker/清理服务等到开放时启动。恢复点之后的数据明确不在此实例，需要与原实例核对，不能称为零数据丢失。任何步骤失败目标继续关闭，原实例不受影响，不自动删除失败目标。

以新运维凭据登录 O01 核对恢复点和资料数量。以权限 0600 文件明确指定重新授权的旧账号、恢复点内的空间 UUID、职责和**新密码**：

```json
{"workspace_id":"恢复点内的 UUID","login":"school-admin","password":"单独生成的新密码","teacher":false,"admin":true}
```

```sh
sudo python3 deploy/admin.py --project openform-recovery authorize --file /secure/recovery-admin.json
sudo python3 deploy/admin.py --project openform-recovery recovery-open
```

每个启用校园至少重新授权一位管理员，否则拒绝开放；个人空间和教师需要逐个明确授权。开放后学校管理员再核对成员、任教分配和重新签发学生码，教师核对暂停的课堂后决定是否接收。模型 key 必须单独重新配置。原密码不作为恢复后重新授权凭据。

## 升级与故障处理

提前获得新的版本镜像及安装目录，保留原镜像和目录。升级命令自动产生并核对升级前加密备份，再在维护态单次运行 migration、部署新镜像、核验受限业务角色/schema/readiness。不会自动数据库降级：

```sh
sudo python3 deploy/admin.py --project openform-campus upgrade --image openform:v0.1.1 --backup-file /srv/openform/backups/before-v0.1.1.gpg --key-file /root/openform-backup-keys/key.txt
```

成功才将新镜像写入 `.env`。迁移或部署失败保留维护态，不能只换回旧镜像假定兼容。按数据库 schema 判断是否可使用兼容应用修复向前迁移；不可兼容时，以升级前的同一版本镜像在新实例执行上述恢复。核对并确认原实例版本一致后才可 `resume`；恢复实例不能借 `resume` 绕过 `recovery-open`。

故障核对命令只读取部署状态；容器日志可能含受限运维数据，不公开粘贴完整日志：

```sh
sudo python3 deploy/admin.py --project openform-campus status
sudo docker compose -p openform-campus -f deploy/compose.yaml --env-file .env ps
curl --fail --show-error https://classroom.example.edu/api/health/ready
```

工具不自动停止其他 Compose 项目、不删除数据卷、不删除上一备份、不运行压力测试。备份恢复演练、校园网络、真实设备及现场课堂的事实需要各自记录，不能用发行文件替代。
