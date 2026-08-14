# Анализ разработки плагина muztep

> Поиск и отправка треков с muztep.net прямо из чата AyuGram / ExteraGram

---

## Архитектура: как это работает в целом

Плагин перехватывает отправку сообщений через `add_on_send_message_hook`. Если сообщение начинается с `.sm автор - название` — оригинальная отправка отменяется, запускается фоновая задача на `PLUGINS_QUEUE`. Она ищет трек на muztep.net, скачивает его, тегирует метаданными и отправляет как аудио с обложкой и caption.

Если сообщение начинается с `.ism запрос` — отправка тоже отменяется, но вместо скачивания плагин отправляет в чат обычное текстовое сообщение с невидимым маркером в конце. При каждом рендере этого сообщения хук на `ChatMessageCell.setMessageObject` обнаруживает маркер и навешивает на него инлайн-кнопки с результатами поиска. Нажатия на кнопки перехватываются отдельным хуком: пагинация перерисовывает кнопки через `NotificationCenter`, а выбор трека запускает ту же фоновую логику скачивания и отправки, что и `.sm`.

---

## Ключевые решения и нюансы

### 1. `add_on_send_message_hook` — точка входа

`on_send_message_hook` срабатывает до реальной отправки сообщения. `HookStrategy.CANCEL` полностью её блокирует — пользователь отправляет `.sm ...`, но это сообщение не уходит в чат.

```python
result.strategy = HookStrategy.CANCEL
return result
```

Важно возвращать `result` с `CANCEL` **до** запуска фоновой задачи — иначе сообщение успеет уйти.

---

### 2. `run_on_queue` — обязательный уход в фон

Все сетевые операции (поиск, скачивание, парсинг) выполняются в `PLUGINS_QUEUE`, а не в UI-потоке. Без этого приложение замерзает на время запроса.

```python
run_on_queue(
    lambda: self._search_and_send(artist_q, title_q, peer_id),
    PLUGINS_QUEUE,
)
```

`lambda` нужна, потому что `run_on_queue` принимает callable без аргументов — аргументы захватываются из замыкания.

---

### 3. `BypassInternalUriCheck` — почему без него не работает `send_audio`

Telegram проверяет URI файла перед отправкой через `AndroidUtilities.isInternalUri`. Файлы из кэш-директории приложения проходят эту проверку как «внутренние» и блокируются — Telegram не позволяет отправлять их напрямую.

Хук подменяет этот метод, всегда возвращая `False` («не внутренний»):

```python
class BypassInternalUriCheck(MethodReplacement):
    def replace_hooked_method(self, param):
        return False
```

Хук навешивается непосредственно перед отправкой и снимается сразу после — в `finally`, чтобы не влиять на остальную работу приложения.

---

### 4. `_hook_uri` / `_unhook_uri` — минимальное окно хука

```python
self._hook_uri()
try:
    send_audio(...)
finally:
    self._unhook_uri()
```

Хук активен только на время вызова `send_audio`. `finally` гарантирует снятие даже при исключении — иначе `isInternalUri` остался бы сломан до перезапуска приложения.

Отдельный `self._unhook_uri()` в блоке `except` выше нужен для случаев, когда исключение произошло до блока `try/finally` с `send_audio`.

---

### 5. `_search_track` — парсинг первой ссылки из поиска

```python
link = soup.find("a", href=re.compile(r"^/track/"))
```

Берётся первая ссылка на трек из результатов поиска. `re.compile(r"^/track/")` — фильтр по началу href, чтобы не захватить ссылки на артистов и альбомы.

Из URL трека регуляркой извлекается числовой `track_id` — он нужен для API скачивания:

```python
re.search(r"/track/[^/]+/(\d+)", track_url)
```

---

### 6. `_get_track_meta` — данные из `.track-actions`

Страница трека содержит `div.track-actions` с атрибутами `data-title`, `data-artist`, `data-thumb`. Это надёжнее, чем парсить `<h1>` или `og:title`, потому что данные уже очищены и структурированы самим сайтом.

```python
actions = soup.find(class_="track-actions")
title = actions.get("data-title")
artist = actions.get("data-artist")
thumb_url = actions.get("data-thumb")
```

Если парсинг не дал результата — используются query-строки пользователя как fallback:

```python
real_title = meta["title"] if meta["title"] else title_q
real_artist = meta["artist"] if meta["artist"] else artist_q
```

---

### 7. `_get_cdn_url` — получение прямой ссылки на файл

muztep.net предоставляет API для скачивания по `track_id`. Важно передавать `Referer` страницы трека — без него сервер возвращает ошибку.

