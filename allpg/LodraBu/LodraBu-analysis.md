# Анализ разработки плагина LodraBu

> Кнопка "выйти" в меню профиля + секция "Аккаунты" в настройках, AyuGram / ExteraGram
> Версия документа: 1.0.3.1
> Актуализировано по официальной доке: https://plugins.exteragram.app/docs

---

## Обновление: сверка с официальной докой

После того как появилась официальная документация SDK, часть выводов ниже была
перепроверена по ней. Коротко: почти всё, что было найдено эмпирически (методом
проб и ошибок), совпало с докой — кроме одного важного момента, см.
[«Расхождение с докой: `find_class` и рефлекшн»](#расхождение-с-докой-find_class-и-рефлекшн).

---

## Что не работало и почему

### 1. `from base_plugin import Hook`
`Hook` не экспортируется из `base_plugin`. Правильный импорт — только `BasePlugin` и `MethodHook`.

```python
# ❌
from base_plugin import BasePlugin, Hook

# ✅
from base_plugin import BasePlugin, MethodHook
```

Подтверждено докой: страница [Xposed Method Hooking](https://plugins.exteragram.app/docs/xposed-hooking)
описывает три способа хука — `MethodHook`, `MethodReplacement` и функциональные хуки через
`before=`/`after=` (которые под капотом оборачиваются в `BaseHook`, тоже потомок `MethodHook`).
Отдельного `Hook` в публичном API нет.

---

### 2. `add_on_create_menu_hook` — не существует
Такого метода в `BasePlugin` нет вообще. Меню нужно добавлять через `hook_method` с рефлекшном.

```python
# ❌
self.add_on_create_menu_hook("org.telegram.ui.ProfileActivity", ...)

# ✅
self.hook_method(method, CreateMenuHook(self))
```

---

### 3. `MenuItemData` / `MenuItemType` — уточнение, а не заблуждение

Раньше здесь было написано, что `MenuItemType.PROFILE_MENU` не существует и что
`MenuItemData` вообще не работает для профиля. Это нужно уточнить.

**Развенчание:** в официальной доке ([Plugin Class → Menu Items](https://plugins.exteragram.app/docs/plugin-class#menu-items))
такого значения `PROFILE_MENU` действительно нет — но есть **`MenuItemType.PROFILE_ACTION_MENU`**,
который выглядит как ровно то, что нам нужно:

```python
self.profile_item_id = self.add_menu_item(
    MenuItemData(
        menu_type=MenuItemType.PROFILE_ACTION_MENU,
        text="Log User Info",
        on_click=self.handle_profile_click,
        icon="user_search",
    )
)
```

Доступные типы меню на сегодня:
`MESSAGE_CONTEXT_MENU`, `DRAWER_MENU`, `MAIN_MENU`, `CHAT_ACTION_MENU`, `PROFILE_ACTION_MENU`.

**Почему мы всё равно не переписали кнопку "выйти" на этот API:**
`PROFILE_ACTION_MENU`, судя по всему, добавляет пункт в меню профиля **любого** пользователя/чата,
а не только своего — а нам критично, чтобы кнопка "выйти" показывалась исключительно на
собственном профиле. В доке нет примера, как ограничить видимость именно "только свой профиль"
(есть `condition: Optional[str]` — MVEL-выражение, но без документированного списка доступных в
нём переменных рискованно на неё полагаться). Наша текущая проверка через `userId == my_id`
внутри хука на `createActionBarMenu` — уже проверенно рабочая и предсказуемая, поэтому кнопку
"выйти" оставили на низкоуровневом хуке, а не переводили на `MenuItemData`.

Для секции "Аккаунты" в настройках `MenuItemType` вообще не подходит — своей вкладки
"Настройки" (`SettingsActivity`) там нет ни одного пункта. Единственный официальный путь —
низкоуровневый Xposed-хук на `fillItems`.

---

### 4. `MethodHook(after=self.callback)` — неверный синтаксис
`MethodHook` не принимает аргументов в конструкторе. Нужно наследоваться и переопределять `after_hooked_method`.

```python
# ❌
self.add_hook(clazz, "method", MethodHook(after=self.callback))

# ✅
class MyHook(MethodHook):
    def __init__(self, plugin):
        self.plugin = plugin

    def after_hooked_method(self, param):
        self.plugin.do_something(param)
```

**Уточнение по доке:** функциональный синтаксис с `after=`/`before=` в SDK всё-таки есть —
но не как аргументы `MethodHook(...)`, а как именованные аргументы самого `self.hook_method(...)`:

```python
self.hook_method(
    some_method,
    before=lambda param: self.log("Method is about to run!"),
    after=lambda param: self.log(f"Method finished with result: {param.getResult()}"),
)
```

Для наших хуков (нужен доступ к `self.plugin` и сложная логика) классовый стиль всё равно удобнее.

---

### 5. `self.add_hook(JavaClass, "method", hook)` — не работает
`add_hook` в этом SDK — это отдельная сущность для перехвата Telegram-запросов/апдейтов по имени
TL-метода (`self.add_hook("TL_messages_setTyping")`, см. [Plugin Class → Event Hooks](https://plugins.exteragram.app/docs/plugin-class#event-hooks)),
а не универсальный способ хукать произвольные Java-методы. Для Java-рефлекшна нужен именно
`self.hook_method(...)`.

```python
# ✅ — явный рефлекшн
Class = jclass("java.lang.Class")
Boolean = jclass("java.lang.Boolean")
clazz = Class.forName("org.telegram.ui.ProfileActivity")
method = clazz.getDeclaredMethod("createActionBarMenu", Boolean.TYPE)
method.setAccessible(True)
self.hook_method(method, MyHook(self))
```

---

### 6-7. Расхождение с докой: `find_class` и рефлекшн

Это самый важный пункт документа — реальное расхождение между тем, что написано в
официальной доке, и тем, что происходит на устройстве.

**Что говорит дока.** Страница [Xposed Method Hooking → The Hooking Process](https://plugins.exteragram.app/docs/xposed-hooking#the-hooking-process)
прямым текстом рекомендует именно так:

```python
from hook_utils import find_class

ActionBarClass = find_class("org.telegram.ui.ActionBar.ActionBar")
if not ActionBarClass:
    self.log("ActionBar class not found!")
    return

CharSequenceClass = find_class("java.lang.CharSequence")
set_title_method = ActionBarClass.getDeclaredMethod("setTitle", CharSequenceClass)
set_title_method.setAccessible(True)
```

И отдельно предупреждает: *"Do not call `getClass()` on the `Class` object — `find_class(...)`
already returns a Java `Class`. Call `getDeclaredMethod(...)` ... directly on that object"*.
То есть по докам `find_class` возвращает полноценный `java.lang.Class`, на котором работает
`getDeclaredMethod`.

**Что происходит по факту.** При точном повторении этого паттерна:

```python
profile_clazz = find_class("org.telegram.ui.ProfileActivity")
create_method = profile_clazz.getDeclaredMethod("createActionBarMenu", Boolean.TYPE)
```

приложение падает с:

```
com.chaquo.python.PyException: AttributeError: type object 'ProfileActivity' has no attribute 'getDeclaredMethod'
```

То есть `find_class(...)` в установленной сборке возвращает не `java.lang.Class`, а
Python/Chaquopy-обёртку над классом (годную для вызова статических методов и конструктора —
как результат `jclass(...)`), но без метаданных рефлекшна.

**Почему это важно понимать, а не просто "доку не читать".** Дока описывает целевое поведение
SDK версии `1.4.4.3`+, но фактическое поведение `find_class` может отличаться в зависимости от
установленной версии SDK/сборки ExteraGram. Раз мы не можем гарантированно проверить версию
SDK на конкретном устройстве заранее, самый предсказуемый путь — не полагаться на
`find_class(...).getDeclaredMethod(...)`, а получать `Class` явно и низкоуровнево:

```python
# ✅ — работает предсказуемо независимо от версии SDK
Class = jclass("java.lang.Class")
clazz = Class.forName("org.telegram.ui.ProfileActivity")
method = clazz.getDeclaredMethod("createActionBarMenu", Boolean.TYPE)
```

**Итоговое правило для этого плагина:**
- `find_class(...)` — используем только там, где нужен сам класс как фабрика (создать
  инстанс через `LogoutActivity()`, вызвать статический метод) — там он и раньше был рабочим.
- `Class.forName(...)` через `jclass("java.lang.Class")` — используем везде, где нужен
  именно `getDeclaredMethod`/`getDeclaredConstructor` для рефлекшна.

Старые пункты 6 и 7 ниже (про `.class_` и обёртку без `getDeclaredMethod`) по сути описывали
ту же проблему раньше докой — вывод совпал.

#### 6. `ProfileActivity.getDeclaredMethod(...)` — не работает напрямую
`find_class`/`jclass` возвращают обёртку над Java-классом, у которой нет `.getDeclaredMethod`.
Для рефлекшна нужен `jclass` из модуля `java` и `Class.forName`.

```python
# ❌
ProfileActivity = find_class("org.telegram.ui.ProfileActivity")
method = ProfileActivity.getDeclaredMethod("createActionBarMenu")

# ✅
from java import jclass
Class = jclass("java.lang.Class")
clazz = Class.forName("org.telegram.ui.ProfileActivity")
method = clazz.getDeclaredMethod("createActionBarMenu", Boolean.TYPE)
```

#### 7. `ProfileActivity.class_` — не существует
В Chaquopy нет атрибута `.class_` для получения Java Class объекта. Только `Class.forName(...)`.

```python
# ❌
ProfileActivity = jclass("org.telegram.ui.ProfileActivity")
method = ProfileActivity.class_.getDeclaredMethod(...)

# ✅
Class = jclass("java.lang.Class")
clazz = Class.forName("org.telegram.ui.ProfileActivity")
```

---

### 8. Хук на `ProfileActivity.onItemClick` — метода не существует
`onItemClick` — это не метод класса `ProfileActivity`, а метод анонимного `ActionBar.ActionBarMenuOnItemClick`
listener-а, который передаётся в `actionBar.setActionBarMenuOnItemClick(...)`. Хукать нужно именно его,
получив через `getActionBarMenuOnItemClick()`.

```python
# ❌ — такого метода нет в ProfileActivity
clazz.getDeclaredMethod("onItemClick", Integer.TYPE)

# ✅ — получаем listener и хукаем его класс
listener = activity.getActionBar().getActionBarMenuOnItemClick()
listener_clazz = Class.forName(listener.getClass().getName())
click_method = listener_clazz.getDeclaredMethod("onItemClick", Integer.TYPE)
click_method.setAccessible(True)
self.plugin.hook_method(click_method, ItemClickHook(self.plugin, activity))
```

Обратите внимание: получение самого `Class` листенера тоже идёт через `Class.forName(...)`,
а не `find_class(...)` — по причине из пункта 6-7 выше.

---

### 9. `get_private_field(R, "msg_leave_solar")` — не тот инструмент для этой задачи

`R$drawable` — это класс со статическими полями-константами, а не поле экземпляра объекта.
`get_private_field(obj, name)` по доке ([Hook Utilities → get_private_field](https://plugins.exteragram.app/docs/hook-utils#get_private_fieldobj-javaobject-field_name-str))
предназначен для **инстанс**-полей: *"Accesses and retrieves the value of a private (or public)
**instance** field from a given object"*. Для статических полей в доке есть отдельная функция —
`get_static_private_field(clazz, field_name)` — но она тоже требует настоящий `Class`-объект
класса, а не Python-обёртку, и всё равно завязана на то, что у вас под рукой правильный `R`
для конкретной сборки (у ExteraGram/AyuGram он может быть в другом пакете и с другими
значениями id, чем в оригинальном Telegram).

Правильный и куда более переносимый способ — получить id ресурса по строковому имени через
`Resources.getIdentifier`, которая не зависит от того, из какого пакета фактически собран `R`:

```python
# ❌
R = find_class("org.telegram.messenger.R$drawable")
icon_id = get_private_field(R, "msg_leave_solar")

# ✅
context = activity.getContext()
pkg = context.getPackageName()
icon_id = context.getResources().getIdentifier("msg_leave_solar", "drawable", pkg)
```

Если иконки с таким именем нет — вернёт `0`, кнопка появится без иконки (не упадёт).

---

### 10. Получение текста кнопки на языке пользователя

Telegram поддерживает кастомные языковые пакеты, загружаемые с серверов. Их строки хранятся не в
`res/values/strings.xml`, а в отдельной базе данных приложения и управляются через `LocaleController`.

#### Почему `res.getString(R.string.LeaveChannel)` не работает для кастомного языка

`context.getResources().getString(id)` читает только встроенные XML-ресурсы приложения. Кастомный
языковой пакет (установленный через Telegram → Настройки → Язык) там не живёт — он загружается
динамически и подменяется через `LocaleController`. Поэтому при кастомном языке `res.getString`
вернёт английскую строку из дефолтного `strings.xml`.

```python
# ❌ — вернёт "Leave channel" даже при кастомном языке
str_id = res.getIdentifier("LeaveChannel", "string", pkg)
label = res.getString(str_id)
```

#### Почему `LocaleController.getString(R.string.LeaveChannel)` тоже не работает

`R.string.LeaveChannel` — это `int`-идентификатор из класса `R` конкретного билда. В
ExteraGram/AyuGram у `R` другой пакет и другие значения id по сравнению с тем, что ожидает
`LocaleController`. Передача int из чужого `R` приводит к тому, что строка не находится или
находится неверная.

```python
# ❌ — R из другого пакета, int не совпадёт
R_string = jclass(pkg + ".R$string")
str_id = R_string.LeaveChannel
label = LocaleController.getString(str_id)
```

#### Правильный способ — строковый ключ

`LocaleController.getString(String key)` — перегрузка, которая ищет строку по текстовому ключу
напрямую в активном языковом пакете (включая кастомный). Именно этот метод используется внутри
самого Telegram в исходниках на GitHub ([ProfileActivity.java, строки 12045–12051](https://github.com/DrKLO/Telegram/blob/009e97356f966bb81eceba113d210230bf383122/TMessagesProj/src/main/java/org/telegram/ui/ProfileActivity.java)).

```python
# ✅ — строковый ключ, работает с кастомным языком
LocaleController = jclass("org.telegram.messenger.LocaleController")
label = LocaleController.getString("LogOut")
```

Ключи строк совпадают с именами атрибутов в `strings.xml` (например `name="LogOut"`). Список всех
ключей — в [strings.xml на GitHub](https://github.com/DrKLO/Telegram/blob/master/TMessagesProj/src/main/res/values/strings.xml).

> **Заблуждение из ранней версии плагина:** для кнопки выхода изначально использовался ключ
> `LeaveChannel` ("выйти с канала") — визуально похожий текст, но не тот. В `SettingsActivity`
> (родном экране настроек) кнопка выхода использует именно ключ `LogOut`
> (`getString(R.string.LogOut)`), это и есть корректный ключ.
>
> Для заголовка секции "Аккаунты" аналогично: не выдуманный ключ `Accounts`, а `SettingsAccounts` —
> ровно тот, что использует сам `SettingsActivity` (`getString(R.string.SettingsAccounts)`).

#### Про фоллбэки на этот ключ

Ранее здесь был рекомендован паттерн с двойным фоллбэком (`LocaleController` → `getIdentifier` →
жёсткая строка). Это было оправдано, пока не было уверенности в правильности ключа. После того
как оба ключа (`LogOut`, `SettingsAccounts`) подтвердились как рабочие на реальном устройстве,
фоллбэки убраны — лишний `try/except`, который не добавляет надёжности, только шум:

```python
# ✅ — минимальный рабочий вариант, ключ подтверждён
LocaleController = jclass("org.telegram.messenger.LocaleController")
label = LocaleController.getString("LogOut")
```

Если в будущем понадобится добавить строку с ключом, в существовании которого нет уверенности —
фоллбэк-паттерн из прошлой версии документа остаётся валидным подходом, просто не для уже
проверенных ключей.

---

## Что работало

### Проверка, что открыт собственный профиль

Кнопка должна появляться только в своём профиле. `ProfileActivity` используется и для чужих
профилей, поэтому нужно сравнивать `userId` активити с id текущего аккаунта через `UserConfig`.

```python
UserConfig = jclass("org.telegram.messenger.UserConfig")
my_id = UserConfig.getInstance(
    activity.getCurrentAccount()
).getClientUserId()

userId = get_private_field(activity, "userId")
if userId != my_id:
    return
```

`getCurrentAccount()` возвращает индекс аккаунта (для мульти-аккаунта), `getClientUserId()` —
Telegram user id текущего аккаунта. `userId` — приватное поле `ProfileActivity`, хранящее id
открытого профиля. Это же поле — `instance`-поле, так что `get_private_field` для него —
правильный инструмент (в отличие от пункта 9 выше про статические поля `R`).

---

### Получение приватного поля `otherItem`
`get_private_field` отлично работает для получения приватных полей экземпляра activity.

```python
from hook_utils import find_class, get_private_field

otherItem = get_private_field(activity, "otherItem")
```

---

### Добавление пункта в меню через `addSubItem`
После получения `otherItem` — стандартный вызов Java-метода работает напрямую.

```python
otherItem.addSubItem(LOGOUT_ITEM_ID, icon_id, "текст")
```

Сигнатура: `addSubItem(int id, int iconResId, CharSequence text)`

---

### Открытие `LogoutActivity` через `presentFragment`
Стандартный способ открыть экран выхода — такой же как в самом Telegram. Это единственное
место в плагине, где `find_class(...)` используется именно как "создать инстанс" — и здесь он
стабильно работает, потому что не требует `getDeclaredMethod`:

```python
LogoutActivity = find_class("org.telegram.ui.LogoutActivity")
if LogoutActivity is None:
    return
fragment = LogoutActivity()
activity.presentFragment(fragment)
```

---

### `param.thisObject` в хуке
Правильное имя поля для получения экземпляра объекта внутри `MethodHook`. Подтверждено докой —
[The `param` Object](https://plugins.exteragram.app/docs/xposed-hooking#the-param-object):
*"`param.thisObject`: instance on which the method was called, or `None` for static methods"*.

```python
# ❌
activity = param.this_object

# ✅
activity = param.thisObject
```

---

## Правильный паттерн для иконки

Иконки передаются как integer resource id. Получить id по имени:

```python
context = activity.getContext()
pkg = context.getPackageName()
icon_id = context.getResources().getIdentifier("msg_leave_solar", "drawable", pkg)
```

Если иконки с таким именем нет — вернёт `0`, кнопка появится без иконки (не упадёт).

---

## Правильный паттерн для хука на анонимный listener

Когда нужный метод находится не в самом классе, а в анонимном listener-е:

```python
# 1. Получить listener через геттер
listener = activity.getActionBar().getActionBarMenuOnItemClick()

# 2. Получить его реальный класс (анонимный, имя вида ProfileActivity$6)
#    через Class.forName, а НЕ find_class — см. раздел про расхождение с докой
Class = jclass("java.lang.Class")
listener_clazz = Class.forName(listener.getClass().getName())

# 3. Получить метод
click_method = listener_clazz.getDeclaredMethod("onItemClick", Integer.TYPE)
click_method.setAccessible(True)

# 4. Повесить хук
self.plugin.hook_method(click_method, MyClickHook(self.plugin, activity))
```

---

## Новое: секция "Аккаунты" в настройках

Второй функционал плагина — секция со списком уже добавленных аккаунтов в общей вкладке
"Настройки" (`SettingsActivity`), с переключением по тапу. В стоке Telegram она есть, в
ExteraGram/AyuGram — нет, поэтому добавляется хуком.

### Хук на `fillItems`

`SettingsActivity.fillItems(ArrayList<UItem> items, UniversalAdapter adapter)` — приватный метод,
который на каждой перерисовке заново собирает список пунктов настроек. После оригинального
вызова (`after_hooked_method`) в уже собранный `items` вставляется наш блок.

```python
Class = jclass("java.lang.Class")
settings_clazz = Class.forName("org.telegram.ui.SettingsActivity")
array_list_cls = Class.forName("java.util.ArrayList")
universal_adapter_cls = Class.forName("org.telegram.ui.Components.UniversalAdapter")

fill_items_method = settings_clazz.getDeclaredMethod(
    "fillItems", array_list_cls, universal_adapter_cls
)
fill_items_method.setAccessible(True)
self.hook_method(fill_items_method, FillItemsHook(self))
```

### Баг первой версии: пункты сливались с соседними

Первая реализация вставляла заголовок, карточки аккаунтов и разделитель (`shadow`) тремя
отдельными вызовами `items.add(index, ...)` на один и тот же индекс. Из-за этого:

- заголовок иногда не добавлялся вовсе (если `UItem.asHeader(...)` падал на "сыром" фоллбэк-тексте —
  исключение проглатывалось общим `except`, а более ранние `items.add(...)` в том же блоке уже
  успевали выполниться);
- не было закрывающего `shadow` **после** карточек — секция визуально сливалась со следующими
  пунктами (в частности, с пунктами других плагинов, тоже вставляющих свои строки около начала
  списка).

### Фикс: собрать блок целиком и вставить одним `addAll`

```python
UItem = jclass("org.telegram.ui.Components.UItem")
AccountCellFactory = jclass("org.telegram.ui.SettingsActivity$AccountCell$Factory")
LocaleController = jclass("org.telegram.messenger.LocaleController")
header_text = LocaleController.getString("SettingsAccounts")

ArrayList = jclass("java.util.ArrayList")
block = ArrayList()
block.add(UItem.asHeader(header_text))
for a in other_accounts:
    block.add(AccountCellFactory.of(ACCOUNT_ITEM_ID_BASE + a, a))
block.add(UItem.asShadow(None))

insert_at = 1 if items.size() > 0 else 0
items.addAll(insert_at, block)
```

Секция теперь самодостаточна: заголовок → карточки → свой собственный закрывающий `shadow`,
независимо от того, что вставляют другие плагины рядом.

### Обработка клика — свои id с большим отступом

Чтобы отличать клики по карточкам аккаунтов от остальных пунктов настроек (у стандартных
пунктов id 1–23), используется диапазон id с отступом:

```python
ACCOUNT_ITEM_ID_BASE = 90000
# id карточки = ACCOUNT_ITEM_ID_BASE + номер_аккаунта
```

Хук вешается на приватный `SettingsActivity.onClick(UItem, View, int, float, float)` — тот же
метод, что обрабатывает клики по всем остальным пунктам настроек:

```python
uitem_cls = Class.forName("org.telegram.ui.Components.UItem")
view_cls = Class.forName("android.view.View")

click_method = settings_clazz.getDeclaredMethod(
    "onClick", uitem_cls, view_cls, Integer.TYPE, Float.TYPE, Float.TYPE
)
click_method.setAccessible(True)
self.hook_method(click_method, ClickHook(self))
```

В обработчике id карточки читается через `get_private_field(item, "id")` (это **instance**-поле
объекта `UItem`, поэтому здесь `get_private_field` — корректный инструмент, в отличие от
статических полей из пункта 9), и если он попадает в наш диапазон — вызывается переключение:

```python
LaunchActivity = jclass("org.telegram.ui.LaunchActivity")
instance = LaunchActivity.instance
if instance is not None:
    instance.switchToAccount(account, True)
```

---

## Новое: сообщение об ошибках вместо логов

Изначально ошибки в хуках просто проглатывались (`except Exception: return`) — молча, без
всякой обратной связи. Хуже того, была добавлена попытка логировать через `self.log(...)` — но
логи полезны только тем, у кого включён logcat, то есть почти никому из обычных пользователей.

Правильный путь для user-facing ошибок в этом SDK — `BulletinHelper` (см.
[Bulletin Helper](https://plugins.exteragram.app/docs/bulletin-helper) и упоминание в
[Client Utilities → Displaying Bulletins](https://plugins.exteragram.app/docs/client-utils#displaying-bulletins)):
всплывающее уведомление внизу экрана с кнопкой, по нажатию на которую можно скопировать
трейс ошибки в буфер обмена.

```python
import traceback
from android_utils import copy_to_clipboard
from ui.bulletin import BulletinHelper

def _show_copyable_error(short_msg, exc, fragment=None):
    try:
        trace = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        BulletinHelper.show_with_button(
            short_msg,
            jclass("org.telegram.messenger.R").raw.error,
            "Copy",
            on_click=lambda: copy_to_clipboard(trace),
            fragment=fragment,
        )
    except Exception:
        pass
```

Сигнатура подтверждена докой:
`show_with_button(text: str, icon_res_id: int, button_text: str, on_click, fragment=None, duration=...)`.
`fragment` необязателен — если не передать, хелпер сам пытается найти активный фрагмент.

Используется точечно — только там, где реально может что-то пойти не так во время работы
(вставка секции аккаунтов, переключение аккаунта, навешивание хука на кнопку выхода). Там, где
падать по сути нечему (простые проверки на `None` при поиске классов на старте плагина) —
оставлен тихий `return`, чтобы не спамить уведомлениями на пустом месте.

---

## Про примитивные типы в сигнатурах

Раньше примитивные типы для `getDeclaredMethod` получались через `jclass(...)`:

```python
Boolean = jclass("java.lang.Boolean")
Integer = jclass("java.lang.Integer")
Float = jclass("java.lang.Float")
```

Дока во всех своих примерах импортирует их напрямую из `java.lang`:

```python
from java.lang import Boolean, Integer, Float
```

Оба варианта рабочие (это подтверждено — `find_class`-эксперимент сломался именно на
`getDeclaredMethod`, а не на способе получения `Boolean.TYPE`), но прямой импорт — это то, что
показано в каждом официальном примере, так что для консистентности с докой в плагине оставлен
именно он.

---

## Итоговый рабочий шаблон хука с рефлекшном

```python
from base_plugin import BasePlugin, MethodHook
from hook_utils import find_class, get_private_field
from java import jclass
from java.lang import Boolean, Integer, Float

class MyHook(MethodHook):
    def __init__(self, plugin):
        self.plugin = plugin

    def after_hooked_method(self, param):
        activity = param.thisObject
        # делаем что нужно

class MyPlugin(BasePlugin):
    def on_plugin_load(self):
        Class = jclass("java.lang.Class")

        clazz = Class.forName("org.telegram.ui.ProfileActivity")
        method = clazz.getDeclaredMethod("createActionBarMenu", Boolean.TYPE)
        method.setAccessible(True)
        self.hook_method(method, MyHook(self))
```

**Правило одной строкой:** `find_class(...)` — для создания инстансов и статических вызовов,
`jclass("java.lang.Class").forName(...)` — для всего, что дальше пойдёт в `getDeclaredMethod`
или `getDeclaredConstructor`.
