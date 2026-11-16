# Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).

"""A song's page: the cover and the names, what matters on a plate, the file, the rest of the tags, the sound and
the history folded under "Details"; authors, albums and genres open in the library."""

import os
import re
import threading
import time

from android_utils import copy_to_clipboard, run_on_ui_thread
from java import dynamic_proxy, jclass

from .i18n import plural, tr
from .common import _dp, _log

try:
    import mutagen
except Exception:
    mutagen = None

MONTHS = (tr("января"), tr("февраля"), tr("марта"), tr("апреля"), tr("мая"), tr("июня"), tr("июля"), tr("августа"), tr("сентября"), tr("октября"), tr("ноября"), tr("декабря"))
TAG_KEYS = ("title", "album", "artist", "albumartist", "composer", "genre", "tracknumber", "discnumber", "date",
            "isrc", "lyricist", "organization", "copyright", "bpm")
SYNCED = re.compile(r"\[\d{1,3}:\d{2}")
STORAGE = "/storage/emulated/0"
FORMATS = {"MP3": "MP3", "FLAC": "FLAC", "MP4": "M4A", "OggVorbis": "Ogg", "OggOpus": "Opus", "WAVE": "WAV", "AIFF": "AIFF"}


class DialogButton(dynamic_proxy(jclass("org.telegram.ui.ActionBar.AlertDialog$OnButtonClickListener"))):
    def __init__(self, action):
        super().__init__()
        self.action = action

    def onClick(self, dialog, which):
        action, self.action = self.action, None
        if action is not None:
            action()


class Dismissed(dynamic_proxy(jclass("android.content.DialogInterface$OnDismissListener"))):
    def __init__(self, action):
        super().__init__()
        self.action = action

    def onDismiss(self, dialog):
        action, self.action = self.action, None
        if action is not None:
            action()


# -- reading the file --------------------------------------------------------------------------


def _first(value):
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        value = value[0] if value else ""
    text = getattr(value, "text", None)
    if text is not None:
        value = text[0] if isinstance(text, (list, tuple)) and text else text
    return str(value).strip()


def _raw_extras(raw):
    """The comment and the lyrics: each container keeps them under its own names."""
    comment, lyrics = "", ""
    tags = getattr(raw, "tags", None)
    if tags is None:
        return comment, lyrics
    try:
        keys = list(tags.keys())
    except Exception:
        return comment, lyrics
    for key in keys:
        upper = str(key).upper()
        try:
            value = tags[key]
        except Exception:
            continue
        if not comment and (upper.startswith("COMM") or upper in ("COMMENT", "DESCRIPTION", "©CMT")):
            comment = _first(value)
        elif not lyrics and (upper.startswith("USLT") or upper in ("LYRICS", "UNSYNCEDLYRICS", "©LYR")):
            lyrics = _first(value)
        elif not lyrics and upper.startswith("SYLT"):
            lyrics = "[00:00]"  # a synced lyrics frame: only its presence matters here
    return comment, lyrics


def _codec(raw, info):
    kind = type(raw).__name__
    bits = getattr(info, "bits_per_sample", 0) or 0
    if kind == "MP3":
        mode = str(getattr(info, "bitrate_mode", "")).rsplit(".", 1)[-1]
        version = getattr(info, "version", 1)
        text = "MPEG-%s Layer %s" % ("%g" % version if version else "1", getattr(info, "layer", 3))
        return text + (", %s" % mode if mode and mode != "UNKNOWN" else "")
    if kind == "MP4":
        return str(getattr(info, "codec_description", "") or getattr(info, "codec", "") or "MP4")
    name = {"FLAC": "FLAC", "OggVorbis": "Vorbis", "OggOpus": "Opus", "WAVE": "PCM", "AIFF": "PCM"}.get(kind, kind)
    return tr("%s %d бит") % (name, bits) if bits else name


