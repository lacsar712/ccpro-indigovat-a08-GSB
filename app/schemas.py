from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class WorkshopIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    region: str = Field(min_length=1, max_length=80)
    notes: str = ""


class VatIn(BaseModel):
    workshop_id: int
    code: str = Field(min_length=1, max_length=40)
    dyeType: str = Field(min_length=1, max_length=80)
    volumeL: Decimal
    status: str = "idle"


class DipLotIn(BaseModel):
    vat_id: int
    dippedAt: datetime
    clothMeters: Decimal
    redoxMv: Optional[Decimal] = None


class FermentLogIn(BaseModel):
    vat_id: int
    seq: int = Field(gt=0)
    tempC: Decimal = Field(ge=Decimal("20"), le=Decimal("42"))
    ph: Decimal = Field(ge=Decimal("8"), le=Decimal("12"))
    sampledAt: datetime
    inspector: str = Field(min_length=1, max_length=80)


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    detail: str
