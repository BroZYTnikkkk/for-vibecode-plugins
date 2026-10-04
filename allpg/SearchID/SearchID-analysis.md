Анализ разработки плагина SearchID

«Поиск плагинов ExteraGram по ID
Версия плагина: 1.0.1
Источники: Исходники plugins (decompiled code), runtime-классы ExteraGram»

---

Архитектура: как это работает в целом

Я не меняю сам механизм поиска плагинов. ExteraGram уже умеет фильтровать список плагинов по названию, поэтому я встраиваюсь непосредственно в существующий процесс "PluginsActivity.fillItems()".

Основная идея состоит из двух хуков:

1. хук на "PluginsActivity.fillItems()" — я получаю текущий поисковый запрос;
2. хук на "Plugin.getName()" — я временно изменяю возвращаемое имя плагина, если его ID соответствует запросу.

За счёт этого мне не приходится самостоятельно создавать список результатов или повторять внутреннюю логику фильтрации ExteraGram.

Схема получается такой:

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

После завершения "fillItems()" я сбрасываю состояние поиска.

---

Ключевые решения и нюансы

1. Я использую существующий поиск ExteraGram

Вместо того чтобы полностью перехватывать построение списка плагинов, я использую уже существующий механизм "PluginsActivity".

В исходном коде логика поиска основана на имени плагина:

plugin.getName().toLowerCase().contains(query.toLowerCase())

Мне достаточно сделать так, чтобы во время поиска "getName()" возвращал строку, содержащую ID:

SearchID SearchID
cactuslib_mini CactusLib Mini

Если пользователь вводит:

cactuslib_mini

штатный фильтр ExteraGram получает имя:

CactusLib Mini cactuslib_mini

и считает плагин подходящим.

Это позволяет мне добавить поиск по ID без замены самого фильтра.

---

2. Хук на "fillItems" — получение поискового запроса

Я использую reflection Chaquopy:

activity_reflector = activity_class._chaquopy_reflector

fill_methods = activity_reflector.getMethods("fillItems")

"_chaquopy_reflector" здесь важен, потому что обычные Java reflection-методы недоступны непосредственно на Python-обёртке класса так, как они доступны на обычном "java.lang.Class".

"getMethods("fillItems")" возвращает настоящий "java.lang.reflect.Method", который можно передать в:

self.hook_method(...)

Я использую найденный метод как точку входа для "FillItemsHook".

---

3. Почему я читаю "query" из "param.thisObject"

"fillItems()" вызывается на конкретном экземпляре "PluginsActivity".

Поэтому в "before_hooked_method" я получаю:

query = get_private_field(param.thisObject, "query")

и сохраняю его в состоянии плагина:

self.plugin.query = "" if query is None else str(query).strip().lower()

Одновременно устанавливается:

self.plugin.searching = True

Это состояние нужно второму хуку — "Plugin.getName()".

---

4. "before_hooked_method" и "after_hooked_method"

На "fillItems()" я использую оба этапа.

Перед оригинальным методом:

def before_hooked_method(self, param):
    ...

я сохраняю поисковый запрос.

После завершения:

def after_hooked_method(self, param):
    self.plugin.searching = False
    self.plugin.query = ""

я сбрасываю состояние.

Это важно, потому что "Plugin.getName()" вызывается не только непосредственно для поиска. Я не хочу изменять имена плагинов во всех остальных местах приложения.

Поэтому условие второго хука начинается с:

if not self.plugin.searching or not self.plugin.query:
    return

---

5. Хук на "Plugin.getName()"

Второй хук устанавливается на:

plugin_class._chaquopy_reflector.getMethods("getName")

и срабатывает после оригинального "getName()".

Я сначала получаю обычное имя:

name = param.getResult()

а затем ID:

plugin_id = param.thisObject.getId()

Если поисковый запрос находится в ID:

if self.plugin.query in str(plugin_id).lower():
    param.setResult("{} {}".format(name, plugin_id))

я подменяю результат "getName()".

Например:

ID:    zwylib
Name:  ZwyLib

при поиске "zwylib":

ZwyLib zwylib

После этого штатный поиск ExteraGram видит совпадение.

---

6. Почему я не перехватываю сам результат фильтра

Мне не нужно менять "fillItems()" после формирования списка.

Если бы я пытался вручную добавлять или удалять элементы, пришлось бы повторять внутреннюю структуру "UItem", сортировку, разделители и другие детали "PluginsActivity".

Вместо этого я изменяю только данные, которые уже использует оригинальный фильтр.

Получается минимальное вмешательство:

Plugin.getName()
      │
      └── временно → "Name ID"
                    │
                    ▼
             оригинальный filter
                    │
                    ▼
             обычный список

Сам "PluginsActivity" при этом продолжает работать своим кодом.

---

7. R8 и runtime-методы

В исходном коде "PluginsActivity" фильтр находится в Kotlin-generated lambda:

lambda$fillItems$1

Однако в собранном APK этот метод оптимизируется R8.

Поэтому я не могу рассчитывать на наличие исходного имени:

lambda$fillItems$1

в runtime.

Вместо этого я использую реальные runtime-методы:

PluginsActivity.fillItems()
Plugin.getName()

Это делает плагин независимым от конкретного имени сгенерированной Kotlin lambda.

---

8. Почему я не использую R8 lambda как основную точку входа

