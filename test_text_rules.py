from modules.text_rules import normalize_required_capitalization


def check(source, expected):
    actual = normalize_required_capitalization(source)
    assert actual == expected, (source, actual, expected)


check("amen deus jesus senhor κύριος pai", "Amen Deus Jesus Senhor Κύριος Pai")
check("amém amén αμήν", "Amém Amén Αμήν")
check("AMEN, dEuS! JESUS; SENHOR? ΚΎΡΙΟΣ. PAI", "Amen, Deus! Jesus; Senhor? Κύριος. Pai")
check("amendoim deuses senhores pais", "amendoim deuses senhores pais")
check(
    "1\n00:00:00,000 --> 00:00:02,000\namen, senhor.\n",
    "1\n00:00:00,000 --> 00:00:02,000\nAmen, Senhor.\n",
)

print("OK capitalization=unicode_case_insensitive whole_words_only")
