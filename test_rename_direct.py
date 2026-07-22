from pathlib import Path
from tempfile import TemporaryDirectory

from modules.rename_page import RenameTask


def main():
    with TemporaryDirectory() as temp:
        source=Path(temp)/"素材"; source.mkdir()
        task=RenameTask(source,source.parent,source.name,"前缀",
                        "这是一条不应被二十字截断的完整长标题.mp4\n第二条标题",
                        "20260722","FF-PT",1,3,True,direct_replace=True)
        first,adjusted=task.render_name_info("1.mp4",1)
        second,_=task.render_name_info("2.mov",2)
        assert first=="这是一条不应被二十字截断的完整长标题.mp4" and not adjusted
        assert second=="第二条标题.mov"
        normal=RenameTask(source,source.parent,source.name,"","标题","","",1,3,True)
        assert normal.render_name("1.mp4",1)=="001-标题.mp4"
    print("rename direct replacement + legacy rules: OK")


if __name__=="__main__":
    main()
