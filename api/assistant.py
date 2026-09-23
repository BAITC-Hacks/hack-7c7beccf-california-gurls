"""AI-ассистент аналитика и карточка узла (OpenAI или NVIDIA API, function calling).
LLM НЕ участвует в расчёте ролей: она только вызывает аналитические функции и пересказывает их результат.
Работает только при наличии ключа выбранного провайдера; пайплайн и интерфейс без него работают полностью."""
import json
import os

from . import store, tools

# Любой OpenAI-совместимый провайдер: OpenAI или NVIDIA (build.nvidia.com), выбирается в .env
PROVIDERS = {
    "openai": {"base_url": None, "key_env": "OPENAI_API_KEY", "model": "gpt-4.1-mini"},
    "nvidia": {"base_url": "https://integrate.api.nvidia.com/v1", "key_env": "NVIDIA_API_KEY",
               "model": "meta/llama-3.3-70b-instruct"},
}
PROVIDER = os.getenv("LLM_PROVIDER", "openai").lower()
_P = PROVIDERS[PROVIDER]
MODEL = os.getenv("LLM_MODEL") or _P["model"]

SYSTEM = """Ты — помощник AML-аналитика банка. Работаешь с обезличенным графом переводов (июль 2026):
81 seed-клиент (выявлены правоохранителями) и их исходящие переводы на 4 колена, порог 5000 KZT.
Роли узлов: coordinator, distributor, consolidator, transit, terminal, boundary (4-е колено, исходящие
не выгружались), peripheral. Правила:
- Отвечай ТОЛЬКО на основе результатов инструментов. Не выдумывай узлы, суммы и связи.
- Всегда указывай gid узлов, на которые опираешься.
- Формулируй как гипотезы для проверки («признаки консолидации»), а не как утверждение о виновности.
- Учитывай ограничения: у seed входящие занижены; у узлов 4-го колена исходящие неизвестны.
- Отвечай по-русски, кратко и по делу."""

TOOLS_SPEC = [
    {"name": "get_node", "description": "Метрики, роль, обоснование и крупнейшие связи узла",
     "parameters": {"type": "object", "properties": {"gid": {"type": "string"}}, "required": ["gid"]}},
    {"name": "get_neighbors", "description": "Окрестность узла на 1–3 шага",
     "parameters": {"type": "object", "properties": {"gid": {"type": "string"},
                    "direction": {"type": "string", "enum": ["in", "out", "both"]},
                    "hops": {"type": "integer"}}, "required": ["gid"]}},
    {"name": "common_receivers", "description": "Кто получает деньги (напрямую или по цепочке) сразу от нескольких узлов — поиск общих сборщиков",
     "parameters": {"type": "object", "properties": {"gids": {"type": "array", "items": {"type": "string"}},
                    "max_hops": {"type": "integer"}}, "required": ["gids"]}},
    {"name": "trace_path", "description": "Кратчайший путь денег от src к dst",
     "parameters": {"type": "object", "properties": {"src": {"type": "string"}, "dst": {"type": "string"}},
                    "required": ["src", "dst"]}},
    {"name": "top_nodes", "description": "Узлы с наибольшим приоритетом проверки, с фильтрами",
     "parameters": {"type": "object", "properties": {"role": {"type": "string"}, "cluster_id": {"type": "integer"},
                    "n": {"type": "integer"}, "include_seed": {"type": "boolean"}}}},
    {"name": "cluster_summary", "description": "Состав, оборот и гипотеза по кластеру",
     "parameters": {"type": "object", "properties": {"cluster_id": {"type": "integer"}}, "required": ["cluster_id"]}},
    {"name": "simulate_removal", "description": "Что будет с сетью при блокировке узлов (gids или топ-N по приоритету)",
     "parameters": {"type": "object", "properties": {"gids": {"type": "array", "items": {"type": "string"}},
                    "top_n": {"type": "integer"}}}},
]
TOOLS_SPEC += [
    {"name": "find_cycles", "description": "Возвратные потоки: цепочки через узел, где деньги возвращаются к отправителю",
     "parameters": {"type": "object", "properties": {"gid": {"type": "string"}, "max_len": {"type": "integer"}},
                    "required": ["gid"]}},
    {"name": "next_requests", "description": "Белые пятна: какие выгрузки запросить дальше и почему",
     "parameters": {"type": "object", "properties": {"n": {"type": "integer"}}}},
]
FUNCS = {t["name"]: getattr(tools, t["name"]) for t in TOOLS_SPEC}


def _client():
    key = os.getenv(_P["key_env"])
    if not key:
        raise RuntimeError(f"{_P['key_env']} не задан (LLM_PROVIDER={PROVIDER}) — AI-функции отключены")
    from openai import OpenAI
    return OpenAI(api_key=key, base_url=os.getenv("LLM_BASE_URL") or _P["base_url"])


def ask(messages: list[dict], max_steps: int = 6) -> dict:
    """Агентный цикл: модель вызывает инструменты, пока не сформирует ответ."""
    client = _client()
    msgs = [{"role": "system", "content": SYSTEM}] + messages
    trace = []
    for _ in range(max_steps):
        r = client.chat.completions.create(model=MODEL, messages=msgs, temperature=0.1,
                                           tools=[{"type": "function", "function": t} for t in TOOLS_SPEC])
        m = r.choices[0].message
        if not m.tool_calls:
            return {"answer": m.content, "trace": trace}
        msgs.append({"role": "assistant", "content": m.content or "",
                     "tool_calls": [{"id": tc.id, "type": "function",
                                     "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                                    for tc in m.tool_calls]})
        for tc in m.tool_calls:
            args = json.loads(tc.function.arguments or "{}")
            try:
                res = FUNCS[tc.function.name](**args)
            except Exception as e:  # ошибка инструмента → модели, пусть скорректирует вызов
                res = {"error": str(e)}
            trace.append({"tool": tc.function.name, "args": args})
            msgs.append({"role": "tool", "tool_call_id": tc.id,
                         "content": json.dumps(res, ensure_ascii=False, default=str)[:12000]})
    return {"answer": "Не удалось завершить анализ за отведённое число шагов.", "trace": trace}


def node_card(gid: str) -> dict:
    data = tools.get_node(gid)
    if "error" in data:
        return data
    data["transactions"] = store.transactions(gid)[:40]
    prompt = ("Составь справку по клиенту для AML-аналитика (до 120 слов): 1) роль и уверенность, "
              "2) ключевые потоки (от кого/кому, суммы), 3) на что обратить внимание, "
              "4) какой запрос/выгрузку сделать следующим шагом. Только факты из данных, формулировки-гипотезы.\n\n"
              + json.dumps(data, ensure_ascii=False, default=str))
    r = _client().chat.completions.create(model=MODEL, temperature=0.2,
                                          messages=[{"role": "system", "content": SYSTEM},
                                                    {"role": "user", "content": prompt}])
    return {"gid": gid, "card": r.choices[0].message.content}
