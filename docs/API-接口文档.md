# ETL-Agent 数据集成平台 接口文档（API）

| 项目 | 内容 |
| --- | --- |
| 文档版本 | v1.0 |
| 状态 | 基线（待评审） |
| 依据文档 | 《需求基线v2.md》、《docs/PRD.md》（第 10 章）、《docs/SPEC-模块规格文档.md》 |
| 冲突仲裁 | 与上游文档冲突时，以《需求基线v2.md》为准 |
| 目标读者 | 前后端开发、测试 |

---

## 1. 通用约定

### 1.1 基础

- Base URL：`/api/v1`（健康检查除外）；Content-Type：`application/json`（文件上传为 `multipart/form-data`）。
- 认证：除注册/登录/健康检查外，所有接口要求请求头 `Authorization: Bearer <session_token>`。
- 项目边界：凡涉及项目资源的接口，服务端强制校验调用者在该项目内的角色，越权返回 `E_FORBIDDEN_PROJECT`。

### 1.2 响应信封与错误码

成功：直接返回资源 JSON（HTTP 200/201）。

失败：统一错误结构（HTTP 4xx/5xx）：

```json
{
  "code": "E_FORBIDDEN_DUTY",
  "message": "同一 Preparation 单内同一用户只能占用一个职责槽",
  "details": { "preparation_id": 42, "conflict_slot": "checker1" },
  "trace_id": "01J..."
}
```

错误码总表见 SPEC 第 9 章。本文各接口仅列特有错误码。

### 1.3 分页

列表接口统一查询参数 `page`（默认 1）、`page_size`（默认 20，最大 100），响应：

```json
{ "items": [], "total": 137, "page": 1, "page_size": 20 }
```

### 1.4 敏感字段掩码

连接配置、凭据、样本数据中的敏感值在响应中一律掩码（如 `pa***rd`、`zh***@example.com`）；服务端永不返回明文密钥。

### 1.5 审计

审批/执行类写操作（Prepare、决策、Commit、Dry-Run、取消、回滚）全部写证据账本，响应中携带 `audit_event_id` 便于追溯。

---

## 2. 健康检查

### GET /health

无认证。检查系统组件与依赖就绪状态。

```json
{
  "status": "ok",
  "components": {
    "postgres": "ok", "redis": "ok", "doris": "ok",
    "seatunnel": "ok", "minio": "ok", "vault": "ok", "mysql": "ok"
  }
}
```

其中 `mysql` 为演示业务库（本地开发链路源端），非平台依赖组件。

任一依赖异常时 `status="degraded"`，HTTP 503。

---

## 3. 认证

### POST /api/v1/auth/register

注册。无认证。

请求：

```json
{ "username": "zhangsan", "password": "S3cure!pwd", "display_name": "张三", "email": "zs@example.com" }
```

响应 201：`{ "id": 1, "username": "zhangsan", "display_name": "张三", "email": "zs@example.com", "status": "active" }`

错误：`E_VALID_*`（用户名已存在/弱密码）。

### POST /api/v1/auth/login

登录，返回会话令牌。

请求：`{ "username": "zhangsan", "password": "S3cure!pwd" }`

响应：`{ "token": "eyJ...", "expires_at": "2026-08-18T12:00:00Z", "user": { "id": 1, "display_name": "张三" } }`

错误：`E_AUTH_INVALID_CREDENTIALS`（不区分用户不存在/密码错误）。

> 会话语义（R13）：令牌本体为不透明随机串；登录时服务端在 `sessions` 表写入会话记录（仅存 `token_digest` 摘要、`expires_at`、`revoked_at`），鉴权时校验会话未吊销且未过期。库内不存令牌明文。

### POST /api/v1/auth/logout

注销当前会话：服务端吊销该会话（置 `sessions.revoked_at`），此后该令牌鉴权失败。响应 204。

---

## 4. 项目与成员

### POST /api/v1/projects

