# Spoiler Remover: два способа изменить сообщение

> автор: @JasonVurhyz · версия 1.0.2 · `.plugin`, ~230 строк
> файла плагина в репо нет, здесь разбор и короткие выдержки с указанием автора

маленький плагин, который убирает спойлеры с текста и медиа. ценен тем, что одну и ту же задачу решает двумя разными способами, и по нему хорошо видно разницу между «править при отрисовке» и «править при получении».

---

## два режима

| | визуальный | постоянный |
|---|---|---|
| где | хук `ChatMessageCell.setMessageObject` (before) | `add_hook("TL_updateNewMessage")` и `TL_updateNewChannelMessage` |
| когда | каждый раз, когда ячейка получает сообщение | один раз, когда апдейт приходит с сервера |
| что видно | все сообщения, включая старые | только новые сообщения |
| в базе клиента | без изменений | сохраняется уже без спойлера |
| выключение | спойлеры вернутся после перезапуска | убранные спойлеры не вернутся |

общая часть одна, `_process_message(message)`: выкидывает из `message.entities` все `TL_messageEntitySpoiler` и ставит `message.media.spoiler = False`. возвращает `True`, если что-то поменялось.

## визуальный режим

```python
target_method = ChatMessageCellClass.getDeclaredMethod(
    "setMessageObject",
    MessageObject, MessageObject.GroupedMessages, Boolean.TYPE, Boolean.TYPE, Boolean.TYPE)
self.hook_ref = self.hook_method(target_method, SpoilerCellHook(self))
```
<sub>Spoiler Remover (@JasonVurhyz)</sub>

в `before_hooked_method` плагин правит `param.args[0].messageOwner`, а если что-то поменялось, ставит `forceUpdate = True` и вызывает `resetLayout()`. без этого `MessageObject` отрисовался бы по закэшированной разметке, где спойлер уже посчитан.

важно: правка идёт по `messageOwner` в памяти. «визуальный» он только в том смысле, что база не трогается. пока сообщение в памяти, другие части клиента (пересылка, копирование) тоже увидят его без спойлера.

## постоянный режим

```python
def on_update_hook(self, update_name, account, update):
    message = getattr(update, "message", None)
    if message and self._process_message(message):
        update.message = message
        return HookResult(strategy=HookStrategy.MODIFY, update=update)
    return HookResult()
```
<sub>Spoiler Remover (@JasonVurhyz)</sub>

апдейт меняется до того, как клиент его обработает и сохранит, поэтому дальше сообщение везде живёт без спойлера. для правки входящих это самый «дешёвый» путь: никаких хуков UI.

## нюансы

- режим выбирается диалогом при первом запуске (`AlertDialogBuilder.set_items`, `set_cancelable(False)`). флаг «первый запуск пройден» хранится в отдельном JSON в `getFilesDirFixed()`, хотя для этого хватило бы `set_setting`.
- `_apply_hooks_based_on_mode` сначала снимает всё (`remove_hook`, `unhook_method`), потом ставит нужное. так переключение режима не оставляет двойных хуков.
- в постоянном режиме правки сообщений (`TL_updateEditMessage`, `TL_updateEditChannelMessage`) не перехватываются, так что спойлер, добавленный редактированием, останется. доходят ли до `on_update_hook` сообщения из `getDifference` (пришедшие, пока клиент был выключен), по коду плагина не видно, это стоит проверить на устройстве.

## что взять себе

- сигнатура `ChatMessageCell.setMessageObject` и связка `forceUpdate` + `resetLayout()` для любой правки отображения сообщения;
- `on_update_hook` + `HookStrategy.MODIFY` для правки входящих.
