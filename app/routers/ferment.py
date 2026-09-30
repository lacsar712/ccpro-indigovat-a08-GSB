"""靛蓝发酵温志专页：登记、更新温志（仅还原中可登记）。

温志齐套判定不在本路由，改可染色的判定统一走
``app.services.vat_rules.validate_vat_status_change``，与浸染电位门槛挂在同一处。
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.auth import get_current_user
from app.db import get_db
from app.models import FermentLog, Vat, Workshop
from app.routers.pages import STATUS_LABELS
from app.services.vat_rules import VatRuleError, validate_ferment_readings

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def render(request: Request, name: str, context: dict, status_code: int = 200):
    ctx = {k: v for k, v in context.items() if k != "request"}
    return templates.TemplateResponse(request, name, ctx, status_code=status_code)


def _fmt_dt_local(value: Optional[datetime]) -> str:
    if value is None:
        return ""
    return value.strftime("%Y-%m-%dT%H:%M")


def _log_payload(log: FermentLog) -> dict:
    return {
        "id": log.id,
        "seq": log.seq,
        "tempC": float(log.tempC),
        "ph": float(log.ph),
        "sampledAt": log.sampledAt.strftime("%Y-%m-%d %H:%M"),
        "sampledAtLocal": _fmt_dt_local(log.sampledAt),
        "inspector": log.inspector,
    }


def _vat_brief(vat: Vat) -> dict:
    return {
        "id": vat.id,
        "code": vat.code,
        "dyeType": vat.dyeType,
        "status": vat.status,
        "statusLabel": STATUS_LABELS.get(vat.status, vat.status),
        "workshopName": vat.workshop.name if vat.workshop else "",
        "fermentCount": len(vat.ferment_logs),
    }


def _ferment_context(
    request: Request,
    db: Session,
    user,
    selected_vat: Optional[int] = None,
    error: Optional[str] = None,
    edit_id: Optional[int] = None,
    form: Optional[dict] = None,
):
    vats = (
        db.query(Vat)
        .options(joinedload(Vat.workshop), joinedload(Vat.ferment_logs))
        .order_by(Vat.code)
        .all()
    )
    workshops = db.query(Workshop).order_by(Workshop.name).all()

    selected = None
    logs: list[FermentLog] = []
    edit_log = None
    if selected_vat is not None:
        selected = next((v for v in vats if v.id == selected_vat), None)
        if selected is not None:
            logs = sorted(selected.ferment_logs, key=lambda x: (x.sampledAt, x.id))
            if edit_id is not None:
                edit_log = next((l for l in logs if l.id == edit_id), None)

    return {
        "request": request,
        "user": user,
        "workshops": workshops,
        "vats": [_vat_brief(v) for v in vats],
        "selected": _vat_brief(selected) if selected else None,
        "logs": [_log_payload(l) for l in logs],
        "edit_log": _log_payload(edit_log) if edit_log else None,
        "error": error,
        "form": form or {},
        "status_labels": STATUS_LABELS,
        "active": "ferment",
    }


@router.get("/ferment", response_class=HTMLResponse)
async def ferment_page(
    request: Request,
    vat: Optional[int] = None,
    edit: Optional[int] = None,
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    return render(
        request,
        "ferment.html",
        _ferment_context(request, db, user, vat, edit_id=edit),
    )


def _parse_log_form(seq_s: str, temp_s: str, ph_s: str, sampled_s: str, inspector: str):
    """解析并共用校验温志表单；失败抛 ValueError/VatRuleError。"""
    inspector = inspector.strip()
    if not inspector:
        raise VatRuleError("巡检人不能为空。")
    try:
        seq = int(seq_s)
    except (TypeError, ValueError):
        raise VatRuleError("志序号须为整数。")
    if seq <= 0:
        raise VatRuleError("志序号须为正整数。")
    try:
        tempC = Decimal(temp_s)
        ph = Decimal(ph_s)
    except (InvalidOperation, ValueError):
        raise VatRuleError("液温与酸碱值须为数字。")
    try:
        sampled_at = datetime.fromisoformat(sampled_s)
    except (TypeError, ValueError):
        raise VatRuleError("采样时刻格式无效。")
    # 新建与更新共用读数区间校验
    validate_ferment_readings(tempC, ph)
    return seq, tempC, ph, sampled_at, inspector


@router.post("/ferment/vats/{pk}/logs", response_class=HTMLResponse)
async def ferment_create(
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

    raw = {"seq": seq, "tempC": tempC, "ph": ph, "sampledAt": sampledAt, "inspector": inspector}
    try:
        if vat.status != Vat.STATUS_REDUCING:
            raise VatRuleError("仅还原中的染缸可登记发酵温志。")
        seq_n, temp_n, ph_n, sampled_at, inspector_n = _parse_log_form(
            seq, tempC, ph, sampledAt, inspector
        )
        exists = (
            db.query(FermentLog.id)
            .filter(FermentLog.vat_id == pk, FermentLog.seq == seq_n)
            .first()
        )
        if exists:
            raise VatRuleError(f"本缸已有志序号 {seq_n}，同缸序号不可重复。")

        log = FermentLog(
            vat_id=pk,
            seq=seq_n,
            tempC=temp_n,
            ph=ph_n,
            sampledAt=sampled_at,
            inspector=inspector_n,
        )
        db.add(log)
        db.commit()
        return RedirectResponse(f"/ferment?vat={pk}", status_code=303)
    except VatRuleError as exc:
        db.rollback()
        error = exc.message
    except IntegrityError:
        # 同缸并发写入相同序号：唯一约束兜底，只许一笔落库
        db.rollback()
        error = "志序号冲突：该序号刚被另一笔登记占用，请更换序号后重试。"
    return render(
        request,
        "ferment.html",
        _ferment_context(request, db, user, pk, error=error, form=raw),
        status_code=400,
    )


@router.post("/ferment/logs/{log_id}", response_class=HTMLResponse)
async def ferment_update(
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

    raw = {"seq": seq, "tempC": tempC, "ph": ph, "sampledAt": sampledAt, "inspector": inspector}
    try:
        seq_n, temp_n, ph_n, sampled_at, inspector_n = _parse_log_form(
            seq, tempC, ph, sampledAt, inspector
        )
        clash = (
            db.query(FermentLog.id)
            .filter(
                FermentLog.vat_id == pk,
                FermentLog.seq == seq_n,
                FermentLog.id != log_id,
            )
            .first()
        )
        if clash:
            raise VatRuleError(f"本缸已有志序号 {seq_n}，同缸序号不可重复。")

        log.seq = seq_n
        log.tempC = temp_n
        log.ph = ph_n
        log.sampledAt = sampled_at
        log.inspector = inspector_n
        db.commit()
        return RedirectResponse(f"/ferment?vat={pk}", status_code=303)
    except VatRuleError as exc:
        db.rollback()
        error = exc.message
    except IntegrityError:
        db.rollback()
        error = "志序号冲突：该序号刚被另一笔登记占用，请更换序号后重试。"
    return render(
        request,
        "ferment.html",
        _ferment_context(request, db, user, pk, error=error, edit_id=log_id, form=raw),
        status_code=400,
    )
