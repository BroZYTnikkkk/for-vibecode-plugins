# Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).

"""Song info the way Musicolet shows it: the file, its tags, its sound, its history; authors, albums and genres
open in the library."""

import os
import re
import threading
import time

from android_utils import OnClickListener, copy_to_clipboard, run_on_ui_thread
from java import dynamic_proxy, jclass

from .common import _dp, _log

try:
    import mutagen
except Exception:
    mutagen = None

MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря")
TAG_KEYS = ("title", "album", "artist", "albumartist", "composer", "genre", "tracknumber", "discnumber", "date")
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
    return "%s %d бит" % (name, bits) if bits else name


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
    tail = count % 100
    word = "раз" if 11 <= tail <= 14 else {2: "раза", 3: "раза", 4: "раза"}.get(count % 10, "раз")
    return "%d %s" % (count, word)


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
        parts = ["Внутренняя память"] + [p for p in folder[len(STORAGE):].split("/") if p]
    else:
        parts = [p for p in folder.split("/") if p]
    return " › ".join(parts)


def number_label(value):
    """"3/12" reads "3 из 12"; a zero is what an M4A stores when there is no number at all."""
    first, _, total = str(value or "").strip().partition("/")
    first, total = first.strip(), total.strip()
    if first in ("", "0"):
        return ""
    return "%s из %s" % (first, total) if total not in ("", "0") else first


def year_label(value):
    text = str(value or "").strip()[:10]
    return "" if text in ("", "0", "0000") else text


