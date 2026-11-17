"""Pydantic request/response models for the REST API."""
from datetime import datetime

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
