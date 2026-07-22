from modules.dynamic_caption_page import mixed_audio_filter, replacement_audio_filter


direct = replacement_audio_filter("直接加入（无淡入淡出）", 500, 700, 10)
assert "afade=" not in direct

replacement = replacement_audio_filter("淡入＋淡出", 500, 700, 10)
assert "afade=t=in:st=0:d=0.500" in replacement
assert "afade=t=out:st=9.300:d=0.700" in replacement
assert "apad=pad_dur=86400" in replacement

mixed = mixed_audio_filter(100, 25, "淡入＋淡出", 600, 800, 12)
assert "[0:a:0]" in mixed and "[1:a:0]" in mixed
assert "afade=t=in:st=0:d=0.600" in mixed
assert "afade=t=out:st=11.200:d=0.800" in mixed
assert "volume=0.250" in mixed

print("audio fade filters: OK")
