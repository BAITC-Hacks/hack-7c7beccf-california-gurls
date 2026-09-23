"""Отпечатки целостности (SHA-256): по каким данным, конфигу и коду получены выводы.
run.py пишет output/manifest.json; API сверяет текущие файлы с манифестом (/api/integrity)."""
import hashlib
import json
import platform
from datetime import datetime, timezone
from pathlib import Path


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_manifest(root: Path, data_dir: Path, out: Path, config: Path) -> dict:
    inputs = sorted(Path(data_dir).glob("*.parquet"))
    code = sorted((root / "pipeline").glob("*.py")) + [root / "run.py"]
    outputs = sorted(p for p in Path(out).glob("*.csv"))
    rel = lambda p: str(Path(p).resolve().relative_to(root.resolve()))
    m = {
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "python": platform.python_version(),
        "inputs": {rel(p): sha256(p) for p in inputs},
        "config": {rel(config): sha256(config)},
        "code": {rel(p): sha256(p) for p in code},
        "outputs": {rel(p): sha256(p) for p in outputs},
    }
    # общий отпечаток прогона — печатается в досье и справке
    m["run_fingerprint"] = hashlib.sha256(json.dumps(
        {k: m[k] for k in ("inputs", "config", "code", "outputs")}, sort_keys=True).encode()).hexdigest()
    return m


def verify(root: Path, manifest_path: Path) -> dict:
    if not manifest_path.exists():
        return {"ok": False, "reason": "манифест не найден — выполните python run.py", "changed": []}
    m = json.loads(manifest_path.read_text(encoding="utf-8"))
    changed, missing = [], []
    for group in ("inputs", "config", "code", "outputs"):
        for f, h in m[group].items():
            p = root / f
            if not p.exists():
                missing.append(f)
            elif sha256(p) != h:
                changed.append(f)
    return {"ok": not changed and not missing, "changed": changed, "missing": missing,
            "run_fingerprint": m["run_fingerprint"], "created_at": m["created_at"],
            "files_checked": sum(len(m[g]) for g in ("inputs", "config", "code", "outputs"))}