创建项目（创建者自动成为管理员成员）。

请求：`{ "name": "数据中台", "code": "dmp", "description": "..." }`

响应 201：项目对象。

### GET /api/v1/projects

当前用户参与的项目列表（分页）。

### GET /api/v1/projects/{project_id}

项目详情，含当前用户角色。

### POST /api/v1/projects/{project_id}/members

添加成员。权限：项目管理员。

请求：`{ "user_id": 2, "role": "engineer" }`（role ∈ `engineer|approver_data|approver_security|operator|auditor`）

### POST /api/v1/projects/{project_id}/role-grants

授予职责槽资格（D3：仅资格，不做互斥判定）。权限：项目管理员。

请求：`{ "user_id": 2, "role_slot": "maker" }`（role_slot ∈ `maker|checker1|checker2|operator`）

### GET /api/v1/projects/{project_id}/role-grants

资格列表。

---

## 5. 数据连接与资产

### GET /api/v1/projects/{project_id}/connections

项目连接列表（分页，可按 `conn_type` 过滤）。`config_json` 中敏感字段已掩码。

### POST /api/v1/projects/{project_id}/connections

创建连接。权限：`engineer`。

```json
{
  "name": "biz-mysql",
  "conn_type": "mysql",
  "config_json": { "host": "mysql", "port": 3306, "database": "biz_demo", "username": "etl", "password": "明文仅本次传输" }
}
```

- `conn_type` ∈ `mysql|postgresql|oracle|doris|clickhouse|s3|rest_api`（注册表校验，否则 `E_VALID_CONN_TYPE`）。
- CSV 等文件资产统一走 file_assets 通道（D8/C3），不再作为连接类型：EtlPlan 引用 CSV 源时使用 `file_asset_id`，CSV 探查/字段推断结果落 `file_assets.schema_json`，不经 metadata_profiles。
- 服务端将敏感字段写入 Vault 后以 `vault://` 引用入库。

响应 201：连接对象（敏感字段掩码）。

### PUT /api/v1/connections/{id}

编辑连接（同上结构，部分更新）。

### POST /api/v1/connections/{id}/tests

连通性测试。

响应：`{ "ok": true, "latency_ms": 12, "server_version": "8.0.36" }`；失败 `ok=false` + `message`。

### POST /api/v1/connections/{id}/profiles

发起只读元数据探查与脱敏样本采集。

请求：`{ "object_name": "orders", "sample_size": 100 }`

响应 201：

```json
{
  "id": 7, "connection_id": 3, "object_name": "orders",
  "schema_json": { "columns": [ { "name": "amount", "type": "DECIMAL(12,2)", "nullable": true } ], "primary_key": ["id"] },
  "stats_json": { "approx_rows": 1000 },
  "masked_sample_json": [ { "id": 1, "email": "zh***@example.com" } ],
  "created_at": "..."
}
```

错误：`E_VALID_*`（对象不存在）；探查为只读，禁止写操作。

### GET /api/v1/connections/{id}/profiles

该连接的探查结果列表（分页）。

### POST /api/v1/file-assets

上传并解析 CSV 文件资产（存 MinIO，C3）。`multipart/form-data`：`project_id`、`file`。

响应 201：

```json
{
  "id": 5, "file_name": "products.csv",
  "file_path": "s3a://etl-assets/projects/1/file_assets/5/products.csv",
  "file_size": 20480, "file_format": "csv",
  "schema_json": { "columns": [ { "name": "sku", "inferred_type": "string" } ] }
}
```

错误：`E_VALID_FILE_FORMAT`（v1 仅 CSV，D8）。

---

## 6. Pipeline 与生成

### POST /api/v1/pipelines

创建 Pipeline 定义。权限：`engineer`。

请求：`{ "project_id": 1, "name": "订单入仓", "code": "orders_dwd", "description": "..." }`

响应 201：Pipeline 对象（初始 `status=draft`，自动创建 `version_number=1` 草稿版本）。

