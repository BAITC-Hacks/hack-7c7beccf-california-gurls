"""Живая проверка AI-ассистента Tamyr и псевдонимизации. Запуск из папки проекта:
    python scripts/check_ai.py
Нужен .env с OPENAI_API_KEY и выполненный `python run.py`."""
import os, sys, json
sys.path.insert(0, ".")
os.environ.setdefault("STORAGE", "local")
from api import assistant, privacy

sent = []
orig = assistant._call
def spy(client, **kw):                      # перехватываем всё, что уходит в OpenAI
    sent.append(json.dumps(kw["messages"], ensure_ascii=False))
    return orig(client, **kw)
assistant._call = spy

q = "Кто собирает деньги с seed 100000000343175100, 100000004269433100, 100000008418835100?"
r = assistant.ask([{"role": "user", "content": q}])
print("ОТВЕТ:\n", r["answer"], "\n")
print("Инструменты:", " → ".join(t["tool"] for t in r["trace"]))
leak = any(privacy.GID_RE.search(m) for m in sent)
print("Реальные gid ушли в OpenAI:", "ДА — ПРОБЛЕМА" if leak else "нет (только псевдонимы К-…)")
print("Псевдонимов в запросе:", r.get("pseudonymized"))
