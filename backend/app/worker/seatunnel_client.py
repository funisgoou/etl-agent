"""SeaTunnel REST 客户端（SPEC 7.5 / HANDOVER §4.1 血泪契约）：

1. 提交：POST /hazelcast/rest/maps/submit-job?jobName=...（不是 /submit-job）
2. 作业体是 JSON（plugin_name 键），Jdbc source 必须带结构化 query，sink 必须带 INSERT 模板 query
3. 状态：running-job/{id}（结束后 404 属正常，兜底查 finished-jobs）
仅供 Worker 任务经 Broker handler 使用。
"""

import httpx
import structlog

from app.core.config import get_settings

logger = structlog.get_logger(__name__)


def _base() -> str:
    return get_settings().seatunnel_url.rstrip("/")


async def submit_job(job: dict, job_name: str) -> str:
    """提交作业，返回 job_id。"""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{_base()}/hazelcast/rest/maps/submit-job",
            params={"jobName": job_name},
            json=job,
        )
        resp.raise_for_status()
        data = resp.json()
        job_id = str(data.get("jobId") or data.get("job_id") or "")
        if not job_id:
            raise RuntimeError(f"SeaTunnel 未返回 jobId: {data}")
        logger.info("seatunnel 作业已提交", job_id=job_id, job_name=job_name)
        return job_id


async def job_status(job_id: str) -> dict:
    """查询状态：running 404 时兜底 finished-jobs 取终态。

    Returns:
        {"status": "RUNNING|FINISHED|FAILED|CANCELED|UNKNOWN", "errorMsg": str}
    """
    async with httpx.AsyncClient(timeout=10) as client:
        # 1. 运行中查询
        resp = await client.get(f"{_base()}/hazelcast/rest/maps/running-job/{job_id}")
        if resp.status_code == 200:
            data = resp.json()
            return {"status": data.get("jobStatus", "UNKNOWN"), "errorMsg": data.get("errorMsg", "")}
        # 2. 终态兜底（结束后 running-job 返回 404 属正常语义）
        resp2 = await client.get(f"{_base()}/hazelcast/rest/maps/finished-jobs")
        if resp2.status_code == 200:
            for item in resp2.json() or []:
                if str(item.get("jobId")) == job_id:
                    return {"status": item.get("jobStatus", "UNKNOWN"), "errorMsg": item.get("errorMsg", "")}
        return {"status": "UNKNOWN", "errorMsg": ""}


async def kill_job(job_id: str) -> bool:
    """取消作业。"""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(f"{_base()}/hazelcast/rest/maps/stop-job", json={"jobId": int(job_id)} if job_id.isdigit() else {"jobId": job_id})
        return resp.status_code == 200


def build_job_json(
    *,
    mode: str,
    source: dict,
    target_table: str,
    target_db: str,
    doris_user: str,
    doris_password: str,
    doris_host_for_engine: str,
    doris_port_for_engine: int,
    columns: list[str],
    sample_limit: int | None = None,
) -> dict:
    """构建作业体（HANDOVER §4.1 契约）。

    - mysql 源：Jdbc source + 结构化 query（LIMIT 注入采样）
    - csv 源：S3 source（file_path 是 s3a://bucket/key 形态，拆给 S3 插件）
    - sink：Jdbc + INSERT 占位符模板（Doris MySQL 协议）
    双地址由调用方显式传入（§4.3：控制面地址 / 数据面容器地址两个视角）。
    """
    # 1. 源配置
    if source["kind"] == "mysql":
        query = f"SELECT {', '.join(f'`{c}`' for c in columns)} FROM `{source['table']}`"
        if sample_limit:
            query += f" LIMIT {int(sample_limit)}"
        source_block = {
            "plugin_name": "Jdbc",
            "url": source["url"],
            "driver": "com.mysql.cj.jdbc.Driver",
            "user": source["user"],
            "password": source["password"],
            "query": query,
        }
    else:  # csv via S3
        path = source["file_path"].replace("s3a://", "")
        bucket, _, key = path.partition("/")
        source_block = {
            "plugin_name": "S3",
            "path": f"s3a://{bucket}/{key}",
            "file_format_type": "csv",
            "delimiter": ",",
            "header_row_number": 1,
            "endpoint": source["minio_endpoint"],
            "access_key": source["minio_access_key"],
            "secret_key": source["minio_secret_key"],
            "hdfs_site": {"fs.s3a.endpoint": source["minio_endpoint"], "fs.s3a.path.style.access": "true"},
        }
    # 2. sink：INSERT 模板（列序与 source query 一致）
    placeholders = ", ".join(["?"] * len(columns))
    col_list = ", ".join(f"`{c}`" for c in columns)
    sink_block = {
        "plugin_name": "Jdbc",
        "url": f"jdbc:mysql://{doris_host_for_engine}:{doris_port_for_engine}/{target_db}",
        "driver": "com.mysql.cj.jdbc.Driver",
        "user": doris_user,
        "password": doris_password,
        "query": f"INSERT INTO `{target_table}` ({col_list}) VALUES ({placeholders})",
        "enable_upsert": False,
    }
    return {
        "env": {"job.mode": "BATCH", "parallelism": 1},
        "source": [source_block],
        "sink": [sink_block],
    }