В runtime "PluginsActivity" содержит несколько методов вида:

$r8$lambda$...

Но наличие нескольких синтетических методов само по себе не даёт надёжной привязки к конкретной части "fillItems()".

Кроме того, R8 может менять их имена и структуру при оптимизации.

"fillItems()" и "Plugin.getName()" являются более подходящими точками:

- первый отвечает за построение списка;
- второй возвращает значение, которое непосредственно участвует в фильтрации.

Поэтому я использую их вместо привязки к synthetic lambda.

---

9. Reflection через "_chaquopy_reflector"

Для получения методов я использую:

activity_class._chaquopy_reflector
plugin_class._chaquopy_reflector

Затем:

fill_methods = activity_reflector.getMethods("fillItems")
get_name_methods = plugin_reflector.getMethods("getName")

Это отличается от обычного:

activity_class.fillItems

который возвращает Chaquopy "JavaMethod", а не объект "java.lang.reflect.Method", ожидаемый "hook_method".

Поэтому для регистрации хуков я использую именно результат "getMethods()".

---

10. Приоритет хуков

Для "fillItems" я использую:

priority=100

Мне важно получить "query" до того, как выполняется основная логика построения списка.

Для "getName" используется:

priority=5

Там я уже изменяю результат после выполнения оригинального метода.

При этом я не вмешиваюсь в сам результат "fillItems".

---

11. Повторная загрузка хука

У "SearchID" есть отдельная особенность lifecycle: после повторного запуска приложения обычный:

self.hook_method(
    fill_methods[0],
    FillItemsHook(self),
    priority=100,
)

может вернуть "None", хотя при первой загрузке тот же метод успешно перехватывается.

Поэтому я оставляю fallback:

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

Таким образом, первая попытка использует конкретный "Method", а при повторной регистрации я использую API "hook_all_methods()".

Это относится именно к регистрации hook и не меняет саму логику поиска.

---

12. Хранение hook handles

Я сохраняю оба установленных хука:

self.hooks = []

После успешной регистрации:

self.hooks.append(fill_hook)
self.hooks.append(name_hook)

Это позволяет снять именно те hook handles, которые были получены при текущей загрузке плагина.

---

13. "on_plugin_unload"

При выгрузке я прохожу по сохранённым hook:

for hook in self.hooks:
    try:
        self.unhook_method(hook)
    except Exception:
        pass

После этого список очищается:

self.hooks = []

Также сбрасывается состояние поиска:

self.searching = False
self.query = ""

Это гарантирует, что после выгрузки объект плагина не остаётся в состоянии активного поиска.

---

14. Почему состояние хранится в самом экземпляре плагина

Я не использую глобальные переменные для:

searching
query

Они относятся непосредственно к текущему экземпляру "SearchIDPlugin".

Поэтому hook получает ссылку:

FillItemsHook(self)

или:

GetNameHook(self)

и обращается к:

self.plugin.searching
self.plugin.query

Это также позволяет корректно сбросить состояние при выгрузке.

---

15. Регистрон поиска

Запрос нормализуется:

str(query).strip().lower()

и ID также приводится к нижнему регистру:

str(plugin_id).lower()

Поэтому поиск не зависит от регистра.

Например:

SearchID
searchid
SEARCHID

будут эквивалентны.

"strip()" дополнительно убирает пробелы по краям запроса.

---

16. Поиск является поиском по вхождению

Я не сравниваю ID через:

query == plugin_id

Вместо этого используется:

query in plugin_id

Поэтому можно искать как полный ID:

cactuslib_mini

так и его часть:

cactus

При этом используется та же семантика "contains", которую уже применяет штатный поиск ExteraGram по названию.

---

17. Обработка ошибок

Для ошибок хуков я использую отдельную функцию:

def _show_error(message, exc):
    ...

Она формирует полный traceback:

trace = "".join(
    traceback.format_exception(
        type(exc),
        exc,
        exc.__traceback__
    )
)

и позволяет скопировать его через Bulletin.

Основная логика хука при этом защищена "try/except", чтобы исключение при обработке одного плагина не ломало весь список.

---

Полная схема работы

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

---

Что я в итоге изменяю в ExteraGram

Я не заменяю менеджер плагинов и не реализую собственный поиск.

Моё вмешательство ограничено двумя точками:

PluginsActivity.fillItems()
Plugin.getName()

На первом этапе я узнаю, выполняется ли сейчас поиск и какой запрос используется.

На втором временно расширяю имя плагина его ID.

Поэтому штатная логика ExteraGram продолжает отвечать за:

- построение списка;
- фильтрацию;
- отображение;
- сортировку;
- создание "UItem";
- обновление списка.

Я добавляю только дополнительный источник совпадения — "Plugin.getId()".

---

Итог

Главная идея "SearchID" — не переписывать существующий поиск ExteraGram, а использовать его собственную логику.

Я перехватываю "fillItems()", сохраняю текущий "query", а во время его выполнения перехватываю "Plugin.getName()".

Если запрос находится в ID плагина, я возвращаю:

Название ID

вместо обычного:

Название

Штатный фильтр ExteraGram воспринимает это как обычное совпадение по имени и оставляет нужный плагин в списке.

За счёт этого поиск по ID добавляется с минимальным вмешательством в существующий код приложения и без необходимости самостоятельно воспроизводить внутреннюю архитектуру "PluginsActivity".