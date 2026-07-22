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
        ordered, reason = match_clips_to_script(
            clips, transcripts, "Amen para sua família\n\n---\n\nJesus está contigo",
        )
        assert ordered == [clips[1], clips[0]], reason
        assert split_group_script("primeiro\n\n---\n\nsegundo") == ["primeiro", "segundo"]

        srt = "1\n00:00:00,300 --> 00:00:01,200\nOlá\n\n2\n00:00:01,300 --> 00:00:02,400\nmundo"
        start, end, detected = speech_trim_bounds(srt, 3.0, 80, 120)
        assert detected and abs(start - 0.22) < 0.001 and abs(end - 2.52) < 0.001
        assert speech_trim_bounds("", 3.0) == (0.0, 3.0, False)

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
        start, end, detected = speech_trim_bounds(analysis["srt"], 6.0, 80, 120)
        assert detected and abs(start - 1.42) < .001 and abs(end - 4.32) < .001
        # Audio may tighten padding, but must never cross into the first/last word.
        start, end, detected = hybrid_trim_bounds(
            analysis["srt"], 6.0, (1.47, 4.23, True), 80, 120, 40,
        )
        assert detected and abs(start - 1.46) < .001 and abs(end - 4.24) < .001
        # Internal silence is intentionally irrelevant: only the outer bounds are combined.
        assert hybrid_trim_bounds(analysis["srt"], 6.0, (0.0, 6.0, False), 80, 120)[:2] == (1.42, 4.32)
    print("group merge helpers: OK")


if __name__ == "__main__":
    main()
