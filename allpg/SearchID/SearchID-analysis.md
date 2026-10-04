# Анализ разработки плагина SearchID
> Поиск плагинов ExteraGram по ID
> Версия плагина: 1.0.1
> Источники: исходники plugins (decompiled code), runtime-классы ExteraGram

---

## Архитектура: как это работает в целом

Плагин не меняет сам механизм поиска. ExteraGram уже умеет фильтровать список плагинов по названию, поэтому SearchID встраивается в существующий процесс `PluginsActivity.fillItems()`.

Основная идея — **два хука**:

1. хук на `PluginsActivity.fillItems()` — получает текущий поисковый запрос;
2. хук на `Plugin.getName()` — временно изменяет возвращаемое имя плагина, если его ID соответствует запросу.

За счёт этого не нужно самостоятельно создавать список результатов или повторять внутреннюю логику фильтрации ExteraGram.

```text
Пользователь вводит запрос
        │
        ▼
PluginsActivity.query
        │
        ▼
fillItems()
        │
        ├── устанавливаю searching = True
        │
        └── сохраняю query
                │
                ▼
        Plugin.getName()
                │
                ├── получаю обычное имя
                ├── получаю plugin.getId()
                │
                └── если query содержится в ID:
                        name → "name id"
                                │
                                ▼
                     штатный поиск ExteraGram
                     видит совпадение
```

После завершения `fillItems()` состояние поиска сбрасывается.

---

## Ключевые решения и нюансы

### 1. Используется существующий поиск ExteraGram

Вместо того чтобы полностью перехватывать построение списка плагинов, плагин использует уже существующий механизм `PluginsActivity`.

В исходном коде логика поиска основана на имени плагина:

```java
plugin.getName().toLowerCase().contains(query.toLowerCase())
```

Достаточно сделать так, чтобы во время поиска `getName()` возвращал строку, содержащую ID:

| ID | Name |
|---|---|
| `SearchID` | `SearchID` |
| `cactuslib_mini` | `CactusLib Mini` |

Если пользователь вводит:

```text
cactuslib_mini
```

штатный фильтр ExteraGram получает имя:

```text
CactusLib Mini cactuslib_mini
```

и считает плагин подходящим.

Так поиск по ID добавляется без замены самого фильтра.

---

### 2. Хук на `fillItems` — получение поискового запроса

Используется reflection Chaquopy:

```python
activity_reflector = activity_class._chaquopy_reflector

fill_methods = activity_reflector.getMethods("fillItems")
```

`_chaquopy_reflector` здесь важен: обычные Java reflection-методы недоступны непосредственно на Python-обёртке класса так, как они доступны на обычном `java.lang.Class`.

`getMethods("fillItems")` возвращает настоящий `java.lang.reflect.Method`, который можно передать в:

```python
self.hook_method(...)
```

Найденный метод становится точкой входа для `FillItemsHook`.

---

### 3. Почему `query` читается из `param.thisObject`

`fillItems()` вызывается на конкретном экземпляре `PluginsActivity`. Поэтому в `before_hooked_method` запрос берётся прямо из него:

```python
query = get_private_field(param.thisObject, "query")
```

и сохраняется в состоянии плагина:

```python
self.plugin.query = "" if query is None else str(query).strip().lower()
```

Одновременно устанавливается:

```python
self.plugin.searching = True
```

Это состояние нужно второму хуку — `Plugin.getName()`.

---

### 4. `before_hooked_method` и `after_hooked_method`

На `fillItems()` используются оба этапа.

**Перед** оригинальным методом сохраняется поисковый запрос:

```python
def before_hooked_method(self, param):
    ...
```

**После** завершения состояние сбрасывается:

```python
def after_hooked_method(self, param):
    self.plugin.searching = False
    self.plugin.query = ""
```

Это важно, потому что `Plugin.getName()` вызывается не только непосредственно для поиска, а имена плагинов не должны меняться во всех остальных местах приложения.

Поэтому условие второго хука начинается с:

```python
if not self.plugin.searching or not self.plugin.query:
    return
```

---

### 5. Хук на `Plugin.getName()`

Второй хук устанавливается на:

```python
plugin_class._chaquopy_reflector.getMethods("getName")
```

и срабатывает **после** оригинального `getName()`.

Сначала берётся обычное имя:

