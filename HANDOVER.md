## 2. 复用的环境资产

### 2.1 服务清单（docker-compose.yml，已实测可用）

| 服务 | 镜像 | 端口(宿主→容器) | 凭据/说明 |
|---|---|---|---|
| postgresql | postgres:16 | 5432 | harness/harness，库 `harnessflow`，卷 `pgdata` |
| redis | redis:7.4-alpine | 6379 | 无密码 |
| mysql-src（源库） | mysql:8.0 | **3307**→3306 | root/root123；只读账号 etl_reader/reader123（仅 shop.* SELECT）；库 `shop` |
| doris-fe | apache/doris:fe-2.1.11 | **19030**→9030，18030→8030 | root/**doris123**（注意 §3.3 密码是手工设置的）；库 `ods` |
| doris-be | apache/doris:be-2.1.11 | 8040 | 静态 IP 172.28.1.2，卷 `dorisbe`，entrypoint 已 sed 绕过宿主检查 |
| seatunnel | apache/seatunnel:2.3.12 | **5801**, 8080 | REST 提交模式，见 §4.1；挂载 JDBC 驱动 + 自定义 hazelcast.yaml |
| minio | minio/minio:latest | 9000（控制台 9001） | minioadmin/minioadmin123，卷 `miniodata` |

- **profile 划分**：`datalane`（mysql/doris×2/seatunnel/minio）与 `control`（api/worker/beat，构建自 `./backend`）。存储两件套（postgresql/redis）无 profile，始终启动。
- **网络**：`datalane` 固定子网 `172.28.0.0/16`，FE=172.28.1.1、BE=172.28.1.2 静态 IP（doris 镜像要求 FE_SERVERS/BE_ADDR 可解析，勿改成主机名）。
- **seatunnel 关键挂载**（`deploy/` 三件套，已在 git 内，勿 clean）：
  - `deploy/seatunnel-lib/` → `/opt/seatunnel/lib/extra`（mysql-connector-j-8.0.33.jar）
  - `deploy/seatunnel-config/hazelcast.yaml` → `/opt/seatunnel/config/hazelcast.yaml:ro`（**开启 hazelcast REST API**，默认关闭，没这个文件 REST 全 404）
  - `extra_hosts: host.docker.internal:host-gateway`（容器内反代回宿主，见 §4.3）
  - command 里的 `-DJocker` 拼写虽怪但实测可跑，勿改。

### 2.2 种子数据语义（质量分流的演示不变量）

`deploy/mysql-init/01_shop.sql`（mysql 无数据卷，**每次 down→up 自动重新播种**，对演示友好）：

- `shop.orders` 10 行，其中 **2 行是故意埋的脏数据**：id=2（amount=0.00, closed）、id=3（amount=-5.50, refunded）。
- `shop.customers` 3 行，含 phone/id_card/email 敏感字段（供 L3/L4 分级与脱敏演示）。
- **E2E 黄金不变量：10 行入 raw → 分流后 8 行合格入正式表、2 行带错误码入 `__err`。** 上一轮实测结果即 orders=8。重写后的质量规则可以自定，但必须能产生这个分流演示效果。

---

## 3. 环境现状与手工步骤（开工前必读）

### 3.1 容器已停止、卷还活着

7 个容器全部 Exited（正常停止），三个卷 `harnessflow_pgdata / dorisbe / miniodata` 仍在。直接 `docker compose up -d` 即可复活，**但卷里是旧代码跑出的数据**，处置见 3.2。

### 3.2 卷清理决策（重写开工第一步）

| 卷 | 内容 | 建议 |
|---|---|---|
| `pgdata` | 旧 23 张表 + 演示账号 + **加密存的 LLM Provider Key** | **必须清**。新代码 Alembic 版本表与旧表冲突；`docker volume rm harnessflow_pgdata` 后由新迁移重建。清后 DeepSeek Key 需在系统管理页重新录入（Key 从 `D:/Code/EcoGain/.env` 的 `LLM_API_KEY` 或 DeepSeek 控制台取，**绝不写入任何文件**） |
| `dorisbe` | 旧 ods 库（`__raw/__shadow/__err/orders/__bak` 等残留表） | 建议连同 FE 一起清（见 3.4），让新代码从建库开始走全生命周期 |
| `miniodata` | 演示文件 | 可留可清，无副作用 |

清理命令：`docker compose down -v`（会连卷一起删，mysql 反正会重播种）。**down -v 前确认 deploy/ 三件套已入库（已在），否则 bind-mount 源丢失容器起不来（上一轮真实事故）。**

### 3.3 Doris root 密码是手工步骤，compose 里没有

`root/doris123` 是上一轮 FE 首启后手工 `SET PASSWORD` 设置的，**compose 未包含此步骤**。重建 FE 后 root 初始为空密码。重写时二选一并在新代码连接配置处适配：① init 脚本自动设密码；② 首启后手工 SET PASSWORD 并写入运行文档。

### 3.4 Doris FE 无持久化卷，BE 有——重建必须成对

FE 元数据在容器层（down 即失），BE 存储在 `dorisbe` 卷（down 后残留）。若只重建 FE 不清 BE 卷，FE 元数据为空但 BE 带旧存储，注册/表状态不一致。**规则：动 Doris 就 FE/BE 一起重建（down -v 或手动同时清）。**

### 3.5 宿主 sysctl：vm.max_map_count

Doris BE 要求宿主（Docker Desktop 的 Linux VM）`vm.max_map_count≥2000000`。entrypoint 的 sed 只绕过了**检查**，真实需求仍在；**Docker Desktop 重启/升级后可能失效**，BE 起不来先查这个：

```bash
docker run --rm --privileged alpine sysctl -w vm.max_map_count=2000000
```

### 3.6 control profile 引用旧代码路径

`docker-compose.yml` 中 api/worker/beat 的 `build: ./backend` 与 command（`app.main:app`、`app.core.seed`、`app.workers.celery_app`、`alembic upgrade head`）是按旧代码模块路径写的。**重写后要么保持同名模块入口，要么同步改 compose command**。backend 目录下的 `beat.pid`、`celerybeat-schedule*` 是旧运行残留，随重写一并清除。

### 3.7 杂项

- 根目录 `*.err` / `*.log` 是旧 Start-Process 重定向产物，可删。
- 现存容器由旧版 compose 创建（postgres 实为 16-alpine），下次 `up -d` 会按当前 compose 重建为 postgres:16，属预期。
- 宿主端口避让（3307/19030/5801/18030）是为躲宿主已有服务，**新代码连接配置直接按 §2.1 端口表写，勿改端口**。

---

## 4. 已验证数据面契约（血泪实测，直接遵守，禁止凭旧知识/网络旧文重写）

### 4.1 SeaTunnel 2.3.12 REST 契约

1. **提交**：`POST http://localhost:5801/hazelcast/rest/maps/submit-job?jobName={name}`——**不是** `/submit-job`。
2. **作业体是 JSON**，不是 HOCON 文本：顶层 `env` / `source[]` / `sink[]`，插件用 `plugin_name` 键：
   ```json
   {"env": {"job.mode": "BATCH", "parallelism": 1},
    "source": [{"plugin_name": "Jdbc", "url": "...", "driver": "com.mysql.cj.jdbc.Driver",
                 "user": "...", "password": "...", "query": "SELECT ..."}],
    "sink":   [{"plugin_name": "Jdbc", "url": "...", "driver": "com.mysql.cj.jdbc.Driver",
                 "user": "...", "password": "...",
                 "query": "INSERT INTO tbl (a,b) VALUES (?,?)"}]}
   ```
3. **Jdbc source 必须带结构化 `query`；Jdbc sink 必须带 `query`（INSERT 占位符模板）**。`table`/`database` 键会被静默忽略——不报错但一条数据都不写，这是最坑的静默失败。
4. **状态查询**：`GET /hazelcast/rest/maps/running-job/{id}`，字段 `jobStatus`/`errorMsg`。**作业结束后该端点返回 404 属正常语义**，必须兜底查 `GET /hazelcast/rest/maps/finished-jobs` 列表取终态。
5. REST 由自定义 hazelcast.yaml 开启（§2.1），容器未挂载该文件时全部 REST 404。

### 4.2 Doris 2.1.11 SQL 契约（单 BE 环境）

1. **建表必须显式 `PROPERTIES("replication_num"="1")`**，默认 3 在单 BE 下直接被拒。
2. **原子发布**：`ALTER TABLE {t} REPLACE WITH TABLE {t}__shadow PROPERTIES("swap"="true")`——**swap=true 是两表数据互换**，不是单向覆盖；旧数据落入 `__shadow` 槽位，RENAME 为 `__bak` 即回滚备份；回滚 = 再互换一次（按 P1 处理，签发 Capability）。
3. **首跑正式表不存在**：先 `CREATE TABLE {t} LIKE {t}__shadow` 再互换。
4. **分流 INSERT INTO ... SELECT 里不能带 `AS` 别名**（Doris 报错），列直接写。
5. 质量分流采用 **SQL 分流（D6）**：SeaTunnel 只做 源→`{target}__raw` 搬运；合格写 `__shadow`、错误入 `__err`（CASE WHEN 打错误码）由 Worker 发 Doris SQL 完成。**禁止 SeaTunnel 自定义插件、禁止多 Sink 双写。**
6. 表命名五槽位（D7）：`{t}__raw`(TRUNCATE) / `{t}__shadow`(重建) / `{t}__err`(追加留7天) / `{t}`(正式) / `{t}__bak`(留7天)。

### 4.3 URL 双视角规则（宿主 vs 容器）

Worker 在宿主访问 `localhost:3307/19030`；SeaTunnel 作业在容器内执行，`localhost` 指向容器自身。上一轮用 `//localhost:` → `//host.docker.internal:` 字符串替换（compose 已配 host-gateway）。**重做建议升级**：连接配置显式分「控制面地址 / 数据面容器地址」两个字段，由 build_job_json 各取所需，消灭运行时字符串替换这种隐式行为。

---

## 5. 设计输入：必读文档与继承决策

文档优先级：`docs/需求澄清与决策记录.md`（D1~D17）> 01~06 设计文档 > 原始需求。冲突时以决策记录为准。

**直接继承的架构决策**（上一轮验证成功，勿再发明）：

| 决策 | 内容 |
|---|---|
| D1 定位 | 生产级架构演示：协议是真的（三阶段/四眼/Capability/Outbox/Evidence Ledger 全真实现），环境仿真配套（Vault 用本地 AES-GCM 但按 KV v2 接口抽象） |
| D5/D6/D7 | 仅全量快照；SQL 分流；五槽位表命名 |
| D10~D12 | 风险-审批矩阵（P0 拒绝/P1-P2 双审四眼/P3 单审，Maker 禁占 Checker 槽）；两段式回滚；调度复用已审批 Preparation + 指纹漂移阻断 |
| D17 状态机 | draft → generating → gated → frozen → executing → executed/retired；**frozen 后任何字段不可变，只有 frozen 可 Prepare/执行/调度** |
| 三层状态隔离 | conversations/messages（对话）、agent_run + pending_question（生成状态机）、execution_runs（执行）各自独立载体 |
| 副作用原子投递 | ExecutionRun 创建与任务投递同一 PG 事务经 Outbox 落库；Tool Broker 是副作用唯一出口 |
| Capability | Ed25519 签名，绑定工具/主体/环境/制品指纹，**TTL 5min 硬约束** + 单次消费 Replay Guard |
| LLM Provider | 只依赖 OpenAI 兼容协议；管理页配置（admin），Key 加密入 DB；生成过程 SSE 流式 |

**技术栈**（决策记录第七节锁定）：Python 3.12（**锁死单一版本，上一轮 3.12/3.13 混装**）/ FastAPI / SQLAlchemy 2 async / Alembic / Celery 5 / LangGraph / Pydantic v2 / structlog / cryptography；Vue3 + Vite + TS + Pinia + Element Plus；SSE 不用 WebSocket。

---

## 6. 红线清单（上一轮踩过的坑 → 本次强制规则）

### 6.1 Git 与密钥纪律

| # | 上次的坑 | 本次规则 |
|---|---|---|
| 1 | 三把明文 API Key 随历史 commit 永久进 GitHub | Key 只进环境变量/gitignore 文件或 DB 加密存储；文档只写获取方式。**任何文件提交前 grep 一遍 key 模式**（sk- 等） |
| 2 | filter-repo 把未提交工作对象一起弄丢（relay_daemon.py 整文件消失） | 重写历史前必须完整 bundle 备份 + 工作区 clean |
| 3 | `git add` 漏新文件（providers.py），`__init__.py` 却已 import → push 后仓库 ImportError | 每次提交前 `git status` 核对新增文件全被跟踪；含新模块的提交 push 前在干净检出里跑一次启动冒烟 |
| 4 | bind-mount 源文件（hazelcast.yaml/JDBC 驱动）未入库，git clean 后容器挂载失败退出码 127 | **compose 引用的一切工作区文件必须入 git**；新增挂载先查 `git ls-files` |
| 5 | 攒大 commit | 沿用既有规范：一功能一 commit、中文 message、正文列要点（见 AGENTS.md「Git 提交规范」） |

### 6.2 后端实现纪律

| # | 上次的坑 | 本次规则 |
|---|---|---|
| 6 | prepare 响应后立即 decide 偶发 404（同请求会话时序） | prepare 落库走**独立事务提交**，写完即提交，不依赖请求会话收尾 |
| 7 | metadata_profiles 同表多条导致 `scalar_one_or_none` 抛异常 | 探查落库第一天起就是 **upsert 语义**（唯一约束 + ON CONFLICT），查询天然最多一行 |
| 8 | LLM 偶尔返回预算 0，链路直接断 | LLM 产出的所有数值按不可信输入处理，统一兜底默认值 |
| 9 | async 路径混同步 IO 踩 greenlet 错误 | 全程 AsyncSession/异步驱动，严禁在 async 上下文碰同步引擎或阻塞 IO |
| 10 | Capability TTL 5min 内 relay 未派发令牌作废 | commit→outbox 派发延迟当显式 SLO 设计（<30s），超窗可观测可重试，不靠守护进程保活兜底 |
| 11 | 临时 print 调试残留 | structlog 结构化日志 + TraceID 从第一天就是默认，交付前零裸 print |
| 12 | Python 3.12/3.13 版本漂移 | venv/requirements/Dockerfile 三处锁同一版本 |

### 6.3 运行环境纪律（若沿用宿主直跑控制面，见 §7）

| # | 上次的坑 | 本次规则 |
|---|---|---|
| 13 | Git Bash `(cmd &)` 后台进程被会话静默收割，beat/worker 反复死且无输出 | 后台常驻一律 PowerShell `Start-Process` 分离启动 |
| 14 | celery beat 在 Windows 不稳，被迫自写 relay_daemon | Windows 宿主跑 Celery 必须 `-P solo`；beat 能不用就不用（调度 tick 并入自研守护或 API 内调度） |
| 15 | SSE 经 Redis Pub/Sub 偶发丢消息/断连 | 事件**先落库再推送**，断线重连补快照；前端兜底轮询 |

---

## 7. 控制面部署

**控制面全容器化**，即 compose `control` profile 直接用。Windows 很多坑的根源都是「宿主跑控制面 + 容器跑数据面」的混合部署；进容器后 beat/-P prefork/网络视角全部正常化。开发迭代用代码卷挂载 + `--reload` 解决，不必反复 build。

**§4.3 的双地址连接字段设计**都建议做，它同时消除两种部署下的 URL 歧义。

---

## 9. 命令速查（Windows 宿主，Git Bash）

```bash
# 全量拉起（首次或清库后）
docker compose up -d postgresql redis
docker compose --profile datalane up -d
# BE 起不来 → 先修 sysctl（见 §3.5）再 restart doris-be

# 健康自检
curl http://localhost:8000/health                # API（起来后）
curl http://localhost:5801/hazelcast/rest/maps/running-job/x   # SeaTunnel REST 通=配置对
docker exec harnessflow-mysql-src-1 mysql -uetl_reader -preader123 shop -e "SELECT COUNT(*) FROM orders;"  # =10

# Doris（MySQL 协议）
docker exec harnessflow-doris-fe-1 mysql -h172.28.1.1 -P9030 -uroot -pdoris123

# 彻底重置（注意 §3.2/§3.4：down -v 会清 pgdata/dorisbe/miniodata）
docker compose --profile datalane --profile control down -v
```

控制面启动（方案 B 时）：PowerShell `Start-Process` 分离启动 uvicorn:8000 / celery worker -P solo / 派发守护；前端 `npm run dev`（5173，/api 代理 8000）。