### POST /api/v1/pipelines/{pipeline_id}/versions

创建新草稿版本（版本迭代）。权限：`engineer`。`version_number` = 当前最大 +1；可选请求体 `{"base_version_id": 42}` 复制既有版本内容作为起点（缺省则创建空白草稿）。

请求（可选）：

```json
{ "base_version_id": 42 }
```

响应 201：

```json
{ "version_id": 43, "pipeline_id": 7, "version_number": 2, "status": "draft", "base_version_id": 42 }
```

### GET /api/v1/projects/{project_id}/pipelines

Pipeline 列表（分页）。

### POST /api/v1/versions/{version_id}/generation

触发 LangGraph 候选生成。权限：`engineer`（maker 资格）。

请求：

```json
{ "prompt": "把 biz_demo.orders 同步到 Doris，amount 必须为正数，order_no 不能为空" }
```

响应 202：

```json
{ "run_id": 11, "thread_id": "v42-01J...", "status": "running" }
```

状态机推进通过轮询 `GET /api/v1/agent-runs/{run_id}` 观察（v1 不提供 agent-run 的 SSE 接口，SSE 仅用于 execution-run，D7）。

### GET /api/v1/agent-runs/{run_id}

查询 agent-run 生成状态机当前状态（轮询）。

```json
{ "run_id": 11, "status": "waiting_input", "step_count": 2,
  "pending_question": { "field": "target_table", "message": "目标表名是什么？" } }
```

### POST /api/v1/agent-runs/{run_id}/answers

提交澄清回答，从 checkpoint 恢复状态机（D10）。

请求：`{ "answer": { "target_table": "dwd_orders" } }`

响应 202：`{ "run_id": 11, "status": "running" }`

### GET /api/v1/versions/{version_id}/design

查询生成结果（方案审查视图数据源）。

```json
{
  "version_id": 42, "status": "generated",
  "etl_plan": { "source": "...", "target": "...", "mappings": [], "quality_contract": { "rules": [] } },
  "hocon": "env { ... }",
  "dag": { "nodes": [], "edges": [] },
  "gate_report": { "passed": true, "findings": [] },
  "artifact_digest": "a3f1...（冻结后存在）",
  "is_immutable": false
}
```

### POST /api/v1/versions/{version_id}/freeze

门禁全部通过后冻结不可变版本（SHA256 摘要，`is_immutable=true`）。

响应：`{ "version_id": 42, "artifact_digest": "a3f1...", "is_immutable": true }`

错误：`E_GATE_*`（存在 blocking 未通过项）。

### POST /api/v1/versions/{version_id}/dry-run

触发受管试运行（独立 ToolIntent，PDP 评级，免四眼审批，全程进账本）。

响应 202：`{ "execution_run_id": 88, "audit_event_id": 1024, "status": "pending" }`

Dry-Run 结果复用 7.1 查询；目标为 `tmp_dry_run` 库，跳过 Swap，行数硬校验（C1）。Dry-Run 不创建准备单（免四眼），其 ExecutionRun 的 `run_kind='dry_run'`、`preparation_id` 为空，但仍签发 Capability、进证据账本（R1）。

---

## 7. 三阶段协议与执行

### 7.1 Prepare

**POST /api/v1/versions/{version_id}/prepare** — 生成准备单。权限：maker。前置：版本已冻结。

响应 201：

```json
{
  "id": 42, "version_id": 42, "status": "pending",
  "maker_id": 2, "expires_at": "2026-08-21T06:30:00Z",
  "input_fingerprint": "b7e2...",
  "resource_scope": { "source": ["mysql:biz_demo.orders"], "target": ["doris:dwd_orders"] },
  "impact_json": { "write_tables": ["dwd_orders"], "estimated_rows": 1000 },
  "data_classification": "internal",
  "budget_json": { "max_read_rows": 100000, "max_write_bytes": 1073741824, "max_duration_seconds": 1800 },
  "rollback_plan_json": { "steps": ["drop_shadow", "restore_state"] },
  "risk_level": "P1",
  "approval_requests": [
    { "id": 91, "required_role": "checker1", "status": "pending" },
    { "id": 92, "required_role": "checker2", "status": "pending" }
  ],
  "audit_event_id": 1025
}
```

