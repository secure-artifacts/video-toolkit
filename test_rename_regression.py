import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from modules.rename_page import (
    INVALID_FILENAME_CHARS,
    RenameTask,
    RenameWorker,
    natural_key,
)


root = Path(os.environ["RENAME_TEST_ROOT"])
task = RenameTask(
    root / "src",
    root / "out",
    "CON",
    "ZB:测试",
    '合法标题\n含:非法?字符"\n这是一段特别特别特别特别特别特别长的标题，需要安全截断',
    "20260719",
    "FF|PT",
    1,
    3,
    True,
)

ordered = sorted((root / "src").iterdir(), key=lambda path: natural_key(path.name))
print("sorted", [path.name for path in ordered])
print("task", task.task_name, task.prefix, task.suffix)
print("preview", [task.render_name_info(path.name, index + 1) for index, path in enumerate(ordered)])

worker = RenameWorker([task])
worker.run()
files = sorted(task.output_folder().iterdir())
valid = (
    len(files) == 3
    and all(not any(char in path.name for char in INVALID_FILENAME_CHARS) for path in files)
    and all(len(path.name) <= 230 for path in files)
    and all((root / "src" / name).exists() for name in ("1.mp4", "2.mp4", "10.mp4"))
)
print("output", [path.name for path in files])
print("valid", valid)
if not valid:
    raise SystemExit(1)
