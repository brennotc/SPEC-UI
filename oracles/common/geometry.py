"""Caixas na tela e relações espaciais entre elementos."""

from dataclasses import dataclass

from playwright.sync_api import Locator


@dataclass(frozen=True)
class Box:
    x: float
    y: float
    w: float
    h: float

    @property
    def x1(self) -> float:
        return self.x + self.w

    @property
    def y1(self) -> float:
        return self.y + self.h

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    @property
    def area(self) -> float:
        return self.w * self.h

    def overlaps_vertically(self, other: "Box", min_fraction: float = 0.4) -> bool:
        """Estão na mesma linha (sobreposição vertical de ao menos `min_fraction` do menor)."""
        overlap = min(self.y1, other.y1) - max(self.y, other.y)
        return overlap >= min_fraction * min(self.h, other.h)

    def overlaps_horizontally(self, other: "Box", min_fraction: float = 0.4) -> bool:
        overlap = min(self.x1, other.x1) - max(self.x, other.x)
        return overlap >= min_fraction * min(self.w, other.w)

    def contains_point(self, x: float, y: float) -> bool:
        return self.x <= x <= self.x1 and self.y <= y <= self.y1


def box(locator: Locator | None) -> Box | None:
    """Caixa do elemento em px do viewport; None se ausente, invisível ou sem tamanho."""
    if locator is None:
        return None
    try:
        raw = locator.bounding_box(timeout=1500)
    except Exception:  # noqa: BLE001 - desapareceu no meio
        return None
    if not raw or raw["width"] <= 0 or raw["height"] <= 0:
        return None
    return Box(raw["x"], raw["y"], raw["width"], raw["height"])


def first_visible(locator: Locator, limit: int = 30) -> Locator | None:
    """Primeiro elemento visível (sem esperar) entre os que casam com o locator."""
    for i in range(min(locator.count(), limit)):
        node = locator.nth(i)
        if node.is_visible():
            return node
    return None


def visible_all(locator: Locator, limit: int = 60) -> list[Locator]:
    return [locator.nth(i) for i in range(min(locator.count(), limit)) if locator.nth(i).is_visible()]


def sorted_by_x(locators: list[Locator]) -> list[Locator]:
    pairs = [(box(loc), loc) for loc in locators]
    return [loc for b, loc in sorted((p for p in pairs if p[0]), key=lambda p: p[0].cx)]


def sorted_by_y(locators: list[Locator]) -> list[Locator]:
    pairs = [(box(loc), loc) for loc in locators]
    return [loc for b, loc in sorted((p for p in pairs if p[0]), key=lambda p: p[0].cy)]
