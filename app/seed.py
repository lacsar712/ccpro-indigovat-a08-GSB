import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import DipLot, FermentLog, User, Vat, Workshop

_PWD_SALT = os.environ.get("PWD_SALT", "indigovat-dev-salt").encode("utf-8")


def hash_password(password: str) -> str:
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), _PWD_SALT, 120000
    )
    return digest.hex()


def verify_password(plain: str, hashed: str) -> bool:
    return hmac.compare_digest(hash_password(plain), hashed)


def ensure_seed_data(db: Session) -> None:
    """幂等种子：账号 + 蓝靛湾/清水江样例缸位与电位序列。"""
    if not db.query(User).filter_by(username="admin").first():
        db.add(
            User(
                username="admin",
                password_hash=hash_password("123456"),
                is_superuser=True,
            )
        )
    if not db.query(User).filter_by(username="worker").first():
        db.add(
            User(
                username="worker",
                password_hash=hash_password("123456"),
                is_superuser=False,
            )
        )
    db.commit()

    if db.query(Workshop).first():
        return

    w1 = Workshop(name="蓝靛湾一号坊", region="黔东南", notes="晨露还原较快")
    w2 = Workshop(name="清水江二号坊", region="黔南", notes="缸体较深，保温好")
    db.add_all([w1, w2])
    db.flush()

    v1 = Vat(
        workshop_id=w1.id,
        code="V-01",
        dyeType="土靛",
        volumeL=Decimal("800.00"),
        status=Vat.STATUS_REDUCING,
    )
    v2 = Vat(
        workshop_id=w1.id,
        code="V-02",
        dyeType="合成靛",
        volumeL=Decimal("600.00"),
        status=Vat.STATUS_IDLE,
    )
    v3 = Vat(
        workshop_id=w2.id,
        code="V-11",
        dyeType="土靛",
        volumeL=Decimal("900.00"),
        status=Vat.STATUS_REDUCING,
    )
    v4 = Vat(
        workshop_id=w2.id,
        code="V-12",
        dyeType="板蓝根靛",
        volumeL=Decimal("750.00"),
        status=Vat.STATUS_READY,
    )
    db.add_all([v1, v2, v3, v4])
    db.flush()

    now = datetime.now(timezone.utc)

    def lots(vat_id: int, series):
        """series: (hours_ago, meters, redox or None)"""
        rows = []
        for hours, meters, redox in series:
            rows.append(
                DipLot(
                    vat_id=vat_id,
                    dippedAt=now - timedelta(hours=hours),
                    clothMeters=Decimal(meters),
                    redoxMv=Decimal(redox) if redox is not None else None,
                )
            )
        return rows

    def ferment(vat_id: int, series):
        """series: (hours_ago, seq, temp_c, ph, inspector)。"""
        rows = []
        for hours, seq, temp, ph, inspector in series:
            rows.append(
                FermentLog(
                    vat_id=vat_id,
                    seq=seq,
                    tempC=Decimal(temp),
                    ph=Decimal(ph),
                    sampledAt=now - timedelta(hours=hours),
                    inspector=inspector,
                )
            )
        return rows

    db.add_all(
        lots(
            v1.id,
            [
                (36, "18.00", "-410.00"),
                (28, "22.50", "-455.00"),
                (20, "30.00", "-490.00"),
                (12, "40.00", "-510.00"),
                (8, "45.00", "-520.00"),
            ],
        )
    )
    db.add_all(
        lots(
            v2.id,
            [
                (6, "8.00", None),
                (1, "12.00", None),
            ],
        )
    )
    db.add_all(
        lots(
            v3.id,
            [
                (40, "25.00", "-390.00"),
                (30, "35.00", "-430.00"),
                (22, "48.00", "-460.00"),
                (14, "60.00", "-480.00"),
            ],
        )
    )
    db.add_all(
        lots(
            v4.id,
            [
                (48, "20.00", "-420.00"),
                (32, "28.00", "-470.00"),
                (20, "33.00", "-505.00"),
                (10, "38.50", "-530.00"),
            ],
        )
    )

    # V-01（还原中）：四条齐套温志——相邻温差 ≤3 ℃、pH 均值 9.3 ≥9，
    # 且最新采样晚于最近浸染（最近浸染 8 小时前，最新采样 1 小时前）。
    db.add_all(
        ferment(
            v1.id,
            [
                (6, 1, "30.00", "9.00", "阿靛"),
                (5, 2, "31.50", "9.20", "阿靛"),
                (3, 3, "30.50", "9.40", "青禾"),
                (1, 4, "32.00", "9.60", "青禾"),
            ],
        )
    )
    # V-03（还原中）：只有 3 条温志，差一条，不可改可染色。
    db.add_all(
        ferment(
            v3.id,
            [
                (9, 1, "33.00", "9.10", "阿岚"),
                (7, 2, "34.00", "9.20", "阿岚"),
                (4, 3, "33.50", "9.30", "阿岚"),
            ],
        )
    )
    # V-04（可染色）：最近一次浸染 10 小时前，四条温志均在其后，保持状态自洽。
    db.add_all(
        ferment(
            v4.id,
            [
                (9, 1, "29.00", "9.20", "青禾"),
                (7, 2, "30.50", "9.30", "青禾"),
                (5, 3, "31.00", "9.40", "阿靛"),
                (3, 4, "30.00", "9.50", "阿靛"),
            ],
        )
    )
    db.commit()
