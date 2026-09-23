"""Псевдонимизация для внешней LLM: модель никогда не видит реальные идентификаторы клиентов.

Перед отправкой в LLM каждый gid (18–20 цифр) заменяется на псевдоним вида К-001. Модель рассуждает и вызывает
инструменты псевдонимами; перед выполнением инструмента псевдонимы переводятся обратно, а в итоговом ответе
аналитик снова видит реальные gid. Таблица соответствия живёт только в памяти одного запроса."""
import re

GID_RE = re.compile(r"\b\d{15,20}\b")
TOKEN_RE = re.compile(r"\bК-\d{3,5}\b")


class Pseudonymizer:
    def __init__(self):
        self.fwd: dict[str, str] = {}
        self.back: dict[str, str] = {}

    def token(self, gid: str) -> str:
        if gid not in self.fwd:
            t = f"К-{len(self.fwd) + 1:03d}"
            self.fwd[gid], self.back[t] = t, gid
        return self.fwd[gid]

    def mask(self, text: str) -> str:
        """Реальные gid → псевдонимы (для всего, что уходит в LLM)."""
        return GID_RE.sub(lambda m: self.token(m.group(0)), text)

    def unmask(self, text: str) -> str:
        """Псевдонимы → реальные gid (для ответа аналитику)."""
        return TOKEN_RE.sub(lambda m: self.back.get(m.group(0), m.group(0)), text or "")

    def unmask_args(self, obj):
        """Аргументы вызова инструмента от модели: псевдонимы → gid. Неизвестный псевдоним оставляем как есть —
        инструмент вернёт «не найден», модель не сможет «угадать» чужой gid."""
        if isinstance(obj, str):
            return self.unmask(obj)
        if isinstance(obj, list):
            return [self.unmask_args(x) for x in obj]
        if isinstance(obj, dict):
            return {k: self.unmask_args(v) for k, v in obj.items()}
        return obj
