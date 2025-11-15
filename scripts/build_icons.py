# =====================================================================
# ⚠️  DEPRECATED SCRIPT - NOT INTEGRATED
# =====================================================================
# This CLI script is not integrated into the Flask/Celery web service.
# 
# Status: Standalone utility for icon generation using ImageMagick
#
# Options:
#   1. Integrate into web service as /build_icons route + Celery task
#   2. Keep as standalone utility if rarely used
#
# This script generates icons with different backgrounds and sizes
# from high-res images in assets_hires directory.
#
# See DEPRECATED_SCRIPTS.md for more information.
# =====================================================================

import os
import subprocess


size_list = ["1024x1024\\!"]
bgcolors = ["white", "black"]


def build_icons() -> None:
    #    magick input.png -background white -alpha remove -alpha off output.png
    assets_dir = "assets_hires"
    for filename in os.listdir(assets_dir):
        if filename.lower().startswith(("low", "shortdef", "word", "icon", "image")):
            continue
        if filename.lower().endswith((".png", ".jpg", ".jpeg")):
            input_path = os.path.join(assets_dir, filename)
            for size in size_list:
                for bgcolor in bgcolors:
                    filesize = size.split("x")[0]
                    output_path = os.path.join(
                        assets_dir, f"icon_{bgcolor}_{filesize}_{filename}"
                    )
                    print(f"processing {filename} into {output_path}")
                    subprocess.run(
                        [
                            "magick",
                            input_path,
                            "-background",
                            bgcolor,
                            "-alpha",
                            "remove",
                            "-alpha",
                            "off",
                            "-resize",
                            size,
                            output_path,
                        ],
                        check=True,
                    )


if __name__ == "__main__":
    build_icons()