```python
name = param.getResult()
```

затем ID:

```python
plugin_id = param.thisObject.getId()
```

Если поисковый запрос находится в ID:

```python
if self.plugin.query in str(plugin_id).lower():
    param.setResult("{} {}".format(name, plugin_id))
```

результат `getName()` подменяется.

Например:

| ID | Name | Запрос | Результат `getName()` |
|---|---|---|---|
| `zwylib` | `ZwyLib` | `zwylib` | `ZwyLib zwylib` |

После этого штатный поиск ExteraGram видит совпадение.

---

### 6. Почему не перехватывается сам результат фильтра

Менять `fillItems()` после формирования списка не нужно.

Если бы список приходилось вручную дополнять или урезать, пришлось бы повторять внутреннюю структуру `UItem`, сортировку, разделители и другие детали `PluginsActivity`.

Вместо этого изменяются только данные, которые уже использует оригинальный фильтр. Получается минимальное вмешательство:

```text
Plugin.getName()
      │
      └── временно → "Name ID"
                    │
                    ▼
             оригинальный filter
                    │
                    ▼
             обычный список
```

Сам `PluginsActivity` при этом продолжает работать своим кодом.

---

### 7. R8 и runtime-методы

В исходном коде `PluginsActivity` фильтр находится в Kotlin-generated lambda:

```text
lambda$fillItems$1
```

Однако в собранном APK этот метод оптимизируется R8, поэтому рассчитывать на исходное имя в runtime нельзя.

Вместо этого используются реальные runtime-методы:

```text
PluginsActivity.fillItems()
Plugin.getName()
```

Плагин не зависит от конкретного имени сгенерированной Kotlin lambda.

---

### 8. Почему R8 lambda не используется как основная точка входа

В runtime `PluginsActivity` содержит несколько методов вида:

```text
$r8$lambda$...
```

Но наличие нескольких синтетических методов само по себе не даёт надёжной привязки к конкретной части `fillItems()`. Кроме того, R8 может менять их имена и структуру при оптимизации.

`fillItems()` и `Plugin.getName()` — более подходящие точки:

- первый отвечает за построение списка;
- второй возвращает значение, которое непосредственно участвует в фильтрации.

Поэтому они используются вместо привязки к synthetic lambda.

---

### 9. Reflection через `_chaquopy_reflector`

Для получения методов используется:

```python
activity_class._chaquopy_reflector
plugin_class._chaquopy_reflector
```

Затем:

```python
fill_methods = activity_reflector.getMethods("fillItems")
get_name_methods = plugin_reflector.getMethods("getName")
```

Это отличается от обычного:

```python
activity_class.fillItems
```

который возвращает Chaquopy `JavaMethod`, а не объект `java.lang.reflect.Method`, ожидаемый `hook_method`.

Поэтому для регистрации хуков используется именно результат `getMethods()`.

---

### 10. Приоритет хуков

| Метод | `priority` | Зачем |
|---|---|---|
| `fillItems` | `100` | `query` нужно получить до выполнения основной логики построения списка |
| `getName` | `5` | результат изменяется уже после выполнения оригинального метода |

В сам результат `fillItems` плагин не вмешивается.

---

### 11. Повторная загрузка хука

У SearchID есть отдельная особенность lifecycle: после повторного запуска приложения обычный:

```python
self.hook_method(
    fill_methods[0],
    FillItemsHook(self),
    priority=100,
)
```

может вернуть `None`, хотя при первой загрузке тот же метод успешно перехватывается.

Поэтому оставлен fallback:

```python
fill_hook = self.hook_method(
    fill_methods[0],
    FillItemsHook(self),
    priority=100,
)

if not fill_hook:
    fill_hook = self.hook_all_methods(
        activity_class,
        "fillItems",
        FillItemsHook(self),
    )
```

Первая попытка использует конкретный `Method`, а при повторной регистрации используется API `hook_all_methods()`.

Это относится именно к регистрации хука и не меняет саму логику поиска.

---

### 12. Хранение hook handles

Оба установленных хука сохраняются:

```python
self.hooks = []
```

После успешной регистрации:

```python
self.hooks.append(fill_hook)
self.hooks.append(name_hook)
```

Это позволяет снять именно те hook handles, которые были получены при текущей загрузке плагина.

---

### 13. `on_plugin_unload`

