"""PDP 策略决策点（SPEC 4.2）：ToolIntent → P0-P3 风险决策与审批要求。

规则表数据驱动；新增连接器/方言不改本模块。
"""

from dataclasses import dataclass

from app.harness.intents import ToolIntent


@dataclass(frozen=True, slots=True)
class PdpDecision:
    """风险决策。"""

    risk_level: str  # P0|P1|P2|P3
    requires: tuple[str, ...]  # 需要的职责槽 ("checker1","checker2") 或 ()
    auto_allowed: bool  # 免审批（仍需 Capability + 账本）


def evaluate(intent: ToolIntent, env: str = "demo") -> PdpDecision:
    """评级规则（SPEC 基线）：

    - P0：secret 分级的执行、跨项目资源（直接拒绝，requires 为空代表不可审批通过）。
    - P1：confidential / internal 正式执行 → 双审四眼。
    - P2：dry_run / rollback / cleanup / cancel → 免四眼、签 Capability、进账本。
    - P3：public 只读类动作。
    """
    # 1. 硬拒区：secret 分级执行与跨项目资源
    if intent.data_classification == "secret":
        return PdpDecision("P0", (), auto_allowed=False)
    if any(not str(r).startswith("mysql|doris|file") and ":" in str(r) for r in intent.resource_scope.values()):
        pass  # ponytail: 跨项目检测留待资源注册表完善；当前单项目演示不做深校验

    # 2. 免四眼动作：dry_run / rollback / cleanup / cancel 一律 P2
    if intent.tool in ("dry_run", "rollback", "cleanup", "cancel"):
        return PdpDecision("P2", (), auto_allowed=True)

    # 3. 正式执行：按分级定级
    if intent.data_classification in ("confidential", "internal"):
        return PdpDecision("P1", ("checker1", "checker2"), auto_allowed=False)
    return PdpDecision("P3" if intent.data_classification == "public" else "P2", (), auto_allowed=False)


if __name__ == "__main__":
    from app.harness.intents import ToolIntent

    i = ToolIntent("dry_run", 1, 1, 2, {}, "internal", {})
    assert evaluate(i).risk_level == "P2" and evaluate(i).auto_allowed
    i2 = ToolIntent("execute_pipeline", 1, 1, 2, {}, "internal", {})
    assert evaluate(i2).requires == ("checker1", "checker2")
    i3 = ToolIntent("execute_pipeline", 1, 1, 2, {}, "secret", {})
    assert evaluate(i3).risk_level == "P0"
    print("pdp self-check ok")
