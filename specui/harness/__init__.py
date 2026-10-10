"""Harness de execução: scaffold Angular, build, servidor estático e navegador."""

from specui.harness.browser import BrowserSession, RenderArtifacts
from specui.harness.scaffold import BuildResult, ScaffoldHarness
from specui.harness.server import StaticServer

__all__ = ["BrowserSession", "BuildResult", "RenderArtifacts", "ScaffoldHarness", "StaticServer"]
