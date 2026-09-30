"""染缸状态业务规则。

改可染色（ready）的判定集中在本模块的 validate_vat_status_change：
既有「最新浸染电位 ≤ -500 mV」门槛与发酵温志齐套检查挂在同一处，
任一不过即抛 VatRuleError，调用方不得半改状态。
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Sequence

from sqlalchemy.orm import Session

from app.models import DipLot, FermentLog, Vat

# 最新浸染电位门槛（照旧，不得拆除）
REDOX_THRESHOLD = Decimal("-500")

# 温志读数区间
TEMP_MIN = Decimal("20")
TEMP_MAX = Decimal("42")
PH_MIN = Decimal("8")
PH_MAX = Decimal("12")

# 温志齐套要求
READY_MIN_LOGS = 4
READY_MAX_TEMP_GAP = Decimal("3")
READY_MIN_PH_AVG = Decimal("9")


class VatRuleError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def _as_utc(value: datetime) -> datetime:
    """表单可能提交无时区时间，统一按 UTC 看待后再比较。"""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def assert_can_log_ferment(vat: Vat) -> None:
    """仅还原中的染缸可登记发酵温志。"""
    if vat.status != Vat.STATUS_REDUCING:
        raise VatRuleError("仅还原中的染缸可登记发酵温志。")


def assert_reading_in_range(tempC: Decimal, ph: Decimal) -> None:
    """读数区间校验：新建与更新温志共用。"""
    if not (TEMP_MIN <= tempC <= TEMP_MAX):
        raise VatRuleError(
            f"液温摄氏须在 {TEMP_MIN} 到 {TEMP_MAX} 之间，当前为 {tempC}。"
        )
    if not (PH_MIN <= ph <= PH_MAX):
        raise VatRuleError(
            f"酸碱值须在 {PH_MIN} 到 {PH_MAX} 之间，当前为 {ph}。"
        )


def validate_ferment_log(
    db: Session,
    vat: Vat,
    seq: int,
    tempC: Decimal,
    ph: Decimal,
    exclude_log_id: Optional[int] = None,
) -> None:
    """温志新建与更新共用：仅还原中 + 同缸序号唯一 + 读数区间。

    数据库另有 uniq_ferment_seq_per_vat 唯一约束兜底并发写入。
    """
    assert_can_log_ferment(vat)
    if seq < 1:
        raise VatRuleError("志序号须为不小于 1 的整数。")
    assert_reading_in_range(tempC, ph)
    dup = db.query(FermentLog.id).filter(
        FermentLog.vat_id == vat.id, FermentLog.seq == seq
    )
    if exclude_log_id is not None:
        dup = dup.filter(FermentLog.id != exclude_log_id)
    if dup.first() is not None:
        raise VatRuleError(f"本缸已存在志序号 {seq}，同缸志序号不可重复。")


def assert_ferment_complete(
    logs: Sequence[FermentLog], latest_lot: Optional[DipLot]
) -> None:
    """发酵温志齐套检查（与电位门槛同为改可染色的必要条件）。

    - 至少 4 条连续志（取采样时刻最近的 4 条）；
    - 相邻液温相差不超过 3 摄氏度；
    - 四条酸碱值平均不低于 9；
    - 最新采集晚于最近浸染。
    """
    ordered = sorted(logs, key=lambda x: (_as_utc(x.sampledAt), x.id))
    if len(ordered) < READY_MIN_LOGS:
        raise VatRuleError(
            f"发酵温志不齐套：至少需 {READY_MIN_LOGS} 条连续志，当前仅 {len(ordered)} 条。"
        )
    last4 = ordered[-READY_MIN_LOGS:]

    for prev, cur in zip(last4, last4[1:]):
        gap = abs(Decimal(cur.tempC) - Decimal(prev.tempC))
        if gap > READY_MAX_TEMP_GAP:
            raise VatRuleError(
                "发酵温志不齐套：相邻志液温相差 "
                f"{gap} 摄氏度，超过 {READY_MAX_TEMP_GAP} 摄氏度。"
            )

    ph_avg = sum(Decimal(x.ph) for x in last4) / Decimal(READY_MIN_LOGS)
    if ph_avg < READY_MIN_PH_AVG:
        raise VatRuleError(
            f"发酵温志不齐套：最近四条酸碱值平均为 {ph_avg.quantize(Decimal('0.01'))}，"
            f"低于 {READY_MIN_PH_AVG}。"
        )

    if latest_lot is None or not (
        _as_utc(last4[-1].sampledAt) > _as_utc(latest_lot.dippedAt)
    ):
        raise VatRuleError("发酵温志不齐套：最新采集时刻须晚于最近一次浸染。")


def assert_can_mark_ready(
    latest: Optional[DipLot], ferment_logs: Sequence[FermentLog]
) -> None:
    """改可染色：最新浸染电位门槛 + 温志齐套，缺一不可。"""
    if latest is None or latest.redoxMv is None or Decimal(latest.redoxMv) > REDOX_THRESHOLD:
        raise VatRuleError(
            "无法设为可染色：最新浸染批次的氧化还原电位为空或高于 -500 mV。"
        )
    assert_ferment_complete(ferment_logs, latest)


def validate_vat_status_change(
    vat: Vat,
    new_status: str,
    latest: Optional[DipLot],
    ferment_logs: Optional[Sequence[FermentLog]] = None,
) -> None:
    """改状态唯一入口：电位门槛与温志齐套都挂在这里。"""
    if new_status == Vat.STATUS_READY:
        assert_can_mark_ready(latest, ferment_logs or [])
