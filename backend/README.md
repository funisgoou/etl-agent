# ETL-Agent 后端

生产级 ETL-Agent 数据集成平台控制面：**Agent 智能生成 + 不可绕过的 Harness 安全内核 + SeaTunnel/Doris 数据面**。

## 架构一览

```
Vue 前端 ─► FastAPI 控制面 ─► LangGraph 编排（意图→澄清→探查→生成→门禁→修复，PostgresSaver checkpoint）
                │
                ▼
        Harness 安全内核（不可绕过）
        PDP 风险评级 │ Ed25519 Capability（nonce 存证+单次消费）│ Tool Broker │ Outbox │ 账本哈希链
                │
                ▼
        Celery Worker ─► SeaTunnel(哑管道) ─► Doris {t}__raw ─受管SQL─► __shadow/__err ─原子Swap─► 正式表
```

- 数据流（D5 哑管道+受管 SQL 分流）：源 → SeaTunnel → `{t}__raw` → Worker 编译产物 SQL 分流 → `__shadow`(合格)/`__err`(违规+错误码) → 原子 Swap 发布。
- 三阶段协议（D10/D3）：`prepare`(指纹冻结+PDP) → `approve`(四眼/职责槽互斥/禁止自批) → `commit`(指纹重算+Capability+单事务 ExecutionRun+Outbox)。
- C1 行数硬判据：`input == 源端行数` 且 `output + error == input`，任一不满足判失败。

## 目录结构

```
backend/app/
  core/        基础设施：config/db/errors/masking/security(pbkdf2+会话)/
               secret_provider(AES-GCM 信封加密，按 Vault KV v2 接口抽象)/redis/minio/llm_client
  db_model.py  24 张表 ORM（23 业务 + keyring）
  harness/     安全内核：intents/pdp/capability/broker/outbox/ledger
  compiler/    QualityContract → Doris 分流 SQL（纯函数，标识符白名单）
  agent/       LangGraph：state/nodes/graph（interrupt 澄清 + checkpoint 恢复）
  domain/      业务域：auth/projects/connections/file_assets/pipelines/
               studio(生成入口)/preparations(三阶段)/executions(SSE)/benchmark/audit/evolution
  worker/      celery_app/tasks(三阶段执行)/seatunnel_client/doris_client/relay/supervision/beat_tasks
alembic/       迁移（含只追加/冻结触发器）
```

## 快速启动

### 1. 环境

```bash
# Python 3.12 锁定（uv 管理）
cd backend && uv sync

# 本地 .env（参考 .env.example；绝不入库）
#   SECRET_MASTER_KEY: python -c "import base64,os;print(base64.b64encode(os.urandom(32)).decode())"
#   LLM_BASE_URL/LLM_API_KEY/LLM_MODEL_ID: OpenAI 兼容协议（D6 全配置化）
```

### 2. 数据面 + 控制面存储

```bash
# BE 起不来先修 sysctl（Docker Desktop 重启后可能失效）
docker run --rm --privileged alpine sysctl -w vm.max_map_count=2000000

docker compose up -d postgresql redis            # 控制面存储
docker compose --profile datalane up -d          # mysql/doris×2/seatunnel/minio/doris-init
```

### 3. 迁移 + 种子 + 服务

```bash
cd backend
uv run alembic upgrade head
uv run python -m app.core.seed        # 演示账号/项目/连接/Benchmark 用例

# 宿主直跑（Windows 注意 worker 用 -P solo；后台常驻用 PowerShell Start-Process）
uv run uvicorn app.main:app --port 8000
uv run python -m app.worker.relay                                   # Outbox 中继
uv run celery -A app.worker.celery_app.celery_app worker -P solo    # 执行 Worker
uv run celery -A app.worker.celery_app.celery_app beat              # 周期任务（准备单过期）

# 或全容器化（compose 已串好 alembic/seed/relay/uvicorn）
docker compose --profile control --profile datalane up -d --build
```

### 4. 演示账号（seed）

| 用户 | 密码 | 角色 | 职责槽 |
|---|---|---|---|
| maker | Demo#2026 | admin/engineer | maker |
| checker1 | Demo#2026 | approver_data | checker1 |
| checker2 | Demo#2026 | approver_security | checker2 |
| operator | Demo#2026 | operator | operator |
| auditor | Demo#2026 | auditor | — |

## 端到端演示流（MySQL→Doris）

1. `POST /api/v1/auth/login`（maker）→ 项目 `demo` 已预置 biz-mysql / doris-ods 连接。
2. `POST /api/v1/pipelines` → `POST /api/v1/versions/{id}/generation`（NL 需求："把 biz_demo.orders 同步到 Doris 的 dwd_orders，amount 必须为正数，order_no 不能为空"）。
3. 轮询 `GET /api/v1/agent-runs/{run_id}`；`waiting_input` 时 `POST .../answers` 补参恢复（checkpoint）。
4. `GET /api/v1/versions/{id}/design` 审查 → `POST .../freeze`（门禁+SHA256）。
5. （可选）`POST .../dry-run`：tmp_dry_run 库采样跑 COPY+SPLIT，免四眼、进账本。
6. `POST .../prepare`（P1）→ checker1/checker2 各自 `POST /api/v1/approval-requests/{id}/decisions` → operator `POST /api/v1/preparations/{id}/commit`。
7. `GET /api/v1/execution-runs/{id}`（或 `/stream` SSE）观察 COPYING→SPLITTING→SWAPPING。
8. 种子基准：orders 20 行 → 正式表 17 + __err 3（E_NOT_POSITIVE×2、E_NOT_NULL×1）。
9. 篡改演示：改库 audit_events 后 `GET /api/v1/audit/verify` 报断点（触发器本身会拦 UPDATE，需超级用户绕过触发器后演示断链检测）。

## 实测记录（2026-08-18）

- 四眼协议：自批/槽资格/槽互斥/重复 commit 全部拦截 ✓
- Capability：重放（E_TOKEN_REPLAYED）/跨工具/指纹绑定（E_TOKEN_SCOPE）✓
- 账本：哈希链 verify 通过；触发器拦截 UPDATE ✓
- Dry-Run：20→17/3，C1 passed，tmp_dry_run ✓
- 正式执行：四眼→commit→SeaTunnel→分流→Swap 发布 17 行 ✓；回滚（17→0）✓

## 已知边界（ponytail 标注）

- `app/worker/tasks.py` 内 cols 全 STRING（id 除外 BIGINT）：哑管道保真策略，精确类型映射待 profile 类型表接入。
- CSV→Doris 链路：作业体构建已就绪（S3 source），端到端未实测（需 SeaTunnel S3 插件核验）。
- benchmark dry_run_pass_rate 仅统计 `dry:` 前缀用例且有真实 dry-run 记录时计入。
- 凭据密文仓 `.local_vault/` 为本地实现（已 gitignore）；换真 Vault 仅改 `secret_provider.LocalVault`。
