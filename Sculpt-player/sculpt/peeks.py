# Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).

"""The title of the song a swipe brings in, over its cover.

PlayerCoverView draws the neighbor itself while a finger drags the cover (drawSide: placed a page away, 0.86 of
the size at that distance, full size in the middle). This draws only that song's title over it, moving with it.
The neighbor comes from the sheet's own getNeighborMessage, which NeighborHook teaches the shuffled order.
"""

from java import jclass

from .common import _dp

SIDE_SCALE = 0.86  # PlayerCoverView.drawSide
TITLE_SP = 14.0


def shuffled_neighbor(media_fields, direction):
    """The song a swipe brings in when the queue plays mixed: MediaController walks shuffledPlaylist towards index 0
    for the next song (getNextTrackDirection is -1 then), so the next one is a step down and the previous a step up."""
    controller = jclass("org.telegram.messenger.MediaController").getInstance()
    mixed = media_fields.get(controller, "shuffledPlaylist")
    if mixed is None:
        return None
    count = mixed.size()
    number = controller.getPlayingMessageObjectNum()
    if count < 2 or number < 0 or number >= count:
        return None
    index = number - 1 if direction > 0 else number + 1
    if index < 0:
        index = count - 1
    elif index >= count:
        index = 0
    return mixed.get(index)


class Peeks:
    def __init__(self, plugin, player):
        self.plugin = plugin
        self.player = player
        self.side = 0
        self.key = None
        self.title = ""
        self.shown = ""
        self.shown_width = 0
        self.text = jclass("android.text.TextPaint")(1)  # ANTI_ALIAS_FLAG
        self.text.setTextSize(float(_dp(TITLE_SP)))
        self.text.setTextAlign(jclass("android.graphics.Paint$Align").CENTER)

    def dispose(self):
        self.title = ""

    def neighbor_title(self, side):
        """Asked once per swipe and side: the same delegate the cover view asks for that cover."""
        cover = self.player.coverView
        playing = cover.getMessageObject()
        key = (side, None if playing is None else (playing.getDialogId(), playing.getId()))
        if key == self.key:
            return self.title
        self.key = key
        delegate = self.plugin.cover_fields.get(cover, "delegate")
        message = delegate.getNeighbor(side) if delegate is not None and playing is not None else None
        self.title = str(message.getMusicTitle() or "") if message is not None else ""
        self.shown_width = 0
        return self.title

    def draw(self, canvas, colors):
        cover = self.player.coverView
        offset = float(cover.getPageOffset())
        if offset == 0.0 or colors is None:
            return
        f = self.plugin.layout_fields
        lay = self.player.layout
        mode = max(0.0, min(1.0, self.plugin.sheet_fields.float(self.player.sheet, "modeProgress")))
        if mode >= 0.99:
            return
        size = f.float(lay, "coverSize")
        page = float(cover.getPageWidth())
        if size <= 0 or page <= 0:
            return
        side = 1 if offset < 0.0 else -1  # dragging left brings the next song: PlayerCoverView.setDragOffset
        title = self.neighbor_title(side)
        if not title:
            return
        # where the cover view draws that neighbor: a page away, moved by the finger, shrinking with the distance
        center = f.float(lay, "coverLeft") + size / 2.0 + side * page + offset
        distance = min(1.0, abs(side * page + offset) / page)
        scale = 1.0 + (SIDE_SCALE - 1.0) * distance
        width = size * scale
        top = f.float(lay, "coverTop") + (size - width) / 2.0
        pane_left = float(f.int(lay, "paneLeft"))
        pane_width = float(f.int(lay, "paneWidth"))
        margin = float(_dp(16))
        room = min(width, pane_width * 0.6) - _dp(8)
        if int(room) != self.shown_width:
            self.shown = str(jclass("android.text.TextUtils").ellipsize(title, self.text, float(room),
                                                                       jclass("android.text.TextUtils$TruncateAt").END))
            self.shown_width = int(room)
        # the cover comes in from off the screen: the title stays whole on it, at the edge it comes from,
        # and follows the cover's middle once that is in view
        half = self.text.measureText(self.shown) / 2.0
        center = max(pane_left + margin + half, min(pane_left + pane_width - margin - half, center))
        alpha = (1.0 - mode) * min(1.0, abs(offset) / (page * 0.25))
        self.text.setColor(colors.text)
        self.text.setAlpha(int(230 * alpha))
        canvas.drawText(self.shown, center, top - _dp(10) - self.text.descent(), self.text)
        lay.postInvalidateOnAnimation()
