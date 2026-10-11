# Server Status: своя кнопка в настройках и свой экран

> автор: @YouRooni (@RnPlugins) · версия 1.0.0 · `.plugin`, ~840 строк, только Python
> файла плагина в репо нет, здесь разбор и короткие выдержки с указанием автора

плагин добавляет пункт «Статус серверов» прямо в главный экран настроек exteraGram и открывает по нему свой экран с вкладками: пинг датацентров Telegram, «скорость медиа» и доступность веб-сервисов. главная ценность для разработчика: как встроиться в настройки клиента и как собрать полноценный экран на `UniversalFragment` без Java.

---

## пункт в настройках exteraGram

```python
class FillItemsHook(MethodHook):
    def after_hooked_method(self, param):
        items = param.args[0]
        items.add(UItem.asButton(777, icon, "Статус серверов"))

class OnClickHook(MethodHook):
    def before_hooked_method(self, param):
        if param.args[0].id == 777:
            plugin_self.open_main_screen()
            param.setResult(None)
```
<sub>Server Status (@YouRooni)</sub>

- `MainPreferencesActivity.fillItems(ArrayList, UniversalAdapter)` строит список пунктов. after-хук дописывает свой `UItem` в конец.
- `MainPreferencesActivity.onClick(UItem, View, int, float, float)` получает нажатия. before-хук ловит свой id и через `param.setResult(None)` не пускает клик дальше в оригинал.
- методы берутся через `getDeclaredMethod` с точными типами (`Integer.TYPE`, `Float.TYPE`), а не `hook_all_methods`, чтобы не зацепить перегрузки.

id `777` выбран произвольно. если два плагина возьмут одинаковый id, оба откроют свои экраны, так что лучше брать что-то менее круглое.

## свой экран на `UniversalFragment`

```text
UniversalFragment(delegate)            ← класс exteraGram для экранов плагинов
     │
StatusDelegate(dynamic_proxy(UniversalFragment$UniversalFragmentDelegate))
     ├── fillItems(items, adapter)     ← список UItem: шапка (asFullyCustom), кнопка (asCustom), заголовки, строки
     ├── afterCreateView(view)         ← правки ActionBar: без тени, без заголовка, свои вкладки FilledTabsView
     ├── onFragmentCreate / onFragmentDestroy  ← флаг is_active
     └── onClick / onLongClick / onMenuItemClick / onBackPressed  ← заглушки, интерфейс требует все методы
```

показ: `LaunchActivity.instance.presentFragment(fragment)` в UI-потоке, с фолбэком на `get_last_fragment().presentFragment`.

полезные приёмы:

- **кэш строк.** вьюхи строк создаются один раз и лежат в `row_cache[name]`, при каждом `fillItems` только обновляются (`update_status_row`). без кэша `adapter.update()` пересоздавал бы все вьюхи при каждом обновлении результата.
- **троттлинг обновлений.** фоновые потоки зовут `notify_ui()`, а тот вызывает `adapter.update(False)` не чаще раза в 250 мс (кроме `force=True`). иначе при частых результатах список дёргается.
- **поколения задач.** `_monitor_gen` увеличивается при каждом запуске, а цикл проверки выходит, если номер сменился. тот же приём, что токен в [Time Nickname](time-nickname.md).
- **`is_active`** в делегате: фоновый поток не трогает адаптер, если экран уже закрыт.

## что на самом деле проверяется

| вкладка | как | насколько честно |
|---|---|---|
| сеть | TCP-подключение к IP датацентра на порт 443, время подключения | реальный пинг. через SOCKS5-прокси, если он включён (рукопожатие SOCKS5 написано вручную на `socket`); MTProto-прокси (с `secret`) не поддерживается, тогда подключение идёт напрямую |
| медиа | резолвит служебный канал, получает 5 сообщений с файлами через `channels.getMessages` | **скорость не измеряется.** файлы не скачиваются, числа скорости генерирует `random` |
| веб | `urllib.request.urlopen` к сайту, время ответа | реальная проверка доступности |

для своих плагинов из этого стоит взять UI-часть, а не вкладку медиа. если нужен настоящий замер, файл надо реально загрузить через `FileLoader` и считать байты по `NotificationCenter.fileLoadProgressChanged`.

## что взять себе

- пункт в главных настройках клиента через `fillItems` + `onClick`;
- полноценный экран на `UniversalFragment` из Python;
- кэш вьюх, троттлинг `adapter.update` и номер поколения для фоновых задач.
