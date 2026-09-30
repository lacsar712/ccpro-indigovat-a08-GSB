"""靛蓝发酵温志专页：还原中按缸登记、改记温志。

与还原台分开的独立页面（顶栏挂载）；改可染色的齐套判定不在这里，
统一走 app.services.vat_rules.validate_vat_status_change。
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from jinja2.utils import markupsafe
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload
import json

from app.auth import get_current_user
from app.db import get_db
from app.models import FermentLog, Vat, Workshop
from app.services.vat_rules import (
    VatRuleError,
    validate_ferment_log,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _tojson(value):
    return markupsafe.Markup(json.dumps(value, ensure_ascii=False))


templates.env.filters["tojson"] = _tojson

STATUS_LABELS = {
    Vat.STATUS_IDLE: "闲置",
    Vat.STATUS_REDUCING: "还原中",
    Vat.STATUS_READY: "可染色",
}


def render(request: Request, name: str, context: dict, status_code: int = 200):
    ctx = {k: v for k, v in context.items() if k != "request"}
    return templates.TemplateResponse(request, name, ctx, status_code=status_code)


def _fmt_dt(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    return value.strftime("%Y-%m-%d %H:%M")


def _form_local(value: datetime) -> str:
    """datetime-local 回填：去掉时区与秒。"""
    return value.strftime("%Y-%m-%dT%H:%M")


def _log_payload(log: FermentLog) -> dict:
    return {
        "id": log.id,
        "seq": log.seq,
        "tempC": float(log.tempC),
        "ph": float(log.ph),
        "sampledAt": _fmt_dt(log.sampledAt),
        "sampledAtRaw": _form_local(log.sampledAt),
        "inspector": log.inspector,
    }


def _vat_brief(vat: Vat) -> dict:
    logs = sorted(vat.ferment_logs, key=lambda x: (x.sampledAt, x.id))
    temps = [float(x.tempC) for x in logs]
    phs = [float(x.ph) for x in logs]
    last4 = logs[-4:]
    return {
        "id": vat.id,
        "code": vat.code,
        "dyeType": vat.dyeType,
        "status": vat.status,
        "statusLabel": STATUS_LABELS.get(vat.status, vat.status),
        "workshopName": vat.workshop.name if vat.workshop else "",
        "logCount": len(logs),
        "logs": [_log_payload(x) for x in logs],
        "last4Count": len(last4),
        "last4MaxGap": (
            round(max(abs(b - a) for a, b in zip(temps[-4:], temps[-3:])), 2)
            if len(temps) >= 2 and len(logs) >= 4
            else None
        ),
        "last4PhAvg": (
            round(sum(phs[-4:]) / 4, 2) if len(phs) >= 4 else None
        ),
        "lastSampledAt": _fmt_dt(logs[-1].sampledAt) if logs else None,
    }


def _page_context(
    request: Request,
    db: Session,
    user,
    selected_vat: Optional[int] = None,
    error: Optional[str] = None,
):
    vats = (
        db.query(Vat)
        .options(
            joinedload(Vat.workshop),
            joinedload(Vat.ferment_logs),
        )
        .order_by(Vat.code)
        .all()
    )
    payloads = [_vat_brief(v) for v in vats]
    selected = next((v for v in payloads if v["id"] == selected_vat), None)
    return {
        "request": request,
        "user": user,
        "workshops": [
            {"id": w.id, "name": w.name}
            for w in db.query(Workshop).order_by(Workshop.name).all()
        ],
        "vats": payloads,
        "selected_vat": selected_vat,
        "selected": selected,
        "error": error,
        "status_labels": STATUS_LABELS,
        "active": "ferment",
    }


@router.get("/ferment", response_class=HTMLResponse)
async def ferment_page(
    request: Request,
    vat: Optional[int] = None,
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    return render(request, "ferment.html", _page_context(request, db, user, vat))


def _parse_log_form(seq: str, tempC: str, ph: str, sampledAt: str, inspector: str):
    """表单解析；失败一律中文 ValueError。"""
    inspector = inspector.strip()
    if not inspector:
        raise ValueError("巡检人不可为空。")
    try:
        seq_val = int(seq)
    except ValueError:
        raise ValueError("志序号须为整数。")
    try:
        temp_val = Decimal(tempC)
        ph_val = Decimal(ph)
    except InvalidOperation:
        raise ValueError("液温与酸碱值须为数字。")
    try:
        sampled = datetime.fromisoformat(sampledAt)
    except ValueError:
        raise ValueError("采样时刻格式无效。")
    return seq_val, temp_val, ph_val, sampled, inspector


@router.post("/ferment/vats/{pk}/logs", response_class=HTMLResponse)
async def ferment_log_create(
    pk: int,
    request: Request,
    seq: str = Form(...),
    tempC: str = Form(...),
    ph: str = Form(...),
    sampledAt: str = Form(...),
    inspector: str = Form(...),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    vat = db.get(Vat, pk)
    if not vat:
        return RedirectResponse("/ferment", status_code=303)
    error = None
    try:
        seq_val, temp_val, ph_val, sampled, inspector_val = _parse_log_form(
            seq, tempC, ph, sampledAt, inspector
        )
        validate_ferment_log(db, vat, seq_val, temp_val, ph_val)
        db.add(
            FermentLog(
                vat_id=pk,
                seq=seq_val,
                tempC=temp_val,
                ph=ph_val,
                sampledAt=sampled,
                inspector=inspector_val,
            )
        )
        db.commit()
        return RedirectResponse(f"/ferment?vat={pk}", status_code=303)
    except (VatRuleError, ValueError) as exc:
        error = getattr(exc, "message", None) or f"温志无效：{exc}"
        db.rollback()
    except IntegrityError:
        # 并发同缸同序号：唯一约束兜底，只许一笔落库
        db.rollback()
        error = "志序号冲突：本缸已有相同志序号，该笔未登记（可能为并发重复提交）。"
    return render(
        request,
        "ferment.html",
        _page_context(request, db, user, pk, error),
        status_code=400,
    )


@router.post("/ferment/logs/{log_id}/edit", response_class=HTMLResponse)
async def ferment_log_edit(
    log_id: int,
    request: Request,
    seq: str = Form(...),
    tempC: str = Form(...),
    ph: str = Form(...),
    sampledAt: str = Form(...),
    inspector: str = Form(...),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    log = db.get(FermentLog, log_id)
    if not log:
        return RedirectResponse("/ferment", status_code=303)
    pk = log.vat_id
    vat = db.get(Vat, pk)
    error = None
    try:
        seq_val, temp_val, ph_val, sampled, inspector_val = _parse_log_form(
            seq, tempC, ph, sampledAt, inspector
        )
        validate_ferment_log(db, vat, seq_val, temp_val, ph_val, exclude_log_id=log_id)
        log.seq = seq_val
        log.tempC = temp_val
        log.ph = ph_val
        log.sampledAt = sampled
        log.inspector = inspector_val
        db.commit()
        return RedirectResponse(f"/ferment?vat={pk}", status_code=303)
    except (VatRuleError, ValueError) as exc:
        error = getattr(exc, "message", None) or f"温志无效：{exc}"
        db.rollback()
    except IntegrityError:
        db.rollback()
        error = "志序号冲突：本缸已有相同志序号，本次修改未保存（可能为并发重复提交）。"
    return render(
        request,
        "ferment.html",
        _page_context(request, db, user, pk, error),
        status_code=400,
    )
