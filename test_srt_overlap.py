from modules.dynamic_caption_page import fix_srt_overlaps, parse_srt


sample = """1
00:00:03,500 --> 00:00:06,260
τους ειρήνη και χαρά

2
00:00:06,120 --> 00:00:07,960
από κάθε κακό
"""

fixed,count=fix_srt_overlaps(sample)
assert count == 1
entries=parse_srt(fixed)
assert entries[0][1] == 6.1
assert entries[1][0] == 6.12
assert entries[0][1] < entries[1][0]
assert entries[0][2] == "τους ειρήνη και χαρά"

unchanged,unchanged_count=fix_srt_overlaps(fixed)
assert unchanged_count == 0 and unchanged == fixed

print("SRT overlap auto-fix: OK")
