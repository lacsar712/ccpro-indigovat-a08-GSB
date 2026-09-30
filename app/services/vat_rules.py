"""染缸状态业务规则。

改可染色（ready）的判定全部集中在 :func:`validate_vat_status_change`：
既保留原有的最新浸染电位门槛（redoxMv <= -500），又新增发酵温志齐套检查，
两者挂在同一个改状态函数里，缺一不可。
"""

from datetime import timezone
from decimal import Decimal
from typing import Optional, Sequence

from app.models import DipLot, FermentLog, Vat


# 发酵温志读数区间
TEMP_MIN = Decimal("20")
TEMP_MAX = Decimal("42")
PH_MIN = Decimal("8")
PH_MAX = Decimal("12")

# 温志齐套参数
MIN_READY_LOGS = 4
MAX_ADJACENT_TEMP_DIFF = Decimal("3")
READY_PH_AVG = Decimal("9")


class VatRuleError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def _as_aware(dt):
    """表单提交的时刻为 naive 本地时间，统一按 UTC 处理以便与种子数据比较。"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def assert_can_mark_ready(latest: Optional[DipLot]) -> None:
    """不能将染缸标为 ready，除非最新浸染批次 redoxMv 已填且 <= -500。"""
    if latest is None or latest.redoxMv is None or Decimal(latest.redoxMv) > Decimal("-500"):
        raise VatRuleError(
            "无法设为可染色：最新浸染批次的氧化还原电位为空或高于 -500 mV。"
        )


def validate_ferment_readings(tempC: Decimal, ph: Decimal) -> None:
    """温志读数区间校验，新建与更新共用。

    液温须在 20~42 ℃ 之间，酸碱值须在 8~12 之间（含边界）。
    """
    tempC = Decimal(tempC)
    ph = Decimal(ph)
    if not (TEMP_MIN <= tempC <= TEMP_MAX):
        raise VatRuleError(f"液温须在 {TEMP_MIN}~{TEMP_MAX} ℃ 之间，当前读数 {tempC} ℃。")
    if not (PH_MIN <= ph <= PH_MAX):
        raise VatRuleError(f"酸碱值须在 {PH_MIN}~{PH_MAX} 之间，当前读数 {ph}。")


def assert_ferment_logs_ready(
    logs: Sequence[FermentLog], latest_lot: Optional[DipLot]
) -> None:
    """温志齐套检查（与电位门槛同为改可染色的必要条件）。

    取最近四条连续温志，要求：
    1. 至少 4 条；
    2. 相邻液温差不超过 3 ℃；
    3. 四条酸碱值平均不低于 9；
    4. 最新采样时刻晚于最近一次浸染。
    """
    ordered = sorted(logs, key=lambda x: (_as_aware(x.sampledAt), x.id))
    if len(ordered) < MIN_READY_LOGS:
        raise VatRuleError(
            f"发酵温志未齐套：至少需要 {MIN_READY_LOGS} 条连续温志，"
            f"当前仅 {len(ordered)} 条。"
        )

    last4 = ordered[-MIN_READY_LOGS:]

    for prev, cur in zip(last4, last4[1:]):
        diff = abs(Decimal(cur.tempC) - Decimal(prev.tempC))
        if diff > MAX_ADJACENT_TEMP_DIFF:
            raise VatRuleError(
                f"发酵温志未齐套：相邻液温差 {diff} ℃ 超过 "
                f"{MAX_ADJACENT_TEMP_DIFF} ℃（志 {prev.seq}→{cur.seq}）。"
            )

    ph_avg = sum((Decimal(x.ph) for x in last4), Decimal("0")) / MIN_READY_LOGS
    if ph_avg < READY_PH_AVG:
        raise VatRuleError(
            f"发酵温志未齐套：最近四条酸碱值平均为 {ph_avg.quantize(Decimal('0.01'))}，"
            f"低于 {READY_PH_AVG}。"
        )

    latest_sampled = _as_aware(last4[-1].sampledAt)
    latest_dipped = _as_aware(latest_lot.dippedAt) if latest_lot else None
    if latest_dipped is None or latest_sampled <= latest_dipped:
        raise VatRuleError(
            "发酵温志未齐套：最新采样时刻必须晚于最近一次浸染。"
        )


def validate_vat_status_change(
    vat: Vat,
    new_status: str,
    latest: Optional[DipLot],
    ferment_logs: Optional[Sequence[FermentLog]] = None,
) -> None:
    """改缸状态的唯一判定入口。

    改可染色时，原有浸染电位门槛与新增发酵温志齐套检查都在此处执行，
    任一不通过即抛 VatRuleError，调用方不得落库改状态（无半改）。
    """
    if new_status == Vat.STATUS_READY:
        # 既有门槛：最新浸染批次 redoxMv <= -500，保持不拆。
        assert_can_mark_ready(latest)
        # 新增齐套：最近四条温志温差、酸碱均值与采样先后。
        assert_ferment_logs_ready(ferment_logs or [], latest)
