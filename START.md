# ETL-Agent 本地启动指南（Windows 宿主直跑）

> 重启电脑后的完整拉起流程。共 4 个常驻终端 + 1 次性环境准备。
> 所有命令在 Git Bash 下执行；`cd` 到仓库根 `D:\Code\ETL-Agent`。

## 0. 一次性准备（每次重启电脑后都要做）

```bash
# 1) 启动 Docker Desktop（手动开，等它变绿）
# 2) 修复 Doris BE 依赖的内核参数（Docker Desktop 重启后会失效）
docker run --rm --privileged alpine sysctl -w vm.max_map_count=2000000
```

## 1. 数据面 + 存储容器

```bash
cd /d/Code/ETL-Agent

# 控制面存储（postgres/redis）
docker compose up -d postgresql redis

# 数据面全家桶（mysql/doris-fe/doris-be/seatunnel/minio）
docker compose --profile datalane up -d
```

等待约 60 秒后自检（BE 注册 FE 需要时间）：

```bash
# 容器全 Up
docker compose ps

# Doris BE 已注册且 Alive=true（关键！）
docker exec etl-agent-doris-fe-1 mysql -h172.29.1.1 -P9030 -uroot -pdoris123 \
  -e "SHOW BACKENDS" 2>/dev/null | grep -c 172.29.1.2
# 输出 1 = 正常；输出 0 时手动注册：
#   docker exec etl-agent-doris-fe-1 mysql -h172.29.1.1 -P9030 -uroot -pdoris123 \
#     -e "ALTER SYSTEM ADD BACKEND '172.29.1.2:9050'"

# 源库种子（orders=20 / customers=10）
docker exec etl-agent-mysql-src-1 mysql -uetl_reader -preader123 biz_demo \
  -e "SELECT COUNT(*) FROM orders;"
```

## 2. 后端 API（终端 1，常驻）

```bash
cd /d/Code/ETL-Agent/backend
set -a && . ./.env && set +a          # .env 已就绪（含 LLM key，勿入库）
uv run python run.py                   # ⚠️ 必须用 run.py，不能用 uvicorn CLI
                                       #    （Windows 事件循环时序，见 run.py 注释）
```

验证：`curl http://localhost:8000/health` → `{"status":"ok",...}`

> 数据库迁移与种子已落库（pgdata 卷持久），正常启动**无需**再跑。
> 仅当执行过 `docker compose down -v` 清库后需要：
> `uv run alembic upgrade head && uv run python -m app.core.seed`

## 3. Outbox 中继（终端 2，常驻）

```bash
cd /d/Code/ETL-Agent/backend
set -a && . ./.env && set +a
uv run python -m app.worker.relay
# 看到 "outbox relay 启动" 即成功
```

## 4. Celery Worker（终端 3，常驻）

```bash
cd /d/Code/ETL-Agent/backend
set -a && . ./.env && set +a
uv run celery -A app.worker.celery_app.celery_app worker --loglevel=INFO -P solo -c 1
# ⚠️ Windows 必须 -P solo；看到 "ready." 即成功
```

## 5. 前端（终端 4，常驻）

```bash
cd /d/Code/ETL-Agent/frontend
VITE_MOCK=false npm run dev -- --port 5173 --strictPort
# ⚠️ 必须带 VITE_MOCK=false，否则进 mock 模式
```

浏览器打开 http://localhost:5173 —— 登录页应显示「已连接真实后端」。

## 演示账号

| 账号 | 密码 | 用途 |
|---|---|---|
| gen1 | Passw0rd!x | 有存量数据（连接/版本/运行记录） |
| maker / checker1 / checker2 / operator / auditor | Demo#2026 | 五人四眼分工演示 |

## 停止

- 四个终端各自 Ctrl+C
- 容器：`docker compose --profile datalane --profile control stop`（或 `down`；`down -v` 会清库慎用）

## 端口备忘（Hyper-V 保留区间规避）

宿主端口已固定为：**15432**(postgres) / **13307**(mysql-src) / 其余不变（5801/18030/19030/9000/8040/6379/8000/5173）。
若再遇 `ports are not available ... access permissions`，用 `netsh interface ipv4 show excludedportrange protocol=tcp`
查保留区间后改 compose 宿主端口（容器内端口不动，库内连接配置用容器名互访不受影响）。

> 注意：库里 gen1 项目登记的 `localhost:3307` 连接在宿主端口迁移后探查/测试会失败——
> 在前端编辑该连接把端口改为 **13307**，或用 seed 账号（maker）的预置连接（容器名互访，不受影响）。

> backend/.env 的 DATABASE_URL 已指向 15432；`docker compose down -v` 清库后需重跑迁移+种子。