def read_file(path):
    """Tags and sound of a file, from mutagen; the Android retriever fills in when mutagen cannot read it."""
    data = {"tags": {key: "" for key in TAG_KEYS}, "comment": "", "lyrics": "", "length": 0, "bitrate": 0,
            "sample_rate": 0, "bits": 0, "channels": 0, "format": os.path.splitext(path)[1].lstrip(".").upper(),
            "codec": "", "size": 0, "mtime": 0}
    try:
        data["size"] = os.path.getsize(path)
        data["mtime"] = int(os.path.getmtime(path))
    except OSError:
        pass
    read = False
    if mutagen is not None:
        try:
            easy = mutagen.File(path, easy=True)
            if easy is not None and easy.tags is not None:
                for key in TAG_KEYS:
                    try:
                        data["tags"][key] = _first(easy.tags.get(key))
                    except Exception:
                        pass
            raw = mutagen.File(path)
            if raw is not None:
                data["comment"], data["lyrics"] = _raw_extras(raw)
                info = raw.info
                data["length"] = int(getattr(info, "length", 0) or 0)
                data["bitrate"] = int(getattr(info, "bitrate", 0) or 0)
                data["sample_rate"] = int(getattr(info, "sample_rate", 0) or 0)
                data["bits"] = int(getattr(info, "bits_per_sample", 0) or 0)
                data["channels"] = int(getattr(info, "channels", 0) or 0)
                data["format"] = FORMATS.get(type(raw).__name__, data["format"])
                data["codec"] = _codec(raw, info)
                read = True
        except Exception as e:
            _log("song info %s: %s" % (os.path.basename(path), e))
    if not read:
        retriever = jclass("android.media.MediaMetadataRetriever")()
        try:
            retriever.setDataSource(path)

            def get(key):
                value = retriever.extractMetadata(key)
                return str(value) if value is not None else ""

            for key, number in (("title", 7), ("album", 1), ("artist", 2), ("albumartist", 13), ("composer", 4),
                                ("genre", 6), ("tracknumber", 0), ("discnumber", 14), ("date", 8)):
                data["tags"][key] = get(number)
            data["length"] = int(get(9) or 0) // 1000
            data["bitrate"] = int(get(20) or 0)
            data["sample_rate"] = int(get(38) or 0)
            data["bits"] = int(get(39) or 0)
        except Exception:
            pass
        finally:
            retriever.release()
    return data


# -- words -------------------------------------------------------------------------------------


def times_label(count):
    return tr("один раз") if count == 1 else plural(count, tr("%d раз"), tr("%d раза"), tr("%d раз")) % count


def date_label(stamp):
    if not stamp:
        return ""
    t = time.localtime(stamp)
    return "%d %s %d, %02d:%02d" % (t.tm_mday, MONTHS[t.tm_mon - 1], t.tm_year, t.tm_hour, t.tm_min)


