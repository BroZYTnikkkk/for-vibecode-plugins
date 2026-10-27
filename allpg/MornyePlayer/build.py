"""Pack this folder into mornye_player.elyx (same layout ElyxBuilder produces without compilation)."""
import os
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = ["refmap.yml", "metainfo.yml", "main.py"]
DIRS = ["mornye", "assets", "wheels"]

with zipfile.ZipFile(os.path.join(HERE, "mornye_player.elyx"), "w", zipfile.ZIP_DEFLATED) as zf:
    for name in FILES:
        zf.write(os.path.join(HERE, name), name)
    for top in DIRS:
        for root, _, files in os.walk(os.path.join(HERE, top)):
            for name in sorted(files):
                if name.endswith(".pyc") or "__pycache__" in root:
                    continue
                path = os.path.join(root, name)
                zf.write(path, os.path.relpath(path, HERE).replace(os.sep, "/"))
print("built mornye_player.elyx")