При выгрузке плагин проходит по сохранённым хукам:

```python
for hook in self.hooks:
    try:
        self.unhook_method(hook)
    except Exception:
        pass
```

После этого список очищается:

```python
self.hooks = []
```

Также сбрасывается состояние поиска:

```python
self.searching = False
self.query = ""
```

Так после выгрузки объект плагина не остаётся в состоянии активного поиска.

---

### 14. Почему состояние хранится в экземпляре плагина

Глобальные переменные для `searching` и `query` не используются. Они относятся непосредственно к текущему экземпляру `SearchIDPlugin`.

Хук получает ссылку на плагин:

```python
FillItemsHook(self)
GetNameHook(self)
```

и обращается к:

```python
self.plugin.searching
self.plugin.query
```

Это также позволяет корректно сбросить состояние при выгрузке.

---

### 15. Регистр поиска

Запрос нормализуется:

```python
str(query).strip().lower()
```

и ID также приводится к нижнему регистру:

```python
str(plugin_id).lower()
```

Поэтому поиск не зависит от регистра — `SearchID`, `searchid` и `SEARCHID` эквивалентны.

`strip()` дополнительно убирает пробелы по краям запроса.

---

### 16. Поиск по вхождению

ID не сравнивается через:

```python
query == plugin_id
```

Вместо этого используется:

```python
query in plugin_id
```

Поэтому можно искать как полный ID:

```text
cactuslib_mini
```

так и его часть:

```text
cactus
```

Применяется та же семантика `contains`, которую уже использует штатный поиск ExteraGram по названию.

---

### 17. Обработка ошибок

Для ошибок хуков используется отдельная функция:

```python
def _show_error(message, exc):
    ...
```

Она формирует полный traceback:

```python
trace = "".join(
    traceback.format_exception(
        type(exc),
        exc,
        exc.__traceback__
    )
)
```

и позволяет скопировать его через Bulletin.

Основная логика хука защищена `try/except`, чтобы исключение при обработке одного плагина не ломало весь список.

---

## Полная схема работы

```text
on_plugin_load()
    │
    ├── find PluginsActivity
    ├── find Plugin
    │
    ├── получить fillItems()
    ├── получить Plugin.getName()
    │
    ├── hook fillItems()
    │       │
    │       └── fallback → hook_all_methods()
    │
    └── hook Plugin.getName()
            │
            ▼
Пользователь вводит текст
            │
            ▼
PluginsActivity.query
            │
            ▼
fillItems.before
            │
            ├── searching = True
            └── query = query.lower()
            │
            ▼
Plugin.getName()
            │
            ├── получить name
            ├── получить id
            │
            └── query in id?
                    │
             ┌──────┴──────┐
             │             │
            нет            да
             │             │
          обычный      "name id"
           name             │
             │              │
             └──────┬───────┘
                    ▼
             штатный фильтр
                    │
                    ▼
             список результатов
                    │
                    ▼
             fillItems.after
                    │
                    ├── searching = False
                    └── query = ""
```

---

## Что изменяется в ExteraGram

Плагин не заменяет менеджер плагинов и не реализует собственный поиск.

Вмешательство ограничено двумя точками:

```text
PluginsActivity.fillItems()
Plugin.getName()
```

- На первом этапе плагин узнаёт, выполняется ли сейчас поиск и какой запрос используется.
- На втором — временно расширяет имя плагина его ID.

Штатная логика ExteraGram продолжает отвечать за:

- построение списка;
- фильтрацию;
- отображение;
- сортировку;
- создание `UItem`;
- обновление списка.

Добавляется только дополнительный источник совпадения — `Plugin.getId()`.

---

## Итог

Главная идея SearchID — не переписывать существующий поиск ExteraGram, а использовать его собственную логику.

Плагин перехватывает `fillItems()`, сохраняет текущий `query`, а во время его выполнения перехватывает `Plugin.getName()`.

Если запрос находится в ID плагина, возвращается:

```text
Название ID
```

вместо обычного:

```text
Название
```

Штатный фильтр ExteraGram воспринимает это как обычное совпадение по имени и оставляет нужный плагин в списке.

За счёт этого поиск по ID добавляется с минимальным вмешательством в существующий код приложения и без необходимости воспроизводить внутреннюю архитектуру `PluginsActivity`.
