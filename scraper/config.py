"""Зареждане и проверка на products.yaml."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

CODE_RE = re.compile(r"/p/(\d+)")


class ConfigError(Exception):
    pass


@dataclass
class ProductConfig:
    code: str
    url: str
    category: str
    target_price: float | None = None
    name: str | None = None
    active: bool = True


@dataclass
class Settings:
    repeat_alerts_daily: bool = False
    notify_on_errors: bool = True
    request_delay: float = 2.0


@dataclass
class Config:
    settings: Settings
    products: list[ProductConfig] = field(default_factory=list)

    @property
    def active_products(self) -> list[ProductConfig]:
        return [p for p in self.products if p.active]


def extract_code(url: str) -> str | None:
    m = CODE_RE.search(url)
    return m.group(1) if m else None


def load_config(path: str | Path) -> Config:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"Файлът {path} не съществува.")

    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    s = raw.get("settings") or {}
    settings = Settings(
        repeat_alerts_daily=bool(s.get("repeat_alerts_daily", False)),
        notify_on_errors=bool(s.get("notify_on_errors", True)),
        request_delay=float(s.get("request_delay", 2)),
    )

    items = raw.get("products")
    if not isinstance(items, list) or not items:
        raise ConfigError("В products.yaml няма списък 'products'.")

    errors: list[str] = []
    products: list[ProductConfig] = []
    seen: dict[str, int] = {}

    for i, item in enumerate(items, start=1):
        where = f"продукт #{i}"
        if not isinstance(item, dict):
            errors.append(f"{where}: очаква се обект с url/category.")
            continue

        url = str(item.get("url") or "").strip()
        code = extract_code(url)
        if not url or not code:
            errors.append(f"{where}: липсва url или в него няма '/p/<код>' ({url or '—'}).")
            continue

        category = str(item.get("category") or "").strip()
        if not category:
            errors.append(f"{where} ({code}): липсва category.")
            continue

        target = item.get("target_price")
        if target is not None:
            try:
                target = float(target)
            except (TypeError, ValueError):
                errors.append(f"{where} ({code}): target_price трябва да е число, а е '{target}'.")
                continue
            if target <= 0:
                errors.append(f"{where} ({code}): target_price трябва да е > 0.")
                continue

        if code in seen:
            errors.append(f"{where}: кодът {code} вече е описан в продукт #{seen[code]}.")
            continue
        seen[code] = i

        products.append(
            ProductConfig(
                code=code,
                url=url,
                category=category,
                target_price=target,
                name=(str(item["name"]).strip() if item.get("name") else None),
                active=bool(item.get("active", True)),
            )
        )

    if errors:
        raise ConfigError("Грешки в products.yaml:\n  - " + "\n  - ".join(errors))

    return Config(settings=settings, products=products)