def size_label(size):
    if size >= 1048576:
        return "%.2f МБ" % (size / 1048576.0)
    return "%d КБ" % (size // 1024)


# -- the dialog --------------------------------------------------------------------------------


class SongInfo:
    def __init__(self, player, path, library_path=None, fallback=None):
        self.player = player
        self.plugin = player.plugin
        self.context = player.context
        self.path = path
        self.library_path = library_path
        self.fallback = fallback or {}
        self.dialog = None
        self.listeners = []
        self.plays_view = None
        self.last_view = None
        Theme = jclass("org.telegram.ui.ActionBar.Theme")
        self.text_color = Theme.getColor(Theme.key_dialogTextBlack)
        self.second_color = Theme.getColor(Theme.key_dialogTextGray3)
        self.link_color = Theme.getColor(Theme.key_dialogTextLink)
        self.line_color = Theme.getColor(Theme.key_divider)

    def show(self):
        def work():
            try:
                data = read_file(self.path) if self.path else None
            except Exception as e:
                _log("song info: %s" % e)
                data = None
            run_on_ui_thread(lambda: self.build(data))

        threading.Thread(target=work, name="sculpt-info", daemon=True).start()

    # -- building

    def text(self, size, color, bold=False):
        view = jclass("android.widget.TextView")(self.context)
        view.setTextSize(1, float(size))
        view.setTextColor(color)
        if bold:
            view.setTypeface(jclass("org.telegram.messenger.AndroidUtilities").bold())
        return view

    def click(self, view, action):
        view.setOnClickListener(OnClickListener(lambda _: self.guarded(action)))
        view.setBackground(jclass("org.telegram.ui.ActionBar.Theme").getSelectorDrawable(False))
        self.listeners.append(view)

    def guarded(self, action):
        try:
            action()
        except Exception as e:
            self.plugin.report("song info", e)

    def field(self, column, label, value, link=None, empty="не указано"):
        """A name over its value; a field that leads somewhere has an arrow after its name and opens on a tap."""
        Params = jclass("android.widget.LinearLayout$LayoutParams")
        block = jclass("android.widget.LinearLayout")(self.context)
        block.setOrientation(1)
        block.setPadding(0, _dp(8), 0, _dp(8))
        head = jclass("android.widget.LinearLayout")(self.context)
        head.setOrientation(0)
        head.setGravity(16)
        name = self.text(15, self.text_color, True)
        name.setText(label)
        head.addView(name)
        shown = str(value) if value else ""
        if link is not None and shown:
            arrow = jclass("android.widget.ImageView")(self.context)
            resources = self.context.getResources()
            package = self.context.getPackageName()
            for icon in ("msg_openin", "msg_link2", "msg_arrowright"):
                resource = resources.getIdentifier(icon, "drawable", package)
                if resource:
                    arrow.setImageResource(resource)
                    break
            arrow.setColorFilter(jclass("android.graphics.PorterDuffColorFilter")(self.link_color, jclass("android.graphics.PorterDuff$Mode").SRC_IN))
            at = Params(_dp(18), _dp(18))
            at.setMarginStart(_dp(8))
            head.addView(arrow, at)
            self.click(block, link)
            block.setContentDescription("%s: %s, открыть" % (label, shown))
        block.addView(head)
        body = self.text(15, self.second_color)
        body.setText(shown or empty)
        if not shown:
            body.setAlpha(0.6)
        block.addView(body)
        column.addView(block, Params(-1, -2))
        return body

    def line(self, column):
        view = jclass("android.view.View")(self.context)
        view.setBackgroundColor(self.line_color)
        place = jclass("android.widget.LinearLayout$LayoutParams")(-1, max(1, _dp(1)))
        place.setMargins(0, _dp(8), 0, _dp(8))
        column.addView(view, place)

    def build(self, data):
        try:
            self.build_dialog(data)
        except Exception as e:
            self.plugin.report("song info", e)

    def build_dialog(self, data):
        Params = jclass("android.widget.LinearLayout$LayoutParams")
        column = jclass("android.widget.LinearLayout")(self.context)
        column.setOrientation(1)
        column.setPadding(_dp(24), _dp(4), _dp(24), _dp(8))
        tags = data["tags"] if data else {}
        fallback = self.fallback
        music = self.plugin.music
        track = music.by_path.get(self.library_path, {}) if self.library_path else {}
        library = self.library_path is not None

        # the file: its cover, its name, where it lies
        if self.path:
            head = jclass("android.widget.LinearLayout")(self.context)
            head.setOrientation(0)
            head.setGravity(16)
            cover = self.cover()
            if cover is not None:
                head.addView(cover, Params(_dp(64), _dp(64)))
            names = jclass("android.widget.LinearLayout")(self.context)
            names.setOrientation(1)
            label = self.text(15, self.text_color, True)
            label.setText("Имя файла")
            names.addView(label)
            value = self.text(14, self.second_color)
            value.setText(os.path.basename(self.path))
            names.addView(value)
            at = Params(0, -2, 1.0)
            if cover is not None:
                at.setMarginStart(_dp(14))
            head.addView(names, at)
            column.addView(head, Params(-1, -2))
            self.field(column, "Местоположение", place_label(self.path), self.copy_path)
            self.line(column)
        else:
            note = self.text(14, self.second_color)
            note.setText("Песня из чата ещё не скачана, поэтому о самом файле пока ничего не известно.")
            column.addView(note)

        # what the tags say
        title = tags.get("title") or fallback.get("title")
        artist = tags.get("artist") or fallback.get("artist")
        album = tags.get("album") or fallback.get("album")
        album_artist = tags.get("albumartist") or track.get("album_artist")
        genre = tags.get("genre") or track.get("genre")
        self.field(column, "Название", title)
        self.field(column, "Альбом", album, (lambda: self.open_group("albums", album)) if library else None)
        self.field(column, "Исполнитель", artist, (lambda: self.open_group("artists", artist)) if library else None)
        self.field(column, "Исполнитель альбома", album_artist, (lambda: self.open_group("artists", album_artist)) if library else None)
        self.field(column, "Композитор", tags.get("composer"))
        self.field(column, "Жанр", genre, (lambda: self.open_group("genres", genre)) if library else None)
        lyrics = data["lyrics"] if data else ""
        if lyrics:
            lines = len([line for line in lyrics.splitlines() if line.strip()])
            kind = "синхронизированный" if SYNCED.search(lyrics) else "обычный"
            self.field(column, "Встроенный текст", "есть, %s, строк: %d" % (kind, lines) if lines > 1 else "есть, %s" % kind)
        else:
            self.field(column, "Встроенный текст", "", empty="нет в файле")
        self.field(column, "Номер дорожки", number_label(tags.get("tracknumber") or track.get("track")))
        self.field(column, "Номер диска", number_label(tags.get("discnumber")))
        self.field(column, "Год", year_label(tags.get("date")))
        comment = data["comment"] if data else ""
        link = comment if comment.startswith(("http://", "https://")) else None
        body = self.field(column, "Комментарий", comment, (lambda: self.open_link(link)) if link else None)
        if comment and not link:
            body.setTextIsSelectable(True)

        # how it sounds
        if data:
            self.line(column)
            seconds = data["length"] or fallback.get("seconds") or track.get("duration") or 0
            self.field(column, "Длительность", clock(seconds) if seconds else "")
            if data["bitrate"]:
                self.field(column, "Битрейт", "~%d кбит/с" % round(data["bitrate"] / 1000.0))
            if data["sample_rate"]:
                self.field(column, "Частота дискретизации", "%d Гц" % data["sample_rate"])
            if data["bits"]:
                self.field(column, "Битность", "%d бит" % data["bits"])
            self.field(column, "Формат", data["format"])
            if data["codec"]:
                self.field(column, "Кодирование", data["codec"])
            if data["channels"]:
                self.field(column, "Каналы", {1: "1, моно", 2: "2, стерео"}.get(data["channels"], str(data["channels"])))
            if data["size"]:
                self.field(column, "Размер", size_label(data["size"]))

        # its history in the library
        if library:
            self.line(column)
            self.field(column, "Добавлена в медиатеку", date_label(track.get("added")))
            self.field(column, "Изменена", date_label((data or {}).get("mtime") or track.get("mtime")))
            self.last_view = self.field(column, "Последний раз играла", date_label(music.last_played(self.library_path)), empty="ещё не играла")
            count = music.play_count(self.library_path)
            self.plays_view = self.field(column, "Сколько раз играла", times_label(count) if count else "", empty="ни разу")
            clear = self.text(14, self.link_color, True)
            clear.setText("ОЧИСТИТЬ ИСТОРИЮ ВОСПРОИЗВЕДЕНИЯ")
            clear.setPadding(0, _dp(12), 0, _dp(12))
            clear.setContentDescription("Очистить историю воспроизведения этой песни")
            self.click(clear, self.clear_history)
            column.addView(clear, Params(-2, -2))

        scroll = jclass("android.widget.ScrollView")(self.context)
        scroll.addView(column)
        builder = jclass("org.telegram.ui.ActionBar.AlertDialog$Builder")(self.context)
        builder.setTitle("Информация о песне")
        builder.setView(scroll)
        if self.library_path:
            builder.setNeutralButton("Редактировать теги", DialogButton(lambda: self.player.edit_tags(self.library_path)))
        builder.setPositiveButton("Готово", DialogButton(None))
        self.dialog = builder.create()
        self.dialog.setOnDismissListener(Dismissed(self.release))
        self.dialog.show()

    def cover(self):
        known, jpg = self.plugin.music.covers.cached(self.path)
        if jpg is None:
            return None
        bitmap = jclass("android.graphics.BitmapFactory").decodeFile(jpg)
        if bitmap is None:
            return None
        image = jclass("org.telegram.ui.Components.BackupImageView")(self.context)
        image.setRoundRadius(_dp(8))
        image.setImageBitmap(bitmap)
        return image

    # -- actions

    def copy_path(self):
        copy_to_clipboard(self.path)
        self.plugin.bulletin(self.player.sheet, "info", "Путь к файлу скопирован")

    def open_link(self, url):
        self.close()
        jclass("org.telegram.messenger.browser.Browser").openUrl(self.context, url)

    def open_group(self, kind, name):
        self.close()
        self.player.open_group(kind, name)

    def clear_history(self):
        self.plugin.music.clear_history(self.library_path)
        for view, text in ((self.plays_view, "ни разу"), (self.last_view, "ещё не играла")):
            if view is not None:
                view.setText(text)
                view.setAlpha(0.6)
        self.plugin.bulletin(self.player.sheet, "ic_delete", "История воспроизведения песни очищена")

    def close(self):
        if self.dialog is not None:
            self.dialog.dismiss()

    def release(self):
        for view in self.listeners:
            try:
                view.setOnClickListener(None)
            except Exception:
                pass
        self.listeners = []
        self.dialog = None
