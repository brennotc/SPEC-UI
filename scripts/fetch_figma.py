#!/usr/bin/env python
"""Busca UMA VEZ os frames do Figma e grava a resposta bruta em references/figma/nodes.raw.json.

O plano Starter (gratuito) do Figma limita endpoints Tier 1 como este a ~6 requisições por mês.
Por isso:
  - é UMA requisição para os 3 frames (GET /v1/files/:key/nodes?ids=a,b,c);
  - o pipeline NUNCA chama a API: ele só lê o JSON local (nodes.raw.json / blocks.json);
  - se o arquivo de saída já existe, recusa sem --force; também recusa quando CI está definido;
  - use --dry-run para conferir a URL e os ids antes de gastar uma das chamadas.

Lê FIGMA_TOKEN e FIGMA_FILE_KEY do .env. Os node ids ficam em benchmarks/tasks/figma_frames.yaml
(na URL do Figma, `node-id=12-345` vira "12:345").

Depois de gravar, deriva references/figma/blocks.json OFFLINE (reexecutável com `specui figma-derive`).
"""

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import yaml

from specui.config import load_env
from specui.metrics.reference import derive_all

API_URL = "https://api.figma.com/v1/files/{key}/nodes?ids={ids}"
PLACEHOLDERS = (None, "", "TODO")
NODE_ID = re.compile(r"^\d+:\d+$")  # na URL aparece 'node-id=9-46'; na API é '9:46'


def load_frames(path: Path) -> dict[str, dict]:
    with open(path, encoding="utf-8") as f:
        return (yaml.safe_load(f) or {}).get("frames", {})


def build_url(file_key: str, node_ids: list[str]) -> str:
    ids = ",".join(urllib.parse.quote(node_id, safe=":") for node_id in node_ids)
    return API_URL.format(key=urllib.parse.quote(file_key, safe=""), ids=ids)


def fetch(url: str, token: str, timeout: int = 60) -> bytes:
    request = urllib.request.Request(url, headers={"X-Figma-Token": token})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Busca os frames do Figma (UMA requisição).")
    parser.add_argument("--frames", type=Path, default=REPO / "benchmarks" / "tasks" / "figma_frames.yaml")
    parser.add_argument("--out", type=Path, default=REPO / "references" / "figma" / "nodes.raw.json")
    parser.add_argument("--force", action="store_true", help="sobrescreve nodes.raw.json (gasta outra chamada)")
    parser.add_argument("--dry-run", action="store_true", help="mostra a URL e sai, sem requisição")
    args = parser.parse_args(argv)

    load_env(REPO)
    frames = load_frames(args.frames)
    pending = [t for t, spec in frames.items() if spec.get("node_id") in PLACEHOLDERS]
    if pending:
        print(f"ERRO: node_id pendente (TODO) em {args.frames.name}: {', '.join(pending)}", file=sys.stderr)
        return 2
    node_ids = [spec["node_id"] for spec in frames.values()]
    malformed = [f"{t}: {spec['node_id']!r}" for t, spec in frames.items() if not NODE_ID.match(str(spec['node_id']))]
    if malformed:
        print("ERRO: node_id fora do formato '9:46' (troque o '-' da URL por ':' e tire o '&t=...'): " + "; ".join(malformed), file=sys.stderr)
        return 2
    file_key = os.environ.get("FIGMA_FILE_KEY", "").strip()
    token = os.environ.get("FIGMA_TOKEN", "").strip()
    if not file_key:
        print("ERRO: defina FIGMA_FILE_KEY no .env", file=sys.stderr)
        return 2
    url = build_url(file_key, node_ids)

    if args.dry_run:
        print(f"GET {url}\n(nenhuma requisição feita; X-Figma-Token {'definido' if token else 'AUSENTE'})")
        return 0
    if os.environ.get("CI") and not args.force:
        print("ERRO: recusado em CI (a cota do plano Starter é de ~6 chamadas/mês).", file=sys.stderr)
        return 1
    if args.out.exists() and not args.force:
        print(f"ERRO: {args.out} já existe; use --force para gastar outra chamada.", file=sys.stderr)
        return 1
    if not token:
        print("ERRO: defina FIGMA_TOKEN no .env", file=sys.stderr)
        return 2

    try:
        body = fetch(url, token)
    except urllib.error.HTTPError as exc:
        hint = " (limite do plano Starter atingido?)" if exc.code == 429 else ""
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        print(f"ERRO: a API do Figma respondeu {exc.code}{hint}: {detail}", file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        print(f"ERRO de rede: {exc.reason}", file=sys.stderr)
        return 1

    payload = json.loads(body)
    missing = [n for n in node_ids if not (payload.get("nodes") or {}).get(n)]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    # Só a chave `nodes` é gravada: o resto da resposta (thumbnailUrl pré-assinada da AWS, nome e papel no arquivo,
    # lastModified) é metadado do arquivo do Figma, não dado do experimento, e não deve entrar no git.
    kept = json.dumps({"nodes": payload.get("nodes") or {}}, ensure_ascii=False, indent=1).encode("utf-8")
    args.out.write_bytes(kept)
    meta = {
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "node_ids": node_ids,
        "file_key_sha256_12": hashlib.sha256(file_key.encode()).hexdigest()[:12],
        "kept_keys": ["nodes"],
        "bytes": len(kept),
    }
    (args.out.parent / "nodes.meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8", newline="\n")
    print(f"OK: {args.out} ({len(kept)} bytes; só a chave 'nodes' da resposta)")
    if missing:
        print(f"AVISO: nós ausentes na resposta: {missing} (confira os ids; a resposta foi salva)", file=sys.stderr)
        return 1

    try:
        derived = derive_all(args.frames, args.out, args.out.parent / "blocks.json", args.frames.parent)
    except Exception as exc:  # noqa: BLE001 - a resposta bruta já está salva; a derivação é reexecutável
        print(f"AVISO: derivação dos blocos falhou ({exc}). Corrija e rode `specui figma-derive`.", file=sys.stderr)
        return 1
    summary = ", ".join(f"{task_id} ({len(entry['blocks'])} blocos)" for task_id, entry in derived.items())
    print("blocks.json: " + summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