### 7.2 Approve

**POST /api/v1/approval-requests/{approval_id}/decisions** — 具名审批决策。权限：对应职责槽资格。

请求：`{ "decision": "approve", "comment": "映射与脱敏核对无误" }`（decision ∈ `approve|reject`）

响应：`{ "id": 91, "status": "decided", "decision": "approve", "approver_id": 3, "decided_at": "...", "audit_event_id": 1026 }`

错误：

- `E_FORBIDDEN_DUTY` — 申请人自批 / 同一 Preparation 内职责槽混用（D3，附 `details.conflict_slot`）
- `E_PREP_*` — 准备单已终结

### 7.3 Commit

**POST /api/v1/preparations/{preparation_id}/commit** — 校验审批与指纹，签发单次 Capability 并原子提交执行。权限：operator 资格。

响应 201：

```json
{
  "execution_run_id": 101, "status": "pending",
  "capability_issued": true, "audit_event_id": 1027
}
```

错误：`E_PREP_NOT_APPROVED`（审批未齐）、`E_FINGERPRINT_MISMATCH`（制品被替换）、`E_PREP_EXPIRED`。

> Capability 明文令牌仅服务端持有并随 Outbox 命令投递 Worker，不在本接口返回。

### 7.4 执行查询

**GET /api/v1/execution-runs/{id}**

```json
{
  "id": 101, "version_id": 42, "preparation_id": 42,
  "run_kind": "execute",
  "status": "running", "sub_stage": "SPLITTING",
  "engine_job_id": "st-job-8f21",
  "input_records": 1000, "output_records": 930, "error_records": 70,
  "bytes_processed": 524288, "started_at": "...", "finished_at": null,
  "diagnosis": null,
  "quality_report": {
    "row_count_check": "pending",
    "error_code_distribution": { "E_NOT_POSITIVE": 50, "E_NOT_NULL": 20 },
    "contract_hits": { "not_null": 980, "positive": 950 }
  }
}
```

`status` ∈ `pending|running|succeeded|failed|cancelled|rolled_back`；`run_kind` ∈ `execute|dry_run`（Dry-Run 时 `preparation_id` 为空，R1）；`sub_stage` ∈ `COPYING|SPLITTING|SWAPPING`（仅 running 时存在）。`diagnosis` 正常为 null；失败/监督中断时由诊断服务写回，结构为 `{"root_cause": "...", "suggestions": [...]}`。

`row_count_check` 判据（C1，双等式口径，R3）：① `input_records == 源端行数`（Dry-Run 时为 min(源端行数, 采样上限 `dry_run_sample_limit`)）；② `output_records + error_records == input_records`（合格行进 shadow、违规行进 err，合计须等于读取行数）。任一不满足即判失败。

**GET /api/v1/projects/{project_id}/execution-runs** — 列表（分页，可按 `status` 过滤）。

### 7.5 SSE 实时推送

**GET /api/v1/execution-runs/{id}/stream**（D7）

`text/event-stream`，事件类型：

```
event: status
data: {"status":"running","sub_stage":"COPYING","input_records":500}

event: metrics
data: {"input_records":1000,"output_records":930,"error_records":70,"bytes_processed":524288,"throughput_rps":420}

event: supervision
data: {"decision":"warning","metric":"error_reject_rate","value":0.07,"threshold":0.1}

event: done
data: {"status":"succeeded","row_count_check":"passed"}
```

断线客户端以 `Last-Event-ID` 重连；终态后服务端关闭流。

### 7.6 运维操作

