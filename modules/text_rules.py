from __future__ import annotations

import re


# 字幕识别容易把专有宗教称谓输出成小写。这里保存用户要求的规范写法；
# 使用完整 Unicode 单词匹配，标点相邻时也生效，但不会误改更长单词。
_TERM_SPELLINGS = {
    "amen": "Amen",
    "amém": "Amém",
    "amén": "Amén",
    "αμήν": "Αμήν",
    "deus": "Deus",
    "jesus": "Jesus",
    "senhor": "Senhor",
    "κύριος": "Κύριος",
    "pai": "Pai",
}
_CAPITALIZED_TERMS = {term.casefold(): spelling for term, spelling in _TERM_SPELLINGS.items()}
_CAPITALIZED_PATTERN = re.compile(
    r"(?<!\w)(?:" + "|".join(re.escape(term) for term in _TERM_SPELLINGS) + r")(?!\w)",
    flags=re.IGNORECASE,
)


def normalize_required_capitalization(text: str) -> str:
    """把指定完整单词统一为规范首字母大写，保留其余文本与时间轴格式。"""
    value = str(text or "")
    return _CAPITALIZED_PATTERN.sub(
        lambda match: _CAPITALIZED_TERMS.get(match.group(0).casefold(), match.group(0)),
        value,
    )
