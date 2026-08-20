from pathlib import Path
from tempfile import TemporaryDirectory

from modules.group_merge import (
    GroupMergeWorker, discover_groups, hybrid_trim_bounds, match_clips_to_script,
    speech_trim_bounds, split_group_script,
)


def main():
    with TemporaryDirectory() as temp:
        root = Path(temp)
        group_10 = root / "10组"; group_2 = root / "2组"
        group_10.mkdir(); group_2.mkdir()
        for name in ("10.mp4", "2.mp4", "1.mp4"):
            (group_2 / name).touch()
        (group_10 / "1.mp4").touch()
        groups = discover_groups(root)
        assert [folder.name for folder, _clips in groups] == ["2组", "10组"]
        assert [path.name for path in groups[0][1]] == ["1.mp4", "2.mp4", "10.mp4"]

        flat = root / "同目录分组"; flat.mkdir()
        for name in ("祷告A_1.mp4", "祷告A_2.mp4", "祝福B-1.mp4", "祝福B-2.mp4", "祝福B-3.mp4"):
            (flat / name).touch()
        flat_groups = discover_groups(flat)
        assert [folder.name for folder, _clips in flat_groups] == ["祝福B", "祷告A"]
        assert [[clip.name for clip in clips] for _folder, clips in flat_groups] == [
            ["祝福B-1.mp4", "祝福B-2.mp4", "祝福B-3.mp4"],
            ["祷告A_1.mp4", "祷告A_2.mp4"],
        ]

        timestamped = root / "带时间戳"; timestamped.mkdir()
        for name in ("2-3_202607211405.mp4", "2-1_202607211405.mp4", "2-2_202607211405.mp4",
                     "11-2.mp4", "11-1.mp4"):
            (timestamped / name).touch()
        timestamped_groups = discover_groups(timestamped)
        assert [folder.name for folder, _clips in timestamped_groups] == ["2", "11"]
        assert [[clip.name for clip in clips] for _folder, clips in timestamped_groups] == [
            ["2-1_202607211405.mp4", "2-2_202607211405.mp4", "2-3_202607211405.mp4"],
            ["11-1.mp4", "11-2.mp4"],
        ]

        clips = [group_2 / "a.mp4", group_2 / "b.mp4"]
        transcripts = {
            str(clips[0].resolve()): "Jesus está contigo",
            str(clips[1].resolve()): "Amen para sua família",
        }
        ordered, reason, details = match_clips_to_script(
            clips, transcripts, "Amen para sua família\n\n---\n\nJesus está contigo",
        )
        assert ordered == [clips[1], clips[0]], reason
        assert details and details[0]["clip"] == clips[1]
        assert split_group_script("primeiro\n\n---\n\nsegundo") == ["primeiro", "segundo"]

        # Greek-like script order must beat natural filename order.
        g_clips = [group_2 / "1.mp4", group_2 / "2.mp4"]
        g_transcripts = {
            str(g_clips[0].resolve()): "Γράψε Αμήν και πίστευε",
            str(g_clips[1].resolve()): "Προσευχή για το παιδί σου τρεις φορές",
        }
        g_script = (
            "Προσευχή για το παιδί σου τρεις φορές, για να σπάσει κάθε κατάρα.\n\n"
            "Γράψε Αμήν και πίστευε στον Θεό."
        )
        g_ordered, g_reason, _g_details = match_clips_to_script(g_clips, g_transcripts, g_script)
        assert g_ordered == [g_clips[1], g_clips[0]], g_reason

        # 低相似度必须拒绝重排（日志里 0.25～0.39 那种）
        bad_clips = [group_2 / "a.mp4", group_2 / "b.mp4", group_2 / "c.mp4"]
        for p in bad_clips:
            p.touch()
        bad_tr = {
            str(bad_clips[0].resolve()): "19 Αυγούστου. Ο διάβολος θέλει να προσπεράσεις",
            str(bad_clips[1].resolve()): "Βλέπεις τον πόνο της ψυχής μου τα δακρυά μου",
            str(bad_clips[2].resolve()): "Το ότι βλέπεις αυτό το μήνυμα δεν είναι τυχαίο",
        }
        bad_script = (
            "Σε καμία περίπτωση μην προσπεράσεις αυτό το βίντεο.\n\n"
            "Εσύ και η οικογένειά σου θα λάβετε καλά νέα από τον Θεό.\n\n"
            "από σήμερα. Αν έχεις την ευκαιρία, μοιράσου αυτό το μήνυμα."
        )
        bad_ordered, bad_reason, bad_details = match_clips_to_script(bad_clips, bad_tr, bad_script)
        assert bad_ordered is None, (bad_reason, bad_details)
        assert "可信度不足" in bad_reason

        # Optimal assignment beats greedy near-ties (similar openings).
        from modules.group_merge import _max_weight_assignment
        # Greedy would take A→seg0 (0.90) then B→seg1 (0.50); optimal is A→seg1, B→seg0.
        assert _max_weight_assignment([[0.90, 0.88], [0.89, 0.50]]) == [1, 0]

        # Numbered script with wrapped lines must stay 3 segments for 3 clips.
        numbered = (
            "1. 今天第一段很长\n继续写在第一段里\n"
            "2. 今天第二段内容\n"
            "3. 今天第三段收尾"
        )
        assert split_group_script(numbered, 3) == [
            "今天第一段很长 继续写在第一段里",
            "今天第二段内容",
            "今天第三段收尾",
        ]
        assert split_group_script("1、甲\n2、乙\n3、丙", 3) == ["甲", "乙", "丙"]

        # 正文中间误出现「2.」时，不得抢走空行三分段（1.7.48 回归）
        messy = (
            "First paragraph says nothing special.\n\n"
            "Second has\n2. this mid line that starts with number after newline\n\n"
            "Third paragraph ends."
        )
        assert split_group_script(messy, 3) == [
            "First paragraph says nothing special.",
            "Second has 2. this mid line that starts with number after newline",
            "Third paragraph ends.",
        ]
        # 段数碰巧=2 时也不能用错误序号切开
        assert len(split_group_script(messy, 2)) != 2 or split_group_script(messy, 2)[0].startswith("First")
        # 上面：期望 2 时最接近是空行 3 段，返回 3 段供上层报错；不得返回假序号 2 段
        bad2 = split_group_script(messy, 2)
        assert len(bad2) == 3, bad2

        # Reorder by script content vs filename 1/2/3.
        r_clips = [group_2 / "1.mp4", group_2 / "2.mp4", group_2 / "3.mp4"]
        for p in r_clips:
            p.touch()
        r_transcripts = {
            str(r_clips[0].resolve()): "欢迎来到频道今天分享护肤第二步保湿",
            str(r_clips[1].resolve()): "欢迎来到频道今天分享护肤第一步清洁",
            str(r_clips[2].resolve()): "感谢收看下期再见",
        }
        r_script = (
            "欢迎来到频道今天分享护肤第一步清洁\n\n"
            "欢迎来到频道今天分享护肤第二步保湿\n\n"
            "感谢收看下期再见"
        )
        r_ordered, r_reason, _ = match_clips_to_script(r_clips, r_transcripts, r_script)
        assert r_ordered == [r_clips[1], r_clips[0], r_clips[2]], r_reason

        srt = "1\n00:00:00,300 --> 00:00:01,200\nOlá\n\n2\n00:00:01,300 --> 00:00:02,400\nmundo"
        start, end, detected = speech_trim_bounds(srt, 3.0, 80, 120)
        # 片头 padding 至少 200ms：0.30 - 0.20 = 0.10；末词后剩余 ≤0.85s 保留到片尾
        assert detected and abs(start - 0.10) < 0.001 and abs(end - 3.0) < 0.001
        assert speech_trim_bounds("", 3.0) == (0.0, 3.0, False)
        # 末词后留白充足时：尾 = max(280, pad) + safety，不拉满到片尾
        long_srt = "1\n00:00:00,300 --> 00:00:01,200\nOlá\n\n2\n00:00:01,300 --> 00:00:02,400\nmundo"
        start2, end2, det2 = speech_trim_bounds(long_srt, 5.0, 80, 120, tail_safety_ms=280)
        assert det2 and abs(start2 - 0.10) < 0.001
        # max(280,120)+280 = 560ms → 2.4+0.56 = 2.96
        assert abs(end2 - 2.96) < 0.001

        # Smart natural-order trimming must use the transcript timeline instead
        # of reusing an older fast-silence cache entry with an empty SRT.
        smart_clip = root / "smart.mp4"; smart_clip.touch()
        calls = []
        smart_srt = "1\n00:00:01,500 --> 00:00:04,200\nTexto real"
        worker = GroupMergeWorker([], root / "out", "ffmpeg",
                                  lambda path: (calls.append(path) or ("Texto real", "", smart_srt)),
                                  {"trim_mode": "smart", "resume": True})
        stale = {str(smart_clip.resolve()): {
            "signature": worker._signature(smart_clip), "srt": "", "bounds": [0.0, 5.0, False],
        }}
        analysis = worker._analysis(smart_clip, stale)
        assert calls == [str(smart_clip)] and analysis["srt"] == smart_srt
        # 6.0 - 4.2 = 1.8 > 0.85 → 不强制到片尾；尾 = 4.2 + max(280,120)/1000 + safety280 = 4.76
        start, end, detected = speech_trim_bounds(analysis["srt"], 6.0, 80, 120, tail_safety_ms=280)
        # 首词 1.5s > 1.2s：疑似漏识别第一句，片头不裁（start=0）；尾 4.2+0.56=4.76
        assert detected and abs(start - 0.0) < .001 and abs(end - 4.76) < .001
        # Audio may tighten padding, but must never cross into the first/last word.
        start, end, detected = hybrid_trim_bounds(
            analysis["srt"], 6.0, (1.47, 4.23, True), 80, 120, 40,
        )
        assert detected and abs(start - 1.46) < .02
        # hybrid 取 speech 与静音外沿：尾扩展后约 4.76
        assert abs(end - 4.76) < .02
        # Internal silence is intentionally irrelevant: only the outer bounds are combined.
        h_start, h_end, h_det = hybrid_trim_bounds(analysis["srt"], 6.0, (0.0, 6.0, False), 80, 120)
        assert h_det and abs(h_start - 0.0) < .001 and abs(h_end - 4.76) < .02
    print("group merge helpers: OK")


if __name__ == "__main__":
    main()