```python
headers["Referer"] = track["track_url"]
```

---

### 8. `_audio_ext` — определение реального формата файла

Файлы на muztep называются `.mp3`, но по факту являются AAC/M4A. Реальный формат определяется по `Content-Type` ответа сервера:

```python
if ct in ("audio/mp4", "audio/x-m4a", "audio/aac"):
    return ".m4a"
```

Если `Content-Type` не помог — проверяется расширение в URL. Фоллбек — `.mp3`. Это важно для `mutagen`, который определяет формат по расширению.

---

### 9. `_send_track` — ручная сборка `TL_documentAttributeAudio`

Главное техническое решение плагина. `send_audio` из `client_utils` читает метаданные из файловых тегов, но это не всегда надёжно. `_send_track` обходит это, вручную собирая Telegram-объект с нужными данными:

```python
attr = TLRPC.TL_documentAttributeAudio()
attr.duration = self._duration(path)
attr.title = title or ""
attr.performer = artist or ""
attr.flags = attr.flags | 1 | 2
document.attributes.add(attr)
```

`flags = flags | 1 | 2` — битовые флаги, сигнализирующие Telegram что поля `title` (бит 0) и `performer` (бит 1) заполнены. Без этого клиент их игнорирует.

Если `_prepare_document` или импорт `TLRPC` падает — fallback на обычный `send_audio`:

```python
except Exception:
    send_audio(peer_id, path, caption=caption)
    return
```

---

### 10. Обложка через `ImageLoader.scaleAndSaveImage`

```python
bmp = BitmapFactory.decodeByteArray(cover_bytes, 0, len(cover_bytes))
thumb = ImageLoader.scaleAndSaveImage(bmp, 320, 320, 80, False)
document.thumbs.add(thumb)
bmp.recycle()
```

`BitmapFactory.decodeByteArray` — стандартный Android API для декодирования изображения из байтов. `ImageLoader.scaleAndSaveImage` — внутренний метод Telegram, который масштабирует и сохраняет превью в нужном формате, возвращая `TLRPC.PhotoSize`. Именно такой объект ожидает `document.thumbs`.

`bmp.recycle()` обязателен — Bitmap в Android выделяет нативную память, которую GC не освобождает автоматически.

---

### 11. `_duration` через `mutagen`

```python
m = mutagen.File(path)
if m is not None and m.info is not None:
    return float(m.info.length)
```

`mutagen.File` автоматически определяет формат файла и парсит его заголовок. `m.info.length` — длина в секундах. Эта информация нужна для `TL_documentAttributeAudio.duration` — без неё Telegram не показывает прогресс-бар у трека.

---

### 12. Удаление файла: `finally` после отправки, `except` при ошибке

Исходная проблема: `finally` удалял файл сразу, не дожидаясь завершения загрузки, потому что `send_audio` асинхронен — он ставит файл в очередь, а не ждёт окончания отправки.

Решение: файл хранится в `get_cache_dir()` (не во временной памяти, а в кэш-директории приложения). Удаляется в двух случаях:
- В `finally` после `send_audio` — при успешном завершении
- В `except` — при любой ошибке до отправки

```python
try:
    send_audio(...)
finally:
    self._unhook_uri()
    try:
        os.remove(tmp_path)
    except Exception:
        pass
```

---

### 13. Буллетины как индикатор прогресса

Поскольку операция фоновая, пользователь не видит прогресса. Три буллетина решают это:

- `"ищу: ..."` — запрос к поиску отправлен
- `"выгружаю: ..."` — трек найден, скачиваем
- `"найс: ..."` — файл передан в очередь отправки

При ошибке — `BulletinHelper.show_with_button` с кнопкой «Копировать», которая копирует текст исключения в буфер обмена. Это критично для отладки, поскольку плагин работает на реальном устройстве без доступа к логам.

---

### 14. `_safe_name` — безопасное имя файла

```python
name = re.sub(r'[\\/:*?"<>| -]', "_", name)[:120].strip()
return name or "track"
```

Символы из запрещённого набора заменяются на `_`. Лимит 120 символов — защита от слишком длинных путей на Android. Fallback `"track"` — если после очистки строка пустая.

---

### 15. Маркер в тексте сообщения — идентификация без msg_id

Главная проблема инлайна: нам нужно знать какое именно сообщение в чате «наше», чтобы навесить на него кнопки. Получить `msg_id` до отправки невозможно, а после — сообщение уже отрендерилось без кнопок.

Решение — невидимый маркер в тексте:

```python
MARKER = "\u200d\u200c\u200c"
```

`\u200d` (zero-width joiner) и `\u200c` (zero-width non-joiner) — Unicode символы нулевой ширины, визуально невидимы в Telegram. Маркер добавляется в конец текста при отправке:

```python
text = "Результаты по запросу " + query + " " + MARKER
run_on_ui_thread(lambda: send_text(peer_id, text))
```

При каждом рендере ячейки `_CellSetupHook` проверяет `messageText` на наличие маркера и применяет markup. Это работает при любом скролле, перезаходе в чат и перезапуске приложения — маркер хранится в самом сообщении на сервере.

---

### 16. `_CellSetupHook` — хук на `setMessageObject` с `before`

Инлайн-кнопки у обычного (не локального) сообщения применяются через хук на `ChatMessageCell.setMessageObject`. Критично использовать `before_hooked_method`, а не `after`:

```python
class _CellSetupHook(MethodHook):
    def before_hooked_method(self, param):
        msg = param.args[0] if param.args else None
        msg_text = str(getattr(msg, "messageText", "") or "")
        if MARKER not in msg_text:
            return
        self._plugin._rebuild_markup(msg)
```

Причина: внутри `setMessageObject` вызывается `setMessageContent`, который читает `getInlineBotButtons()` → `inlineKeyboardSource`. Это поле заполняется `measureInlineBotButtons()` в конструкторе `MessageObject`. Если применить `reply_markup` в `after` — `setMessageContent` уже отработал с пустым `inlineKeyboardSource`. В `before` мы устанавливаем `reply_markup` + вызываем `measureInlineBotButtons()` до того, как `setMessageContent` читает кнопки.

---

### 17. `_rebuild_markup` — применение markup по сессии

```python
def _rebuild_markup(self, msg_obj):
    dialog_id = int(msg_obj.getDialogId())
    session = self._inline_sessions.get(dialog_id)
    if session is None:
        return
    page = session.get("page", 1)
    tracks = self._get_cached_page_tracks(session, page)
    markup = self._build_markup(dialog_id, tracks, page)
    msg_obj.messageOwner.reply_markup = markup
    msg_obj.messageOwner.flags |= 64
    try:
        msg_obj.measureInlineBotButtons()
    except Exception:
        pass
```

`flags |= 64` — бит 6 (`1 << 6`) сигнализирует Telegram что у сообщения есть `reply_markup`. Без этого флага кнопки не рисуются даже при заполненном `reply_markup`.

`_get_cached_page_tracks` берёт треки только из `meta_cache` — без сетевых запросов. При рендере хук вызывается синхронно в UI-потоке, сеть здесь недопустима.

---

### 18. `_InlineButtonHook` — перехват нажатий на кнопки

Локальные кнопки не отправляют callback на сервер — нажатие перехватывается через хук на `ChatActivity$ChatMessageCellDelegate.didPressBotButton`:

```python
class _InlineButtonHook(MethodHook):
    def before_hooked_method(self, param):
        btn = param.args[1]
        data = bytes(btn.data).decode("utf-8", errors="ignore")
        if not data.startswith("muztep_"):
            return
        param.setResult(None)  # отменяем стандартную обработку
        self._plugin._handle_inline_button(cell, data)
```

`param.setResult(None)` — отменяет стандартное поведение (попытку отправить callback боту). Данные кнопки кодируются в `btn.data` как UTF-8 байты с префиксом `muztep_`.

---

### 19. Структура данных кнопок

```
muztep_pick:{peer_id}:{idx}   — выбор трека (idx относительный, 0-3)
muztep_page:{peer_id}:{page}  — смена страницы
muztep_noop                       — заглушка (пустая кнопка, кнопка страницы)
```

`peer_id` в данных кнопки нужен потому что `_handle_inline_button` должен найти нужную сессию — `dialog_id` из `cell` может отличаться в групповых чатах.

`idx` — относительный индекс (0–3) на текущей странице. Абсолютный индекс вычисляется в `_inline_pick`:

```python
abs_idx = (page - 1) * self.TRACKS_PER_PAGE + idx
```

---

### 20. `_fetch_track_links` + `_fetch_page_tracks` — двухэтапный поиск

При `.ism` сначала запрашивается только список ссылок (один запрос):

```python
def _fetch_track_links(self, query):
    # GET /search/{query} → список {track_url, track_id}
```

Метаданные (artist, title, label для кнопки) запрашиваются лениво — только при открытии страницы, по 4 трека за раз через `_fetch_page_tracks`. Результат кешируется в `session["meta_cache"]` по `track_url`:

