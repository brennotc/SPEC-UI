"""Harness do scaffold Angular: injeta os arquivos do modelo, faz o build e limpa.

Fluxo por execução (EXEC@1: uma única tentativa, sem rodada de correção):
  prepare_run_dir -> inject -> build -> (servir dist/app e renderizar) -> collect -> cleanup

`node_modules` é instalado uma vez em <workspace>/shared (npm ci) e ligado a cada diretório de
execução por junction (Windows) ou symlink. O cache do Angular (<workspace>/.angular-cache) também
é compartilhado, via `cli.cache.path` do angular.json.
"""

import hashlib
import json
import logging
import os
import re
import shutil
import signal
import subprocess
import time
from pathlib import Path

from pydantic import BaseModel, Field

from specui.codegen.parser import GeneratedBundle
from specui.llm.base import ConfigurationError
from specui.models import ScaffoldInfo

logger = logging.getLogger(__name__)

_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_ERROR_LINE = re.compile(r"\[ERROR\]\s*(?P<msg>.+)")
_GENERIC_ERROR = re.compile(r"^(?:Error:|error TS\d+|TypeError:|SyntaxError:)")
_RUN_ID = re.compile(r"^[A-Za-z0-9_.-]+$")
_COPY_IGNORE = shutil.ignore_patterns("node_modules", "dist", ".angular", "out-tsc", ".angular-cache")
_IGNORED_DIRS = {"node_modules", "dist", ".angular", "out-tsc", ".angular-cache"}
# Pacotes de infraestrutura: instalados, mas não faz sentido anunciá-los ao modelo.
_HIDDEN_PACKAGES = {"tslib", "@angular/compiler", "zone.js"}
_VERSION_PIN = re.compile(r"^\d+\.\d+\.\d+(?:[-+][\w.]+)?$")
MAX_ERROR_MESSAGES = 30


class BuildResult(BaseModel):
    ok: bool
    timed_out: bool = False
    time_s: float
    return_code: int | None = None
    stdout_path: str
    stderr_path: str
    error_messages: list[str] = Field(default_factory=list)
    dist_dir: str | None = None  # <run_dir>/dist/app quando ok


def _normalized(data: bytes) -> bytes:
    """Fim de linha LF: o hash não muda com o autocrlf do Git no Windows."""
    return data.replace(b"\r\n", b"\n")


def extract_error_messages(text: str, limit: int = MAX_ERROR_MESSAGES) -> list[str]:
    """Mensagens de erro do `ng build` (sem cores), sem repetição, na ordem de aparição."""
    clean = _ANSI.sub("", text)
    messages: list[str] = []
    for line in clean.splitlines():
        line = line.strip()
        m = _ERROR_LINE.search(line)
        msg = m.group("msg").strip() if m else (line if _GENERIC_ERROR.match(line) else None)
        if msg and msg not in messages:
            messages.append(msg)
        if len(messages) >= limit:
            break
    return messages


def make_dir_link(link: Path, target: Path) -> None:
    """Junction no Windows (não exige privilégio), symlink nos demais sistemas."""
    if os.name == "nt":
        proc = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, text=True, check=False
        )
        if proc.returncode != 0 or not link.exists():
            raise OSError(f"falha ao criar junction {link} -> {target}: {proc.stdout}{proc.stderr}")
    else:
        os.symlink(target, link, target_is_directory=True)


def remove_dir_link(link: Path) -> None:
    """Remove só o link, sem tocar no conteúdo do destino."""
    if link.is_symlink() or (os.name == "nt" and os.path.isjunction(link)):
        os.rmdir(link) if os.name == "nt" else os.unlink(link)


def _kill_tree(proc: subprocess.Popen) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, check=False)
    else:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()


