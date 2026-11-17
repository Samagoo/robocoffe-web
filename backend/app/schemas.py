"""Pydantic request/response models for the REST API."""
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .order_config import get_order_config


class OrderCreate(BaseModel):
    """What the customer page sends. Products and tables are checked against order_config.json."""
    product_code: str = Field(min_length=1, max_length=8, examples=["C1"])
    table_number: int = Field(examples=[1])
    customer_name: str | None = Field(default=None, max_length=80)
    notes: str | None = Field(default=None, max_length=200)

    @field_validator("product_code")
    @classmethod
    def _known_product(cls, v: str) -> str:
        v = v.strip().upper()
        if get_order_config().product(v) is None:
            raise ValueError(f"unknown product {v!r}")
        return v

    @field_validator("table_number")
    @classmethod
    def _known_table(cls, v: int) -> int:
        if get_order_config().table(v) is None:
            raise ValueError(f"unknown table {v}")
        return v

    @field_validator("customer_name", "notes")
    @classmethod
    def _blank_to_none(cls, v: str | None) -> str | None:
        return v.strip() or None if v is not None else None


class ScaleReadingIn(BaseModel):
    """One 'PESO:<g>' line, parsed and stamped by scale_bridge."""
    model_config = ConfigDict(allow_inf_nan=False)

    raw: str = Field(max_length=200)
    grams: float = Field(ge=-10_000, le=10_000)     # sanity only; no filtering, no decisions here
    received_at: datetime                            # PC time at COM reception

    @field_validator("raw")
    @classmethod
    def _peso_only(cls, v: str) -> str:
        if not v.strip().startswith("PESO:"):
            raise ValueError("only PESO:<g> lines are accepted")
        return v.strip()

    @field_validator("received_at")
    @classmethod
    def _aware_and_not_future(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.utcoffset() is None:
            raise ValueError("received_at must include a UTC offset")
        if v - datetime.now(timezone.utc) > timedelta(seconds=60):
            raise ValueError("received_at is in the future (check the PC clock)")
        return v


class ScaleBatchIn(BaseModel):
    source: str = Field(min_length=1, max_length=60)      # COM port, e.g. "COM5"
    readings: list[ScaleReadingIn] = Field(max_length=1000)


class ScaleReadingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    received_at: datetime
    ingested_at: datetime
    grams: float
    raw: str | None
    source: str


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    folio: str
    product_code: str
    table_number: int
    distance_m: float
    customer_name: str | None
    notes: str | None
    status: str
    incident: str | None
    load_weight_g: float | None
    delivery_weight_g: float | None
    robot_msg_id: int | None
    created_at: datetime
    updated_at: datetime
    ready_at: datetime | None
    dispatched_at: datetime | None
    arrived_at: datetime | None
    delivered_at: datetime | None
    returned_at: datetime | None