**POST /api/v1/execution-runs/{id}/cancel** — 取消运行中作业。权限：operator。响应 202：`{ "id": 101, "status": "cancelled", "audit_event_id": 1028 }`

**POST /api/v1/execution-runs/{id}/rollback** — 受管影子表回滚与清理（经 Harness 授权）。响应 202：`{ "id": 101, "status": "rolled_back", "audit_event_id": 1029 }`

**POST /api/v1/execution-runs/{id}/rerun** — 安全重跑（R6）。权限：operator。仅允许对终态 run（`succeeded|failed|cancelled|rolled_back`）发起；复用原 Preparation 冻结事实，服务端重算指纹比对（不一致须重新 Prepare）；签发新 Capability，单事务写新 ExecutionRun + Outbox；幂等由按 run 隔离保证。

响应 201：

```json
{ "execution_run_id": 110, "rerun_of": 101, "audit_event_id": 1030 }
```

错误：`E_RUN_INVALID_STATE`（原 run 非终态）、`E_FINGERPRINT_MISMATCH`（制品指纹不一致，须重新 Prepare）。

以上操作均注册 ToolIntent、PDP 评级、签发 Capability 后由 Tool Broker 放行，全程进账本。

---

## 8. Benchmark 与审计

### POST /api/v1/benchmarks/run

触发 Benchmark 评测。权限：`approver_security`。

请求：`{ "suite_version": "v1.0" }`

响应 202：`{ "benchmark_run_id": 9, "status": "running" }`

### GET /api/v1/benchmarks/runs/{id}

```json
{
  "id": 9, "suite_version": "v1.0", "status": "succeeded",
  "metrics_json": {
    "compile_pass_rate": 0.93, "field_f1": 0.91, "dry_run_pass_rate": 0.87,
    "block_rate": 1.0, "false_positive_rate": 0.05, "health_score": 91.4
  },
  "started_at": "...", "finished_at": "..."
}
```

健康度公式与准入（>90 分）见 PRD 第 11 章；C1 行数不一致的用例直接判失败。

### GET /api/v1/audit/events

审计事件列表（分页，按 `project_id` 必填 + `event_type`/`actor_id`/时间范围过滤）。权限：`auditor`。

### GET /api/v1/audit/verify

重算证据账本哈希链并报告断点（D9，篡改演示验收入口）。权限：`auditor`。

请求参数：`project_id`（必填）。

响应：

```json
{
  "project_id": 1, "ok": false, "checked_events": 1024,
  "broken_at_event_id": 777,
  "expected_hash": "c91a...", "actual_hash": "44d0..."
}
```

链完整时 `ok=true`，`broken_at_event_id` 为 null。

### 安全进化管理（R7）

以下接口权限均为 `approver_security`。

**GET /api/v1/evolution/candidates** — 候选对象列表（分页，可按 `project_id`、`status` 过滤）。

**POST /api/v1/evolution/candidates** — 提交安全进化候选（prompt/policy 变更提案）。

请求：`{ "project_id": 1, "kind": "prompt", "title": "生成提示词 v2", "content_json": { "template": "..." } }`（kind ∈ `prompt|policy`）

响应 201：候选对象，字段：`id, project_id, kind, title, content_json, status(proposed|approved|rejected), review_report_json, created_by, created_at, updated_at`（初始 `status=proposed`）。

**GET /api/v1/evolution/candidates/{id}** — 候选对象详情（含评审报告 `review_report_json`）。

**POST /api/v1/evolution/candidates/{id}/reviews** — 提交评审结论。

请求：`{ "decision": "approve", "review_report_json": { "benchmark_run_id": 9, "findings": [] } }`（decision ∈ `approve|reject`）

响应：候选对象（`status` 更新为 `approved|rejected`）。

**GET /api/v1/evolution/gray-flags** — 灰度开关列表（按 `project_id` 过滤）。

**PUT /api/v1/evolution/gray-flags** — 更新灰度开关。