def clock(seconds):
    seconds = max(0, int(seconds))
    if seconds >= 3600:
        return "%d:%02d:%02d" % (seconds // 3600, seconds // 60 % 60, seconds % 60)
    return "%d:%02d" % (seconds // 60, seconds % 60)


def place_label(path):
    """The folder as a person sees it: "Внутренняя память › Music › FLAC"."""
    folder = os.path.dirname(path)
    if folder.startswith(STORAGE):
        parts = [tr("Внутренняя память")] + [p for p in folder[len(STORAGE):].split("/") if p]
    else:
        parts = [p for p in folder.split("/") if p]
    return " › ".join(parts)


def number_label(value):
    """"3/12" reads "3 из 12"; a zero is what an M4A stores when there is no number at all."""
    first, _, total = str(value or "").strip().partition("/")
    first, total = first.strip(), total.strip()
    if first in ("", "0"):
        return ""
    return tr("%s из %s") % (first, total) if total not in ("", "0") else first


def year_label(value):
    text = str(value or "").strip()[:10]
    return "" if text in ("", "0", "0000") else text


def size_label(size):
    if size >= 1048576:
        return tr("%.2f МБ") % (size / 1048576.0)
    return tr("%d КБ") % (size // 1024)


# -- the dialog --------------------------------------------------------------------------------


class SongInfo:
    """The song's page in a window over the player, whatever tab is open under it."""

    def __init__(self, player, path, library_path=None, fallback=None):
        self.player = player
        self.path = path
        self.library_path = library_path
        self.fallback = fallback or {}
        self.screen = None
        self.dialog = None

    def show(self):
        from .common import PANEL_LIBRARY
        player = self.player
        context = player.context
        # the page's helpers (colors, icons, rounded shapes) are the library's; the library itself stays as it is
        owner = player.ensure_stack(PANEL_LIBRARY, player.plugin.sheet_fields.get(player.sheet, "colors"))
        self.screen = SongInfoScreen(owner, self.path, self.library_path, self.fallback, self.close)
        FrameLayout = jclass("android.widget.FrameLayout")
        panel = FrameLayout(context)
        solid = jclass("androidx.core.graphics.ColorUtils").setAlphaComponent(owner.color("background"), 255)
        panel.setBackground(owner.rounded(solid, _dp(28)))
        panel.setClipToOutline(True)
        panel.addView(self.screen.view, FrameLayout.LayoutParams(-1, -1))
        dialog = jclass("android.app.Dialog")(context)
        dialog.requestWindowFeature(1)  # Window.FEATURE_NO_TITLE
        dialog.setContentView(panel)
        dialog.setCanceledOnTouchOutside(True)
        dialog.setOnDismissListener(Dismissed(self.release))
        self.dialog = dialog
        dialog.show()
        metrics = context.getResources().getDisplayMetrics()
        window = dialog.getWindow()
        window.setBackgroundDrawable(jclass("android.graphics.drawable.ColorDrawable")(0))
        window.setLayout(int(metrics.widthPixels) - 2 * _dp(24), int(int(metrics.heightPixels) * 0.76))
        window.setDimAmount(0.6)

    def close(self):
        if self.dialog is not None:
            self.dialog.dismiss()

    def release(self):
        if self.screen is not None:
            self.screen.dispose()
        self.screen = None
        self.dialog = None


def _info_base():
    from .dl_ui import RemoteRows
    return RemoteRows


class SongInfoScreen(_info_base()):
    """A song's page in the plugin's own style: the cover and the names on top, what matters on a plate, the rest
    folded under "Details"."""

    def __init__(self, owner, path, library_path, fallback, close):
        super().__init__(owner, tr("О песне"))
        self.close_window = close
        self.path = path
        self.library_path = library_path
        self.fallback = fallback
        self.data = None
        self.details = None
        self.details_row = None
        self.plays_view = None
        self.last_view = None
        self.page()
        self.start_body()
        self.note(self.body, tr("Читаю файл…"), size=15, top=16)
        if not path:
            self.draw(None)
            return

        def work():
            try:
                data = read_file(path)
            except Exception as e:
                _log("song info: %s" % e)
                data = None
            run_on_ui_thread(lambda: self.alive and self.guarded(self.draw, data))

        threading.Thread(target=work, name="sculpt-info", daemon=True).start()

    def header(self, large=False, trailing=None):
        """The usual header; its arrow closes the window, there is no screen under it to go back to."""
        owner = self.owner
        row = jclass("android.widget.LinearLayout")(owner.context)
        row.setOrientation(0)
        row.setGravity(16)
        row.setPadding(_dp(8), _dp(8), _dp(8), _dp(8))
        row.addView(self.icon_button(("ic_ab_back",), tr("Закрыть"), self.close_window), owner.params(40, 40))
        self.title_view = self.label(20, "text", True)
        self.title_view.setText(self.title_text)
        place = jclass("android.widget.LinearLayout$LayoutParams")(0, -2, 1.0)
        place.setMarginStart(_dp(8))
        row.addView(self.title_view, place)
        self.subtitle_view = owner.text_view(13)
        return row

    def say(self, text, animation="info"):
        """A bulletin would show in the player, under this window."""
        jclass("android.widget.Toast").makeText(self.owner.context, text, 0).show()

    # -- building blocks

    def value_row(self, plate, label, value, action=None, empty=tr("не указано")):
        """A name over its value, on a plate; a row that leads somewhere has an arrow and opens on a tap."""
        owner = self.owner
        trailing = None
        if action is not None and value:
            trailing = jclass("android.widget.ImageView")(owner.context)
            owner.set_icon(trailing, ("msg_arrowright",))
            self.tint_icon(trailing, "textSecondary")
        row, name, second = self.item_row(plate, value or empty, label, action if value else None,
                                          trailing=trailing, title_role="text" if value else "textSecondary")
        name.setSingleLine(False)
        name.setMaxLines(4)
        if second is not None:
            # the label above, the value under it reads better: here the label is the small line
            column = name.getParent()
            column.removeView(second)
            column.addView(second, 0)
        row.setContentDescription("%s: %s" % (label, value or empty))
        return name

    def plate(self, title=None):
        return self.card(self.body, title)

    # -- the page

    def draw(self, data):
        self.data = data
        self.clear_body()
        owner = self.owner
        Params = jclass("android.widget.LinearLayout$LayoutParams")
        tags = data["tags"] if data else {}
        fallback = self.fallback
        music = owner.plugin.music
        track = music.by_path.get(self.library_path, {}) if self.library_path else {}
        library = self.library_path is not None
        title = tags.get("title") or fallback.get("title") or ""
        artist = tags.get("artist") or fallback.get("artist") or ""
        album = tags.get("album") or fallback.get("album") or ""
        genre = tags.get("genre") or track.get("genre") or ""
        year = year_label(tags.get("date"))

        # the cover and the names
        cover = self.cover_image()
        if cover is not None:
            place = owner.params(200, 200)
            place.gravity = 1
            place.topMargin = _dp(8)
            self.body.addView(cover, place)
        name = self.label(24, "text", True)
        name.setText(title or tr("Без названия"))
        name.setGravity(17)
        name.setSingleLine(False)
        name.setMaxLines(3)
        place = Params(-1, -2)
        place.setMargins(_dp(24), _dp(16), _dp(24), 0)
        self.body.addView(name, place)
        if artist:
            who = self.label(17, "accent")
            who.setText(artist)
            who.setGravity(17)
            if library:
                self.click(who, self.open_group, "artists", artist)
            place = Params(-1, -2)
            place.setMargins(_dp(24), _dp(4), _dp(24), 0)
            self.body.addView(who, place)
        where = " · ".join(p for p in (album, year) if p)
        if where:
            line = self.label(14, "textSecondary")
            line.setText(where)
            line.setGravity(17)
            if library and album:
                self.click(line, self.open_group, "albums", album)
            place = Params(-1, -2)
            place.setMargins(_dp(24), _dp(2), _dp(24), 0)
            self.body.addView(line, place)
        if library:
            edit = self.pill(tr("Изменить теги"), True, self.edit_tags)
            place = Params(-2, -2)
            place.gravity = 1
            place.setMargins(0, _dp(16), 0, 0)
            self.body.addView(edit, place)
        if not self.path:
            self.note(self.body, tr("Песня из чата ещё не скачана, поэтому о самом файле пока ничего не известно."), size=14, top=16)

        # what matters
        main = self.plate(tr("Основное"))
        self.value_row(main, tr("Жанр"), genre, (lambda: self.open_group("genres", genre)) if library else None)
        if data:
            seconds = data["length"] or fallback.get("seconds") or track.get("duration") or 0
            self.value_row(main, tr("Длительность"), clock(seconds) if seconds else "")
            self.value_row(main, tr("Формат"), sound_label(data))
        if library:
            count = music.play_count(self.library_path)
            self.plays_view = self.value_row(main, tr("Сколько раз играла"), times_label(count) if count else "", empty=tr("ни разу"))
            self.last_view = self.value_row(main, tr("Последний раз"), date_label(music.last_played(self.library_path)), empty=tr("ещё не играла"))

        # the rest, folded
        self.details_row, _, _ = self.item_row(self.body, tr("Подробнее"), tr("Файл, номера, ISRC, лейбл, звук, история"),
                                               self.toggle_details, icons=("arrow_more", "msg_arrow_more"))
        self.details = jclass("android.widget.LinearLayout")(owner.context)
        self.details.setOrientation(1)
        self.details.setVisibility(8)
        self.body.addView(self.details, Params(-1, -2))
        body, self.body = self.body, self.details
        try:
            self.draw_details(data, tags, track, library)
        finally:
            self.body = body
        spacer = jclass("android.view.View")(owner.context)
        self.body.addView(spacer, Params(-1, _dp(24)))

    def draw_details(self, data, tags, track, library):
        if self.path:
            files = self.plate(tr("Файл"))
            self.value_row(files, tr("Имя файла"), os.path.basename(self.path), self.copy_path)
            self.value_row(files, tr("Папка"), place_label(self.path), self.copy_path)
            if data and data["size"]:
                self.value_row(files, tr("Размер"), size_label(data["size"]))
        more = self.plate(tr("Теги"))
        album_artist = tags.get("albumartist") or track.get("album_artist") or ""
        self.value_row(more, tr("Исполнитель альбома"), album_artist,
                       (lambda: self.open_group("artists", album_artist)) if library else None)
        self.value_row(more, tr("Номер дорожки"), number_label(tags.get("tracknumber") or track.get("track")))
        self.value_row(more, tr("Номер диска"), number_label(tags.get("discnumber")))
        for key, label in (("isrc", "ISRC"), ("composer", tr("Композитор")), ("lyricist", tr("Автор слов")),
                           ("organization", tr("Лейбл")), ("copyright", tr("Копирайт")), ("bpm", "BPM")):
            if tags.get(key):
                self.value_row(more, label, tags.get(key))
        lyrics = data["lyrics"] if data else ""
        if lyrics:
            lines = len([line for line in lyrics.splitlines() if line.strip()])
            kind = tr("синхронизированный") if SYNCED.search(lyrics) else tr("обычный")
            self.value_row(more, tr("Текст в файле"), tr("есть, %s, строк: %d") % (kind, lines) if lines > 1 else tr("есть, %s") % kind)
        else:
            self.value_row(more, tr("Текст в файле"), "", empty=tr("нет"))
        comment = data["comment"] if data else ""
        if comment:
            link = comment if comment.startswith(("http://", "https://")) else None
            shown = self.value_row(more, tr("Комментарий"), comment, (lambda: self.open_link(link)) if link else None)
            if not link:
                shown.setTextIsSelectable(True)
        if data:
            sound = self.plate(tr("Звук"))
            if data["bitrate"]:
                self.value_row(sound, tr("Битрейт"), tr("~%d кбит/с") % round(data["bitrate"] / 1000.0))
            if data["sample_rate"]:
                self.value_row(sound, tr("Частота дискретизации"), tr("%d Гц") % data["sample_rate"])
            if data["bits"]:
                self.value_row(sound, tr("Битность"), tr("%d бит") % data["bits"])
            if data["codec"]:
                self.value_row(sound, tr("Кодирование"), data["codec"])
            if data["channels"]:
                self.value_row(sound, tr("Каналы"), {1: tr("1, моно"), 2: tr("2, стерео")}.get(data["channels"], str(data["channels"])))
        if library:
            history = self.plate(tr("В медиатеке"))
            self.value_row(history, tr("Добавлена"), date_label(track.get("added")))
            self.value_row(history, tr("Изменена"), date_label((data or {}).get("mtime") or track.get("mtime")))
            clear = self.pill(tr("Очистить историю воспроизведения"), False, self.clear_history)
            place = jclass("android.widget.LinearLayout$LayoutParams")(-2, -2)
            place.setMargins(_dp(20), _dp(12), 0, 0)
            self.body.addView(clear, place)

    def toggle_details(self):
        shown = self.details.getVisibility() == 0
        self.details.setVisibility(8 if shown else 0)
        self.details_row.getChildAt(0).setRotation(0.0 if shown else 180.0)
        self.details_row.setContentDescription(tr("Подробнее, %s") % (tr("развернуть") if shown else tr("свернуть")))

    def cover_image(self):
        known, jpg = self.owner.plugin.music.covers.cached(self.path) if self.path else (True, None)
        if jpg is None:
            return None
        image = jclass("org.telegram.ui.Components.BackupImageView")(self.owner.context)
        image.setRoundRadius(_dp(16))
        image.setImage(jpg, "200_200", None)
        return image

    # -- actions

    def edit_tags(self):
        player, path = self.owner.player, self.library_path
        self.close_window()
        player.edit_tags(path)

    def copy_path(self):
        copy_to_clipboard(self.path)
        self.say(tr("Путь к файлу скопирован"))

    def open_link(self, url):
        context = self.owner.context
        self.close_window()
        jclass("org.telegram.messenger.browser.Browser").openUrl(context, url)

    def open_group(self, kind, name):
        player = self.owner.player
        self.close_window()
        player.open_group(kind, name)

    def clear_history(self):
        music = self.owner.plugin.music
        music.clear_history(self.library_path)
        for view, text in ((self.plays_view, tr("ни разу")), (self.last_view, tr("ещё не играла"))):
            if view is not None:
                view.setText(text)
        self.say(tr("История воспроизведения песни очищена"), "ic_delete")

    def refresh(self):
        pass


def sound_label(data):
    """One line for the sound: the format, then its depth and rate when the file has them."""
    parts = [data.get("format") or ""]
    if data.get("bits"):
        parts.append(tr("%d бит") % data["bits"])
    if data.get("sample_rate"):
        parts.append((tr("%.1f кГц") % (data["sample_rate"] / 1000.0)).replace(".0 ", " ").replace(".", ","))
    if not data.get("bits") and data.get("bitrate"):
        parts.append(tr("~%d кбит/с") % round(data["bitrate"] / 1000.0))
    return " · ".join(p for p in parts if p)
