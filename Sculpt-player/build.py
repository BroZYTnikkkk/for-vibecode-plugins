"""Packs this folder into sculpt_player.elyx, the layout ElyxBuilder produces without compilation."""
import os
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = ["refmap.yml", "metainfo.yml", "main.py"]
DIRS = ["sculpt", "assets"]
OUT = os.path.join(HERE, "sculpt_player.elyx")

with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as archive:
    for name in FILES:
        archive.write(os.path.join(HERE, name), name)
    for top in DIRS:
        for root, dirs, files in os.walk(os.path.join(HERE, top)):
            dirs[:] = sorted(d for d in dirs if d != "__pycache__")
            # ElyxBuilder writes directory entries too
            archive.writestr(zipfile.ZipInfo(os.path.relpath(root, HERE).replace(os.sep, "/") + "/"), "")
            for name in sorted(files):
                if name.endswith(".pyc"):
                    continue
                path = os.path.join(root, name)
                archive.write(path, os.path.relpath(path, HERE).replace(os.sep, "/"))
print("built %s, %d bytes" % (os.path.basename(OUT), os.path.getsize(OUT)))
