import os
import tempfile
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="group_caption_appdata_")
os.environ["LOCALAPPDATA"] = os.environ["APPDATA"]

from PySide6.QtWidgets import QApplication
from modules.dynamic_caption_page import GroupCaptionDialog
from modules.group_merge import split_group_script


app = QApplication.instance() or QApplication([])
root = Path(tempfile.mkdtemp(prefix="group_caption_test_"))
group_a = root / "1"; group_b = root / "2"
groups = [(group_a, [group_a / "1.mp4", group_a / "2.mp4"]),
          (group_b, [group_b / "1.mp4"])]
dialog = GroupCaptionDialog(groups, {})
app.clipboard().setText("第一段\n第二段\n第三段")
dialog._paste_all()
scripts = dialog.scripts()
assert split_group_script(scripts[str(group_a.resolve())]) == ["第一段", "第二段"]
assert split_group_script(scripts[str(group_b.resolve())]) == ["第三段"]
assert dialog.table.item(0, 5).text() == "✓ 已对应"
print("OK group_caption_table=folder_rows clipboard=auto_distributed")
