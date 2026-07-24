# -*- coding: utf-8 -*-
from modules.language_style import (
    detect_language, format_subtitle_text, format_subtitle_document,
    is_rtl_text, prepare_ass_dialogue_text, should_disable_letter_spacing,
    should_disable_word_highlight, wrap_rtl_for_ass, effective_letter_spacing,
    writing_language_from_ui, WRITING_LANGUAGE_OPTIONS, BUILTIN_PACKS,
)
from modules.text_rules import normalize_subtitle_text


def check(actual, expected, label=""):
    assert actual == expected, f"{label}: {actual!r} != {expected!r}"


# 检测
check(detect_language("Καλημέρα κόσμε"), "el", "greek detect")
check(detect_language("هذا نص عربي للتجربة"), "ar", "arabic detect")
check(detect_language("שלום עולם"), "he", "hebrew detect")
check(detect_language("Привет мир"), "ru", "russian detect")
check(detect_language("这是一段中文内容"), "zh", "chinese detect")
check(detect_language("Hello world", "el"), "el", "hint wins")
check(detect_language("Hello", "pt-BR"), "pt", "alias")

# UI 解析
check(writing_language_from_ui("自动检测（推荐）"), "", "ui auto")
check(writing_language_from_ui("Ελληνικά 希腊语"), "el", "ui greek")
check(writing_language_from_ui("ar"), "ar", "ui code")

# 语言包齐全
for code in ("en", "pt", "es", "fr", "de", "it", "el", "ru", "tr", "zh", "ar", "he"):
    assert code in BUILTIN_PACKS, code
assert len(WRITING_LANGUAGE_OPTIONS) >= 12

# 希腊引号
el = format_subtitle_text('Είπε "ναι" σήμερα', language="el")
assert "\u00ab" in el and "\u00bb" in el and '"' not in el, el

# 英文弯引号
en = format_subtitle_text('He said "yes"', language="en")
assert "\u201c" in en and "\u201d" in en, en

# 德文引号
de = format_subtitle_text('Er sagte "ja"', language="de")
assert "\u201e" in de, de

# 俄语引号
ru = format_subtitle_text('Он сказал "да"', language="ru")
assert "\u00ab" in ru and "\u00bb" in ru, ru

# 西语倒标
es = format_subtitle_text("Como estas?", language="es")
assert es.startswith("¿") and es.endswith("?"), es
es2 = format_subtitle_text("Hola!", language="es")
assert es2.startswith("¡") and es2.endswith("!"), es2

# SRT 时间轴不动
srt = "1\n00:00:00,000 --> 00:00:02,000\nSaid \"hi\"\n"
formatted = format_subtitle_document(srt, language="en")
assert "00:00:00,000 --> 00:00:02,000" in formatted
assert "\u201c" in formatted or "\u201d" in formatted

# 阿拉伯 / 希伯来 RTL
for sample in ("مرحبا بالعالم", "שלום עולם"):
    assert is_rtl_text(sample)
    assert should_disable_letter_spacing(sample)
    assert should_disable_word_highlight(sample)
    assert not should_disable_word_highlight(sample, allow_rtl_word_highlight=True)
    wrapped = wrap_rtl_for_ass(sample)
    assert wrapped.startswith("\u202b") and wrapped.endswith("\u202c")
    assert "\u202b" in prepare_ass_dialogue_text(sample)

assert effective_letter_spacing({"letter_spacing": 12}, "مرحبا") == 0.0
assert effective_letter_spacing({"letter_spacing": 12}, "Hello") == 12.0

mixed = normalize_subtitle_text('amen and "peace"', language="en")
assert "Amen" in mixed
assert "\u201c" in mixed or "\u201d" in mixed

print("OK language_style packs ui es-inverted rtl he ru")
