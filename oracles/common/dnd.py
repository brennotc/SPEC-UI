"""Arrastar e soltar (AD-H2): mecânica do gesto, sem opinião sobre as regras do app.

Há duas formas legítimas de implementar DnD (eventos de ponteiro/CDK e `draggable` nativo do HTML5).
O driver tenta, na ordem, (1) o mouse real com passos intermediários, que dispara os dois tipos de
evento no Chromium, e (2) `drag_to`; guarda a estratégia que FUNCIONOU num movimento permitido e a
reutiliza nos testes das movimentações proibidas (assim "o card não moveu" não é confundido com
"o gesto não funciona")."""

import logging
from collections.abc import Callable

from playwright.sync_api import Locator, Page

from oracles.common.geometry import box

logger = logging.getLogger(__name__)
STRATEGIES = ("mouse", "drag_to")


class DndDriver:
    def __init__(self, page: Page) -> None:
        self.page = page
        self.strategy: str | None = None  # a que funcionou num movimento permitido

    # ------------------------------------------------------------------ gestos

    def _mouse(self, src: Locator, to: tuple[float, float]) -> None:
        b = box(src)
        if b is None:
            raise ValueError("origem do arrasto invisível")
        mouse = self.page.mouse
        mouse.move(b.cx, b.cy)
        mouse.down()
        mouse.move(b.cx + 8, b.cy + 8, steps=4)
        mouse.move(to[0], to[1], steps=20)
        self.page.wait_for_timeout(60)
        mouse.up()

    def _drag_to(self, src: Locator, to: tuple[float, float]) -> None:
        src.drag_to(self.page.locator("html"), target_position={"x": to[0], "y": to[1]})

    def _run(self, strategy: str, src: Locator, to: tuple[float, float]) -> None:
        (self._mouse if strategy == "mouse" else self._drag_to)(src, to)

    # ------------------------------------------------------------------ API

    def drag(self, src: Locator, to: tuple[float, float]) -> bool:
        """Arrasta com a estratégia já validada (a primeira, se ainda não houve validação)."""
        try:
            self._run(self.strategy or STRATEGIES[0], src, to)
            self.page.wait_for_timeout(450)  # o app pode animar/voltar o card ("snap back")
            return True
        except Exception:  # noqa: BLE001
            return False

    def move_until(self, src: Locator, to: tuple[float, float], moved: Callable[[], bool]) -> bool:
        """Arrasta tentando cada estratégia até `moved()` ser verdadeiro; grava a que funcionou."""
        order = sorted(STRATEGIES, key=lambda s: s != self.strategy)  # a conhecida primeiro
        for strategy in order:
            try:
                self._run(strategy, src, to)
            except Exception:
                logger.debug("estratégia de DnD %s falhou", strategy, exc_info=True)
                continue
            self.page.wait_for_timeout(450)
            if moved():
                self.strategy = strategy
                return True
        return False