请求：`{ "project_id": 1, "flag_key": "generator_prompt_v2", "enabled": true, "description": "..." }`

响应：灰度开关对象，字段：`project_id, flag_key, enabled, description, updated_by, updated_at`。

错误：`E_EVOLUTION_GATE` — `enabled=true` 的前置未满足：该项目最新成功 benchmark_run 的 `health_score` 须 > 90。

---

## 9. 接口索引

| 方法 | 路径 | 说明 | 角色 |
| --- | --- | --- | --- |
| GET | `/health` | 依赖就绪检查 | 公开 |
| POST | `/api/v1/auth/register` `/login` `/logout` | 认证 | 公开/登录态 |
| POST/GET | `/api/v1/projects` | 项目创建/列表 | 登录态 |
| GET | `/api/v1/projects/{id}` | 项目详情 | 成员 |
| POST/GET | `/api/v1/projects/{id}/members` `/role-grants` | 成员与资格 | 管理员 |
| GET | `/api/v1/projects/{id}/connections` | 连接列表 | 成员 |
| POST | `/api/v1/projects/{id}/connections` | 连接创建 | engineer |
| PUT | `/api/v1/connections/{id}` | 连接编辑 | engineer |
| POST | `/api/v1/connections/{id}/tests` | 连通性测试 | engineer |
| POST/GET | `/api/v1/connections/{id}/profiles` | 元数据探查/查询 | engineer/成员 |
| POST | `/api/v1/file-assets` | CSV 上传解析 | engineer |
| POST | `/api/v1/pipelines` | 创建 Pipeline | engineer |
| POST | `/api/v1/pipelines/{id}/versions` | 创建新草稿版本 | engineer |
| GET | `/api/v1/projects/{id}/pipelines` | Pipeline 列表 | 成员 |
| POST | `/api/v1/versions/{id}/generation` | 触发生成 | maker |
| GET | `/api/v1/agent-runs/{id}` | 生成状态查询（轮询） | maker |
| POST | `/api/v1/agent-runs/{id}/answers` | 澄清回答 | maker |
| GET | `/api/v1/versions/{id}/design` | 设计查询 | 成员 |
| POST | `/api/v1/versions/{id}/freeze` | 版本冻结 | maker |
| POST | `/api/v1/versions/{id}/dry-run` | 受管试运行 | maker |
| POST | `/api/v1/versions/{id}/prepare` | 生成准备单 | maker |
| POST | `/api/v1/approval-requests/{id}/decisions` | 审批决策 | checker1/2 |
| POST | `/api/v1/preparations/{id}/commit` | 提交执行 | operator |
| GET | `/api/v1/execution-runs/{id}` | 执行状态与质量报告 | 成员 |
| GET | `/api/v1/projects/{id}/execution-runs` | 执行列表 | 成员 |
| GET | `/api/v1/execution-runs/{id}/stream` | SSE 实时推送（D7） | 成员 |
| POST | `/api/v1/execution-runs/{id}/cancel` `/rollback` | 运维操作 | operator |
| POST | `/api/v1/execution-runs/{id}/rerun` | 安全重跑（终态 run） | operator |
| POST | `/api/v1/benchmarks/run` | 触发评测 | approver_security |
| GET | `/api/v1/benchmarks/runs/{id}` | 评测结果 | 成员 |
| GET | `/api/v1/audit/events` | 审计事件列表 | auditor |
| GET | `/api/v1/audit/verify` | 账本哈希链校验（D9） | auditor |
| GET | `/api/v1/evolution/candidates` | 进化候选列表 | approver_security |
| POST | `/api/v1/evolution/candidates` | 提交进化候选 | approver_security |
| GET | `/api/v1/evolution/candidates/{id}` | 进化候选详情 | approver_security |
| POST | `/api/v1/evolution/candidates/{id}/reviews` | 候选评审 | approver_security |
| GET/PUT | `/api/v1/evolution/gray-flags` | 灰度开关查询/更新 | approver_security |
