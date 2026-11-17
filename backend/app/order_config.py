"""Loads and validates order_config.json (products, tables, provisional statuses).

Business vocabulary lives in that file, not in code or in the database schema, so
renaming a status or re-measuring a table distance never needs a migration.
"""
import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, model_validator

from .config import settings


class Product(BaseModel):
    code: str
    name: str


class Table(BaseModel):
    number: int
    robot_destination: str
    distance_m: float


class OrderConfig(BaseModel):
    products: list[Product]
    tables: list[Table]
    statuses: list[str]
    initial_status: str

    @model_validator(mode="after")
    def _check(self):
        if not self.products or not self.tables or not self.statuses:
            raise ValueError("products, tables and statuses must not be empty")
        if self.initial_status not in self.statuses:
            raise ValueError(f"initial_status {self.initial_status!r} is not in statuses")
        for name, values in (("product codes", [p.code for p in self.products]),
                             ("table numbers", [t.number for t in self.tables]),
                             ("statuses", self.statuses)):
            if len(values) != len(set(values)):
                raise ValueError(f"duplicate {name}")
        return self

    def product(self, code: str) -> Product | None:
        return next((p for p in self.products if p.code == code), None)

    def table(self, number: int) -> Table | None:
        return next((t for t in self.tables if t.number == number), None)


def load_order_config(path: str | Path) -> OrderConfig:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    data = {k: v for k, v in data.items() if not k.startswith("_")}   # drop _comments
    return OrderConfig.model_validate(data)


@lru_cache
def get_order_config() -> OrderConfig:
    return load_order_config(settings.order_config_file)
