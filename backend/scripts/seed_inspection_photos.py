"""在 photos 根目录按 source 布局生成测试照片，并校验查阅接口。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw

from app.core.inspection import (
    list_viewer_dates,
    list_viewer_images,
    load_settings,
    resolve_image,
    today_str,
)


def main() -> None:
    settings = load_settings()
    root = Path(settings["mold_root_path"] or r"E:\Project\LimAnalysis\photos")
    root.mkdir(parents=True, exist_ok=True)
    day = today_str() or datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d")

    # source: 机台/日期/穴位/状态/*.jpg
    specs = [
        ("D6", "A", "OK", 3, (56, 132, 255)),
        ("D6", "B", "OK", 2, (34, 197, 94)),
        ("D6", "A", "定位NG", 1, (239, 68, 68)),
        ("D7", "A", "OK", 2, (168, 85, 247)),
    ]

    created: list[Path] = []
    for machine, cavity, status, count, color in specs:
        folder = root / machine / day / cavity / status
        folder.mkdir(parents=True, exist_ok=True)
        for i in range(1, count + 1):
            name = f"{status},sample{i:02d},{cavity}.jpg"
            path = folder / name
            img = Image.new("RGB", (640, 480), color)
            draw = ImageDraw.Draw(img)
            draw.rectangle((0, 0, 640, 56), fill=(17, 24, 39))
            draw.text((24, 18), f"{machine}  {cavity}穴  {status}  #{i}", fill=(255, 255, 255))
            draw.text((24, 220), day, fill=(255, 255, 255))
            img.save(path, quality=88)
            created.append(path)

    print(f"root={root}")
    print(f"date={day}")
    print(f"created={len(created)}")
    for path in created:
        print(f"  {path}")

    dates = list_viewer_dates("eagle_rcvr", "D6")
    print("viewer_dates=", dates)
    ok_a = list_viewer_images("eagle_rcvr", "D6", "A", dates["default_date"], "OK")
    print(
        "viewer_OK_A=",
        ok_a["total_count"],
        [item["filename"] for item in ok_a["images"]],
        "layout=",
        ok_a.get("layout"),
    )
    ng_a = list_viewer_images("eagle_rcvr", "D6", "A", dates["default_date"], "定位NG")
    print("viewer_NG_A=", ng_a["total_count"], [item["filename"] for item in ng_a["images"]])
    if ok_a["images"]:
        resolved = resolve_image(ok_a["images"][0]["rel_path"])
        print(
            "image_ok=",
            resolved.is_file(),
            "size=",
            resolved.stat().st_size,
            "url=",
            ok_a["images"][0]["view_url"],
        )


if __name__ == "__main__":
    main()