```python
cache[url] = {"artist": ..., "title": ..., "label": ..., "thumb_url": ...}
```

При повторном открытии той же страницы — данные берутся из кеша без сетевых запросов.

---

### 21. Сессии: хранение и восстановление

Сессия хранит всё необходимое для восстановления инлайна после перезапуска приложения:

```python
{
    "query": str,
    "all_tracks": [{"track_url": ..., "track_id": ...}],
    "meta_cache": {track_url: {"artist", "title", "label", "thumb_url"}},
    "page": int
}
```

Сессия сохраняется через `self.set_setting("session_{peer_id}", json)` — встроенное персистентное хранилище BasePlugin. Список всех peer_id хранится в `session_peers`.

При `on_plugin_load` все сессии загружаются в память сразу:

```python
def _load_all_sessions(self):
    peers_raw = self.get_setting("session_peers", None)
    peer_ids = json.loads(peers_raw)
    for peer_id in peer_ids:
        saved = self._load_session(peer_id)
        if saved:
            self._inline_sessions[peer_id] = {...}
```

Это критично: если загружать сессию только при открытии чата (`onResume`), сообщения могут отрендериться раньше чем сессия попадёт в память — и `_rebuild_markup` не найдёт сессию.

---

### 22. `_refresh_message_ui` — обновление ячейки при смене страницы

При нажатии `◀`/`▶` сессия обновляется в памяти и на диске, затем `_refresh_message_ui` триггерит перерендер:

```python
def _refresh_message_ui(self, msg_obj):
    account = int(get_user_config().currentAccount)
    dialog_id = msg_obj.getDialogId()
    nc = NotificationCenter.getInstance(account)
    nc.postNotificationName(228, dialog_id)
```

`NotificationCenter.postNotificationName(228, dialog_id)` — уведомление которое заставляет чат перерисовать сообщения. При следующем рендере `_CellSetupHook` применит новый markup из обновлённой сессии. Есть fallback через `notifyDataSetChanged` у RecyclerView.

---

### 23. Хуки через `find_class("java.lang.Class").forName(...)`

Все хуки на Java-классы регистрируются через:

```python
Class = find_class("java.lang.Class")
clazz = Class.forName("org.telegram.ui.Cells.ChatMessageCell")
for method in clazz.getDeclaredMethods():
    if method.getName() == "setMessageObject":
        self.hook_method(method, _CellSetupHook(self))
```

`find_class(...)` возвращает Python-обёртку без `.getDeclaredMethods()`. Правильный путь — `find_class("java.lang.Class")` как точка входа, затем `Class.forName(имя_класса)` для получения настоящего Java `Class` объекта.

---

## Паттерны, которые стоит переиспользовать

### Отмена отправки сообщения и уход в фон

```python
def on_send_message_hook(self, account, params):
    result = HookResult()
    # ...проверки...
    run_on_queue(lambda: self._do_work(peer_id), PLUGINS_QUEUE)
    result.strategy = HookStrategy.CANCEL
    return result
```

---

### Временный хук с гарантированным снятием

```python
self._hook_uri()
try:
    # операция, требующая хука
finally:
    self._unhook_uri()
```

---

### Ручная сборка аудио-документа с метаданными

```python
from org.telegram.tgnet import TLRPC
from client_utils import _prepare_document, send_message

document = _prepare_document(path, "audio/mpeg")
attr = TLRPC.TL_documentAttributeAudio()
attr.title = title
attr.performer = artist
attr.duration = duration
attr.flags = attr.flags | 1 | 2
document.attributes.add(attr)
send_message({"peer": peer_id, "document": document, "path": path, "caption": caption})
```

---

### Fallback-цепочка для ненадёжных операций

```python
try:
    # основной путь (сложный, но полный)
    ...
except Exception:
    # запасной путь (простой, но работает)
    send_audio(peer_id, path, caption=caption)
    return
```

---

### Невидимый маркер для идентификации сообщения

```python
MARKER = "\u200d\u200c\u200c"
text = "Какой-то текст " + MARKER
send_text(peer_id, text)
```

В хуке на рендер:
```python
if MARKER not in str(getattr(msg, "messageText", "") or ""):
    return
```

---

### Локальный инлайн на обычном сообщении

```python
# в before_hooked_method на setMessageObject:
msg_obj.messageOwner.reply_markup = markup      # TL_replyInlineMarkup
msg_obj.messageOwner.flags |= 64               # бит 6 — есть reply_markup
msg_obj.measureInlineBotButtons()              # пересчитать inlineKeyboardSource
```

