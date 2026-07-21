from pathlib import Path
from tempfile import TemporaryDirectory

from modules.group_merge import (
    discover_groups, match_clips_to_script, speech_trim_bounds, split_group_script,
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
    print("group merge helpers: OK")


if __name__ == "__main__":
    main()