class ScaffoldHarness:
    def __init__(
        self,
        scaffold_dir: str | Path,
        workspace_dir: str | Path,
        build_timeout_s: int = 180,
        configuration: str = "development",
    ) -> None:
        self.scaffold_dir = Path(scaffold_dir).resolve()
        self.workspace_dir = Path(workspace_dir).expanduser().resolve()
        self.build_timeout_s = build_timeout_s
        self.configuration = configuration
        if not (self.scaffold_dir / "package.json").is_file():
            raise ConfigurationError(f"scaffold não encontrado em {self.scaffold_dir}")

    # ------------------------------------------------------------------ informações

    def info(self) -> ScaffoldInfo:
        pkg = json.loads((self.scaffold_dir / "package.json").read_text(encoding="utf-8"))
        deps: dict[str, str] = dict(pkg.get("dependencies", {}))
        if "tailwindcss" in pkg.get("devDependencies", {}):
            deps["tailwindcss"] = pkg["devDependencies"]["tailwindcss"]
        unpinned = [n for n, v in {**deps, **pkg.get("devDependencies", {})}.items() if not _VERSION_PIN.match(v)]
        if unpinned:
            raise ConfigurationError(f"scaffold com versões não fixadas (use versão exata): {unpinned}")
        lock = self.scaffold_dir / "package-lock.json"
        if not lock.is_file():
            raise ConfigurationError("package-lock.json ausente no scaffold (deve estar versionado)")
        version_file = self.scaffold_dir / "SCAFFOLD_VERSION"
        return ScaffoldInfo(
            version=version_file.read_text(encoding="utf-8").strip() if version_file.is_file() else "0",
            lock_sha256=hashlib.sha256(_normalized(lock.read_bytes())).hexdigest(),
            tree_sha256=self._tree_sha256(),
            angular_version=deps["@angular/core"],
            packages={n: v for n, v in sorted(deps.items()) if n not in _HIDDEN_PACKAGES},
        )

    def _tree_sha256(self) -> str:
        digest = hashlib.sha256()
        for path in sorted(self.scaffold_dir.rglob("*")):
            rel = path.relative_to(self.scaffold_dir)
            if path.is_dir() or _IGNORED_DIRS & set(rel.parts):
                continue
            digest.update(rel.as_posix().encode("utf-8") + b"\0")
            digest.update(_normalized(path.read_bytes()) + b"\0")
        return digest.hexdigest()

    # ------------------------------------------------------------------ workspace

    @staticmethod
    def _tool(name: str) -> str:
        found = shutil.which(name)
        if not found:
            raise ConfigurationError(f"'{name}' não encontrado no PATH (instale Node 22; veja .nvmrc)")
        return found

    def ensure_workspace(self, force: bool = False) -> Path:
        """Instala `node_modules` uma vez em <workspace>/shared (npm ci). Devolve o node_modules."""
        shared = self.workspace_dir / "shared"
        modules, marker = shared / "node_modules", shared / ".specui-ok"
        lock_sha = self.info().lock_sha256
        if not force and modules.is_dir() and marker.is_file() and marker.read_text().strip() == lock_sha:
            return modules
        shared.mkdir(parents=True, exist_ok=True)
        shutil.rmtree(modules, ignore_errors=True)
        marker.unlink(missing_ok=True)
        for name in ("package.json", "package-lock.json"):
            shutil.copyfile(self.scaffold_dir / name, shared / name)
        logger.info("npm ci em %s (primeira vez; leva alguns minutos)", shared)
        proc = subprocess.run(
            [self._tool("npm"), "ci", "--no-fund", "--no-audit"],
            cwd=shared, capture_output=True, text=True, timeout=1800, check=False,
        )
        if proc.returncode != 0:
            tail = "\n".join((proc.stdout + proc.stderr).strip().splitlines()[-15:])
            raise ConfigurationError(f"npm ci falhou:\n{tail}")
        marker.write_text(lock_sha, encoding="utf-8")
        return modules

    def prepare_run_dir(self, run_id: str) -> Path:
        """Copia o scaffold (sem node_modules) para <workspace>/<run_id> e liga o node_modules."""
        if not _RUN_ID.match(run_id):
            raise ValueError(f"run_id inválido para diretório: {run_id!r}")
        modules = self.ensure_workspace()
        run_dir = self.workspace_dir / run_id
        if run_dir.exists():
            self.cleanup(run_dir)
        shutil.copytree(self.scaffold_dir, run_dir, ignore=_COPY_IGNORE)
        make_dir_link(run_dir / "node_modules", modules)
        return run_dir

    # ------------------------------------------------------------------ injeção e build

    def inject(self, bundle: GeneratedBundle, run_dir: Path) -> list[str]:
        """Grava os arquivos aceitos. `src/styles.css` do modelo vira `src/app.styles.css`,
        importado pelo styles.css fixo depois do Tailwind (o modelo não consegue removê-lo)."""
        run_dir = Path(run_dir).resolve()
        allowed_root = (run_dir / "src").resolve()
        written: list[str] = []
        for f in bundle.files:
            rel = "src/app.styles.css" if f.path == "src/styles.css" else f.path
            dest = (run_dir / rel).resolve()
            if allowed_root not in dest.parents:  # defesa em profundidade (o parser já valida)
                raise ValueError(f"caminho fora de src/: {f.path}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(f.content, encoding="utf-8", newline="\n")
            written.append(rel)
        return written

    def build(self, run_dir: Path) -> BuildResult:
        run_dir = Path(run_dir)
        ng = run_dir / "node_modules" / "@angular" / "cli" / "bin" / "ng.js"
        if not ng.is_file():
            raise ConfigurationError(f"Angular CLI não encontrado em {ng} (node_modules ligado?)")
        logs = self.workspace_dir / "_logs"
        logs.mkdir(parents=True, exist_ok=True)
        out_path, err_path = logs / f"{run_dir.name}.stdout.txt", logs / f"{run_dir.name}.stderr.txt"
        env = {**os.environ, "NG_CLI_ANALYTICS": "false", "CI": "true", "NO_COLOR": "1", "FORCE_COLOR": "0"}
        cmd = [self._tool("node"), str(ng), "build", "--configuration", self.configuration, "--base-href", "./"]
        popen_kwargs: dict = (
            {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
        )

        started, timed_out, rc = time.monotonic(), False, None
        with open(out_path, "wb") as fo, open(err_path, "wb") as fe:
            proc = subprocess.Popen(cmd, cwd=run_dir, stdout=fo, stderr=fe, env=env, **popen_kwargs)
            try:
                rc = proc.wait(timeout=self.build_timeout_s)
            except subprocess.TimeoutExpired:
                timed_out = True
                _kill_tree(proc)
        elapsed = round(time.monotonic() - started, 2)

        dist = run_dir / "dist" / "app"
        ok = (not timed_out) and rc == 0 and (dist / "index.html").is_file()
        messages: list[str] = []
        if timed_out:
            messages = [f"timeout: build excedeu {self.build_timeout_s}s"]
        elif not ok:
            text = out_path.read_text(encoding="utf-8", errors="replace") + "\n" + err_path.read_text(
                encoding="utf-8", errors="replace"
            )
            messages = extract_error_messages(text)
            if not messages:
                tail = [ln.strip() for ln in _ANSI.sub("", text).splitlines() if ln.strip()]
                messages = tail[-10:] or [f"build terminou com código {rc} sem mensagem"]
        return BuildResult(
            ok=ok, timed_out=timed_out, time_s=elapsed, return_code=rc,
            stdout_path=str(out_path), stderr_path=str(err_path),
            error_messages=messages, dist_dir=str(dist) if ok else None,
        )

    # ------------------------------------------------------------------ coleta e limpeza

    def collect(self, run_dir: Path, dest_dir: Path, build: BuildResult, keep_dist: bool = True) -> dict[str, str]:
        """Copia o que interessa (fontes gerados, dist e logs) para o diretório de resultados."""
        run_dir, dest_dir = Path(run_dir), Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        paths: dict[str, str] = {}
        generated = dest_dir / "generated"
        shutil.copytree(run_dir / "src" / "app", generated / "src" / "app", dirs_exist_ok=True)
        extra = run_dir / "src" / "app.styles.css"
        if extra.is_file():
            shutil.copyfile(extra, generated / "src" / "app.styles.css")
        paths["generated_dir"] = str(generated)
        if keep_dist and build.dist_dir and Path(build.dist_dir).is_dir():
            shutil.copytree(build.dist_dir, dest_dir / "dist", dirs_exist_ok=True)
            paths["dist_dir"] = str(dest_dir / "dist")
        for key, src in (("build_stdout", build.stdout_path), ("build_stderr", build.stderr_path)):
            target = dest_dir / f"{key.replace('_', '.')}.txt"
            shutil.copyfile(src, target)
            paths[key] = str(target)
        return paths

    def cleanup(self, run_dir: Path) -> None:
        """Remove o diretório de execução SEM seguir a junction do node_modules."""
        run_dir = Path(run_dir).resolve()
        if self.workspace_dir not in run_dir.parents:
            raise ValueError(f"recusando apagar fora do workspace: {run_dir}")
        remove_dir_link(run_dir / "node_modules")
        shutil.rmtree(run_dir, ignore_errors=True)
        for suffix in ("stdout", "stderr"):  # os logs do build já foram copiados por `collect`: um par por célula acumulava
            (self.workspace_dir / "_logs" / f"{run_dir.name}.{suffix}.txt").unlink(missing_ok=True)

    def verify_pristine(self) -> BuildResult:
        """Constrói o scaffold vazio (usado por `specui scaffold-check`)."""
        run_dir = self.prepare_run_dir("pristine-check")
        try:
            return self.build(run_dir)
        finally:
            self.cleanup(run_dir)