---

### Перехват нажатий на локальные кнопки

```python
# хук на ChatActivity$ChatMessageCellDelegate.didPressBotButton
param.setResult(None)   # отменить стандартный callback
data = bytes(btn.data).decode("utf-8", errors="ignore")
```

---

### Загрузка всех персистентных данных в on_plugin_load

```python
def on_plugin_load(self):
    self._sessions = {}
    self._load_all_sessions()   # ДО установки хуков
    # ...хуки...
```

Иначе первый рендер произойдёт до восстановления данных.

---

## Полная схема работы (.sm)

```
on_plugin_load()
    └── add_on_send_message_hook()

on_send_message_hook(account, params)
    ├── проверка: starts_with(".sm ")
    ├── парсинг: artist_q, title_q из текста
    ├── run_on_queue → _search_and_send()
    └── HookStrategy.CANCEL

_search_and_send(artist_q, title_q, peer_id)
    ├── BulletinHelper: "ищу: ..."
    ├── _search_track(query)
    │       ├── GET /search/{query}
    │       ├── BeautifulSoup: первая ссылка /track/
    │       └── regex: extract track_id
    ├── _get_track_meta(track_url)
    │       ├── GET track_url
    │       └── BeautifulSoup: .track-actions → data-title, data-artist, data-thumb
    ├── BulletinHelper: "выгружаю: ..."
    ├── _get_cdn_url(track, artist, title)
    │       └── GET /api/download/{track_id} → json.url
    ├── _download(cdn_url, artist, title)
    │       ├── _audio_ext(): Content-Type → .m4a / .mp3
    │       └── streaming download → get_cache_dir()
    ├── GET thumb_url → cover_bytes
    ├── _hook_uri()
    ├── _send_track(peer_id, path, caption, artist, title, cover_bytes)
    │       ├── _prepare_document(path, "audio/mpeg")
    │       ├── TL_documentAttributeAudio: title, performer, duration, flags
    │       ├── BitmapFactory + ImageLoader → document.thumbs
    │       └── send_message({document, path, caption})
    │           [fallback: send_audio(peer_id, path)]
    ├── BulletinHelper: "найс: ..."
    └── finally: _unhook_uri() + os.remove(tmp_path)

on_plugin_unload()
    └── _unhook_uri()
```

---

## Полная схема работы (.ism)

```
on_plugin_load()
    ├── add_on_send_message_hook()
    ├── _load_all_sessions()         ← загружаем все сессии до рендера
    ├── _install_inline_button_hooks()
    ├── _install_cell_setup_hook()
    └── _install_chat_open_hook()

on_send_message_hook: ".ism {query}"
    ├── run_on_queue → _inline_search_start(query, peer_id)
    └── HookStrategy.CANCEL

_inline_search_start(query, peer_id)
    ├── _fetch_track_links(query)    ← GET /search/{query}, список ссылок
    ├── _fetch_page_tracks(session, 1) ← 4 запроса за метой страницы 1
    ├── session → _inline_sessions[peer_id]
    ├── _save_session()              ← персист на диск
    └── send_text(peer_id, text + MARKER)

_CellSetupHook.before_hooked_method  ← при каждом рендере ячейки
    ├── проверка: MARKER in messageText
    └── _rebuild_markup(msg_obj)
            ├── session = _inline_sessions[dialog_id]
            ├── tracks = _get_cached_page_tracks(session, page)
            ├── markup = _build_markup(peer_id, tracks, page)
            ├── msg_obj.messageOwner.reply_markup = markup
            ├── msg_obj.messageOwner.flags |= 64
            └── msg_obj.measureInlineBotButtons()

_InlineButtonHook.before_hooked_method  ← при нажатии кнопки
    ├── decode btn.data → "muztep_pick/page/noop:..."
    ├── param.setResult(None)        ← отменяем стандартный callback
    └── _handle_inline_button(cell, data)
            ├── muztep_pick → _inline_pick(session_peer, idx, peer_id)
            │       ├── abs_idx = (page-1)*4 + idx
            │       ├── meta из кеша или _get_track_meta()
            │       └── → _search_and_send логика (скачать + отправить)
            └── muztep_page → _inline_page(session_peer, page, peer_id, msg_obj)
                    ├── _fetch_page_tracks(session, page)  ← кеш или сеть
                    ├── session["page"] = page
                    ├── _save_session()
                    └── _refresh_message_ui(msg_obj)
                            └── NotificationCenter(228, dialog_id)
                                    └── → _CellSetupHook срабатывает снова
```
