"""Журнал действий аналитика с защитой от подмены (хеш-цепочка, как в блокчейн-журналах).

Каждая запись хранит SHA-256 от своего содержимого и хеша предыдущей записи. Если кто-то изменит или удалит
запись задним числом, проверка цепочки (/api/audit/verify) покажет первую испорченную запись.

Хранение: PostgreSQL (таблица audit_log) или, в локальном режиме, output/audit_log.jsonl."""
import hashlib
import json
import threading
from datetime import datetime, timezone

from . import store

GENESIS = "0" * 64
_lock = threading.Lock()
LOG_FILE = store.ROOT / "output" / "audit_log.jsonl"


def _digest(rec: dict) -> str:
    body = json.dumps({k: rec[k] for k in ("ts", "actor", "action", "target", "details", "prev_hash")},
                      ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _ensure_pg():
    store.q("""CREATE TABLE IF NOT EXISTS audit_log (
                 id BIGSERIAL PRIMARY KEY, ts TEXT, actor TEXT, action TEXT, target TEXT,
                 details TEXT, prev_hash TEXT, hash TEXT)""")


def _all() -> list[dict]:
    if store.backend() == "postgres":
        _ensure_pg()
        return store.q("SELECT id, ts, actor, action, target, details, prev_hash, hash FROM audit_log ORDER BY id")
    if not LOG_FILE.exists():
        return []
    return [json.loads(line) for line in LOG_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]


def record(actor: str | None, action: str, target: str = "", details: dict | None = None) -> dict:
    actor = (actor or "аноним").strip()[:64] or "аноним"
    with _lock:
        rows = _all()
        prev = rows[-1]["hash"] if rows else GENESIS
        rec = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "actor": actor, "action": action,
               "target": str(target)[:64], "details": json.dumps(details or {}, ensure_ascii=False)[:1000],
               "prev_hash": prev}
        rec["hash"] = _digest(rec)
        if store.backend() == "postgres":
            store.q("""INSERT INTO audit_log (ts, actor, action, target, details, prev_hash, hash)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                    (rec["ts"], rec["actor"], rec["action"], rec["target"], rec["details"], rec["prev_hash"], rec["hash"]))
        else:
            rec["id"] = len(rows) + 1
            LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(LOG_FILE, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return rec


def recent(n: int = 100) -> list[dict]:
    return list(reversed(_all()[-n:]))


def verify() -> dict:
    """Пересчитывает всю цепочку. ok=False и номер первой испорченной записи, если журнал правили."""
    rows = _all()
    prev = GENESIS
    for i, r in enumerate(rows, 1):
        if r["prev_hash"] != prev:
            return {"ok": False, "records": len(rows), "broken_at": i, "reason": "нарушена связь с предыдущей записью"}
        if _digest(r) != r["hash"]:
            return {"ok": False, "records": len(rows), "broken_at": i, "reason": "содержимое записи изменено"}
        prev = r["hash"]
    return {"ok": True, "records": len(rows), "last_hash": prev}
