# n0transcriber: своя расшифровка голосовых

> автор: @n0white · версия 1.1.0 · `.plugin`, ~410 строк
> файла плагина в репо нет, здесь разбор и короткие выдержки с указанием автора

плагин подменяет штатную кнопку расшифровки голосовых (ту, что в Telegram Premium) и вместо запроса к Telegram отправляет аудио в Groq Whisper. результат кладётся в нативное поле расшифровки, поэтому выглядит и сохраняется так же, как настоящая расшифровка Premium.

---

## схема

```text
ChatMessageCell.updateWaveform ──after──► useTranscribeButton = True   (кнопка видна всегда)

TranscribeButton.onTap ──MethodReplacement──► run_on_queue(onTap)
        │
        ├── уже есть voiceTranscriptionFinal → просто открыть
        │
        └── нет → путь к файлу (FileLoader, ждём до 30 с)
                    → Groq Whisper (verbose_json, отсев сегментов no_speech_prob ≥ 0.6)
                    → [опц.] LLaMA чистит пунктуацию и суржик
                    → MessagesStorage.updateMessageVoiceTranscription
                    → TranscribeButton.finishTranscription  (UI-поток)
```

## ключевые решения

### 1. два хука, а не новая кнопка

- `ChatMessageCell.updateWaveform` (after) ставит приватное поле `useTranscribeButton = True`. без Premium клиент кнопку прячет, а этот хук включает её у всех голосовых.
- `TranscribeButton.onTap` полностью заменяется (`MethodReplacement`). оригинальный метод отправил бы `messages.transcribeAudio` в Telegram и без Premium получил бы ошибку.

своя кнопка не нужна: внешний вид, анимация загрузки и раскрытие текста остаются штатными.

### 2. повтор логики `onTap` в Python

замена метода означает, что всё, что делал оригинал, надо сделать самому: состояния `shouldBeOpen`, `loading`, `clickedToOpen`, `pressed`, а также регистрацию операции в `transcribeOperationsById` / `transcribeOperationsByDialogPosition` по ключу `Objects.hash(account, dialogId, messageId)`. по этим картам клиент потом находит, какой ячейке отдать результат. по структуре код повторяет оригинальный `TranscribeButton.onTap`, это хороший пример того, как «продолжить» чужой Java-метод из Python.

### 3. результат в нативное хранилище

```python
messageObject.messageOwner.voiceTranscriptionOpen  = True
messageObject.messageOwner.voiceTranscriptionFinal = True
MessagesStorage.getInstance(account).updateMessageVoiceTranscription(
    dialogId, messageId, finalText, messageObject.messageOwner)
run_on_ui_thread(lambda: this.finishTranscription(messageObject, finalId, finalText))
```
<sub>n0transcriber (@n0white)</sub>

текст пишется в базу клиента, поэтому при повторном открытии чата расшифровка уже есть и сеть не нужна. ветка «уже расшифровано» в начале `transcribePressed` как раз это и проверяет.

### 4. работа не в UI-потоке

`replace_hooked_method` сразу уходит в `run_on_queue`, потому что дальше идут загрузка файла и HTTP-запросы. всё, что трогает вьюхи (`finishTranscription`, `BulletinHelper`), возвращается через `run_on_ui_thread`.

### 5. ожидание файла

если голосовое ещё не скачано, плагин вызывает `FileLoader.loadFile(document, msg, 1, 0)` и раз в секунду проверяет `getPathToMessage(...).exists()`, до 30 секунд. просто и надёжно, но держит поток очереди. для длинных загрузок лучше подписаться на `NotificationCenter.fileLoaded`.

## нюансы

- `verbose_json` у Whisper отдаёт сегменты с `no_speech_prob`. отбрасывание сегментов с высокой вероятностью тишины убирает типичные «галлюцинации» Whisper на паузах.
- поле `prompt` у Whisper подсказывает словарь (сленг, названия). у Groq лимит на байты, а кириллица в UTF-8 занимает 2 байта на символ, автор держит подсказку короче 896 байт.
- ключ Groq хранится в настройках плагина, а аудио уходит на сервера Groq.

## что взять себе

- как включить скрытую Premium-кнопку через одно приватное поле;
- как заменить метод целиком и сохранить штатный UI;
- как положить свой результат в нативное хранилище клиента, чтобы он переживал перезапуск.
