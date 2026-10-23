# -*- coding: utf-8 -*-
"""Собирает тексты запланированных задач из prompts/*.md и config.json.

Тексты задач хранятся в репозитории под версиями, а в задачу вставляется
готовый результат из rendered/. Незаполненная подстановка — ошибка, а не
молча пустое место.

    python3 drive_digest/render_prompts.py           # пересобрать rendered/
    python3 drive_digest/render_prompts.py --check   # проверить, что rendered/ актуальны
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TASKS = ("scan", "report")
PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


def load_values(config: dict) -> dict:
    values = {k: str(v) for k, v in config["drive"].items()}
    values.update({k: str(v) for k, v in config["limits"].items()})
    values["timezone"] = config["timezone"]
    values["timezone_label"] = config["timezone_label"]
    values["recipients"] = ", ".join(config["recipients"])
    values["urgent_criteria"] = "; ".join(config["urgent_criteria"])
    return values


def render(name: str, values: dict) -> str:
    common = (ROOT / "prompts" / "_common.md").read_text(encoding="utf-8")
    task = (ROOT / "prompts" / f"{name}.md").read_text(encoding="utf-8")
    text = common.rstrip() + "\n\n" + task

    missing = sorted({m for m in PLACEHOLDER.findall(text) if m not in values})
    if missing:
        raise SystemExit(f"{name}: нет значений в config.json для {missing}")
    return PLACEHOLDER.sub(lambda m: values[m.group(1)], text)


def main() -> int:
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    values = load_values(config)
    out_dir = ROOT / "rendered"
    out_dir.mkdir(exist_ok=True)
    check = "--check" in sys.argv[1:]
    stale = []
    for name in TASKS:
        text = render(name, values)
        out = out_dir / f"{name}.md"
        if check:
            if not out.exists() or out.read_text(encoding="utf-8") != text:
                stale.append(out.name)
        else:
            out.write_text(text, encoding="utf-8")
            print(f"{out.relative_to(ROOT.parent)}: {len(text)} символов")
    if stale:
        print("Устарели, запустите без --check:", ", ".join(stale))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
