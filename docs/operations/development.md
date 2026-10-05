# 工程开发与有限验证

E02 提供依赖锁、API 健康检查、数据库角色与迁移、Web 构建、worker 环境检查入口、Linux 镜像和 CI。账号、活动、课堂和持久任务属于后续任务；`worker --check` 不是模型任务已可运行。

## 已确定的依赖

Python workspace 共用根目录 `uv.lock`，替代 E01 的独立 lockfile。基线为 Python 3.13、uv 0.9.5、Node 24。补丁版本由 lockfile 固定，不靠 README 手动重复维护。

API 使用 FastAPI、Pydantic 2、SQLAlchemy 2、psycopg 3、Alembic；Web 使用 React 19、TypeScript、Vite。Node / Python / PostgreSQL 基础镜像按实际拉取的 digest 固定。应用以 UID 10001 运行，API 和 worker 共用镜像；数据库只在专用测试覆盖文件中绑定回环端口。

容器首发目标为 Linux amd64，uv 工具 wheel 的 SHA-256 取自 PyPI 官方元数据。需要公共包镜像时可在构建中传 `--build-arg UV_TOOL_INDEX_URL=https://mirrors.cloud.tencent.com/pypi/simple`，仍以同一个官方 hash 验证 uv，不接受不同内容。

第三方包保留自身许可证和 wheel/npm 许可证信息，根目录 MIT 不覆盖它们。React、Vite、uv 等来源以各包元数据为准。应用目前不捆绑在线字体或模型账户。

## 本机启动

```sh
uv sync --frozen --all-packages
cd apps/web
npm ci
npm run dev
```

必须使用 Node 24，不能以本机其他主版本忽略 engines 提示。Vite 将 `/api` 代理到 `127.0.0.1:8000`。API 使用配置文件中的真实 PostgreSQL，启动命令：

```sh
uv run --env-file .env uvicorn openform.main:app_factory --factory --host 127.0.0.1 --port 8000
```

以 `.env.example` 为配置模板，不提交 `.env` 或凭据。业务角色使用 `openform_app`，迁移命令使用 `openform_migrate`，不使用 bootstrap 管理角色运行应用。

## 专用数据库与镜像检查

Docker Compose 在 `deploy/compose.yaml`；初次启动前，在 `.local/secrets/` 创建三份随机凭据。父目录 0700，凭据只读 0444，使两个非 root 容器用户可读其独立挂载，其他本机账号不能穿过私有父目录。Compose 文件型 secret 的 uid/mode 在普通 bind 挂载上不能代替实际文件权限。

```sh
python3 - <<'PY'
from pathlib import Path
import secrets
directory = Path('.local/secrets')
directory.mkdir(parents=True, exist_ok=True, mode=0o700)
directory.chmod(0o700)
for role in ('bootstrap', 'migrate', 'app'):
    path = directory / f'database-{role}.txt'
    if not path.exists():
        path.write_text(secrets.token_hex(32))
        path.chmod(0o444)
PY
docker compose -p openform-test -f deploy/compose.yaml -f deploy/compose.test.yaml up -d postgres --wait
```

迁移使用迁移角色 URL 和对应私有凭据文件：

```sh
OPENFORM_DATABASE_URL=postgresql+psycopg://openform_migrate@127.0.0.1:15432/openform OPENFORM_DATABASE_PASSWORD_FILE="$PWD/.local/secrets/database-migrate.txt" uv run alembic -c services/alembic.ini upgrade head
OPENFORM_TEST_DATABASE_URL=postgresql+psycopg://openform_app@127.0.0.1:15432/openform OPENFORM_DATABASE_PASSWORD_FILE="$PWD/.local/secrets/database-app.txt" uv run pytest services/tests/test_postgres.py
docker compose -p openform-test -f deploy/compose.yaml -f deploy/compose.test.yaml build migrate
docker compose -p openform-test -f deploy/compose.yaml -f deploy/compose.test.yaml up -d api
docker compose -p openform-test -f deploy/compose.yaml -f deploy/compose.test.yaml run --rm worker-check
```

运行前确认这是一套专用测试数据库。macOS 没有 Docker 时，可在已授权测试机启动专用实例，经 SSH 转发回环端口执行同一验证。健康检查要求 PostgreSQL 18、当前迁移、非超级用户/非 schema owner/无 BYPASSRLS 的业务角色，以及未维护/未恢复锁定的实例。数据库不可达返回 503 和安全错误；进程存活与可提供业务服务分开。

## 验证范围与 CI

E02 本地有限检查命令：

```sh
uv run ruff check services tools/ci_scope.py tools/tests
uv run mypy services/openform
uv run pytest services/tests/test_foundation.py tools/tests/test_ci_scope.py --cov=openform --cov-report=term-missing --cov-fail-under=80
cd apps/web
npm run build
npm test -- --coverage
```

前端 readiness 请求在成功、错误码、错误内容、断网和无法解析时分别验证；不会因任意 200 响应显示就绪。API 检查覆盖配置、角色、迁移、维护、错误内容及 shutdown；数据库检查真实跑在 PostgreSQL 18，不用 SQLite。

当前执行约定以用户最新要求为准：每个开发任务完成后做一次 `/review`，多个任务集成后做一次 `/qa`，不自行新增或运行自动化测试。上面的测试命令保留为 E02 历史工具说明，不代表当前每次提交要执行。

CI 仅在 PR 上按 base 选择格式/类型/编译工作；合并到 main 后不重复运行 CI，只核对合并提交。已有自动化测试和镜像检查保留为显式手动入口，默认不运行。新模块在范围映射中登记为空测试列表，不为登记制造测试文件。实际部署需要的镜像构建与数据库迁移仍是部署步骤。

第一次业务集成 QA 在身份/空间功能可操作后开展。本页命令与健康接口检查不等于完成浏览器、真实学生设备、校园网络或课堂验收。腾讯云公共域名仍用于后续实际应用 QA，不部署原型。
