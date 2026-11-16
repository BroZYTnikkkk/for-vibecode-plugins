# SPDX-License-Identifier: LGPL-3.0-only
# Mornye extensions in Sculpt Player. Copyright 2026 BroNik (@BroZYTnikkkk).

"""mutagen as Sculpt Player already loads it (metainfo requirements), or None."""

try:
    import mutagen
except Exception:
    mutagen = None
