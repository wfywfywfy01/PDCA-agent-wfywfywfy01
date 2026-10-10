"""Conservative display corrections anchored to this session's public words."""
import re


def normalize_sales_asr(text: str, snapshot: dict, public_words) -> str:
    context = "\n".join(value for value in (
        *(snapshot.get(key, "") for key in ("title", "public_brief", "stage_summary")),
        *public_words,
    ) if isinstance(value, str))
    # ponytail: only three observed phrases; broader ASR correction needs separate evidence.
    rules = (("首单", r"(?<=不急着[订定])手单"),
             ("试单", r"市单(?=周转量)"),
             ("缺项", r"确项(?=清单)"))
    for term, pattern in rules:
        if term not in context or term in text:
            continue
        if term == "首单" and any(word in text for word in ("手工", "人工", "手写")):
            continue
        text = re.sub(pattern, term, text)
    return text
