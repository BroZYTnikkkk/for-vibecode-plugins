# Анализ разработки плагина LodraBu
> Кнопка "выйти" в меню профиля AyuGram / ExteraGram

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

### 3. `MenuItemData` / `MenuItemType.PROFILE_MENU` — не существует
`MenuItemType.PROFILE_MENU` не является валидным значением enum. Этот API работает только для drawer списка чатов (`DRAWER_MENU`), но не для меню профиля.

```python
# ❌ — для профиля не работает
self.add_menu_item(MenuItemData(
    menu_type=MenuItemType.PROFILE_MENU,
    ...
))

# ✅ — для drawer списка чатов работает
self.add_menu_item(MenuItemData(
    menu_type=MenuItemType.DRAWER_MENU,
    ...
))
```

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

---

### 5. `self.add_hook(JavaClass, "method", hook)` — не работает
`add_hook` ожидает строку как первый аргумент, но при передаче строки падал с `Cannot convert str to boolean`. Оказалось — у метода `createActionBarMenu(boolean)` есть аргумент, и `getDeclaredMethod` без указания типа не находит его. Правильный путь — `hook_method` с явным рефлекшном через `java.lang.Class`.

```python
# ❌ — JavaClass объект не принимается
self.add_hook(find_class("org.telegram.ui.ProfileActivity"), "createActionBarMenu", hook)

# ❌ — строка не принимается (ожидался boolean)
self.add_hook("org.telegram.ui.ProfileActivity", "createActionBarMenu", hook)

# ✅ — явный рефлекшн
Class = jclass("java.lang.Class")
Boolean = jclass("java.lang.Boolean")
clazz = Class.forName("org.telegram.ui.ProfileActivity")
method = clazz.getDeclaredMethod("createActionBarMenu", Boolean.TYPE)
method.setAccessible(True)
self.hook_method(method, MyHook(self))
```

---

### 6. `ProfileActivity.getDeclaredMethod(...)` — не работает
`find_class` возвращает Python-обёртку над Java-классом, у которой нет `.getDeclaredMethod`. Для рефлекшна нужен `jclass` из модуля `java` и `Class.forName`.

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

---

### 7. `ProfileActivity.class_` — не существует
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
`onItemClick` — это не метод класса `ProfileActivity`, а метод анонимного `ActionBar.ActionBarMenuOnItemClick` listener-а, который передаётся в `actionBar.setActionBarMenuOnItemClick(...)`. Хукать нужно именно его, получив через `getActionBarMenuOnItemClick()`.

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

---

### 9. `get_private_field(R, "msg_leave_solar")` — не работает
`R$drawable` — это Java inner class. `get_private_field` на ней не даёт id ресурса. Правильный способ — `getIdentifier` через контекст.

```python
# ❌
R = find_class("org.telegram.messenger.R$drawable")
icon_id = get_private_field(R, "msg_leave_solar")

# ✅
context = activity.getContext()
pkg = context.getPackageName()
icon_id = context.getResources().getIdentifier("msg_leave_solar", "drawable", pkg)
```

---

### 10. Получение текста кнопки на языке пользователя

Telegram поддерживает кастомные языковые пакеты, загружаемые с серверов. Их строки хранятся не в `res/values/strings.xml`, а в отдельной базе данных приложения и управляются через `LocaleController`.

#### Почему `res.getString(R.string.LeaveChannel)` не работает для кастомного языка

`context.getResources().getString(id)` читает только встроенные XML-ресурсы приложения. Кастомный языковой пакет (установленный через Telegram → Настройки → Язык) там не живёт — он загружается динамически и подменяется через `LocaleController`. Поэтому при кастомном языке `res.getString` вернёт английскую строку из дефолтного `strings.xml`.

```python
# ❌ — вернёт "Leave channel" даже при кастомном языке
str_id = res.getIdentifier("LeaveChannel", "string", pkg)
label = res.getString(str_id)
```

#### Почему `LocaleController.getString(R.string.LeaveChannel)` тоже не работает

`R.string.LeaveChannel` — это `int`-идентификатор из класса `R` конкретного билда. В ExteraGram/AyuGram у `R` другой пакет и другие значения id по сравнению с тем, что ожидает `LocaleController`. Передача int из чужого `R` приводит к тому, что строка не находится или находится неверная.

```python
# ❌ — R из другого пакета, int не совпадёт
R_string = jclass(pkg + ".R$string")
str_id = R_string.LeaveChannel
label = LocaleController.getString(str_id)
```

#### Правильный способ — строковый ключ

`LocaleController.getString(String key)` — перегрузка, которая ищет строку по текстовому ключу напрямую в активном языковом пакете (включая кастомный). Именно этот метод используется внутри самого Telegram в исходниках на GitHub ([ProfileActivity.java, строки 12045–12051](https://github.com/DrKLO/Telegram/blob/009e97356f966bb81eceba113d210230bf383122/TMessagesProj/src/main/java/org/telegram/ui/ProfileActivity.java)).

```python
# ✅ — строковый ключ, работает с кастомным языком
LocaleController = jclass("org.telegram.messenger.LocaleController")
label = LocaleController.getString("LeaveChannel")
```

Ключи строк совпадают с именами атрибутов в `strings.xml` (например `name="LeaveChannel"`). Список всех ключей — в [strings.xml на GitHub](https://github.com/DrKLO/Telegram/blob/master/TMessagesProj/src/main/res/values/strings.xml).

#### Рекомендуемый паттерн с фоллбэками

```python
try:
    LocaleController = jclass("org.telegram.messenger.LocaleController")
    label = LocaleController.getString("LeaveChannel")
except Exception:
    try:
        str_id = res.getIdentifier("LeaveChannel", "string", pkg)
        label = res.getString(str_id) if str_id != 0 else "выйти"
    except Exception:
        label = "выйти"
```

---

## Что работало

### Проверка, что открыт собственный профиль

Кнопка должна появляться только в своём профиле. `ProfileActivity` используется и для чужих профилей, поэтому нужно сравнивать `userId` активити с id текущего аккаунта через `UserConfig`.

```python
UserConfig = jclass("org.telegram.messenger.UserConfig")
my_id = UserConfig.getInstance(
    activity.getCurrentAccount()
).getClientUserId()

userId = get_private_field(activity, "userId")
if userId != my_id:
    return
```

`getCurrentAccount()` возвращает индекс аккаунта (для мульти-аккаунта), `getClientUserId()` — Telegram user id текущего аккаунта. `userId` — приватное поле `ProfileActivity`, хранящее id открытого профиля.

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
Стандартный способ открыть экран выхода — такой же как в самом Telegram.

```python
LogoutActivity = find_class("org.telegram.ui.LogoutActivity")
fragment = LogoutActivity()
activity.presentFragment(fragment)
```

---

### `param.thisObject` в хуке
Правильное имя поля для получения экземпляра объекта внутри `MethodHook`.

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
listener_clazz = Class.forName(listener.getClass().getName())

# 3. Получить метод
click_method = listener_clazz.getDeclaredMethod("onItemClick", Integer.TYPE)
click_method.setAccessible(True)

# 4. Повесить хук
self.plugin.hook_method(click_method, MyClickHook(self.plugin, activity))
```

---

## Итоговый рабочий шаблон хука с рефлекшном

```python
from base_plugin import BasePlugin, MethodHook
from hook_utils import find_class, get_private_field
from java import jclass

class MyHook(MethodHook):
    def __init__(self, plugin):
        self.plugin = plugin

    def after_hooked_method(self, param):
        activity = param.thisObject
        # делаем что нужно

class MyPlugin(BasePlugin):
    def on_plugin_load(self):
        Class = jclass("java.lang.Class")
        Boolean = jclass("java.lang.Boolean")

        clazz = Class.forName("org.telegram.ui.ProfileActivity")
        method = clazz.getDeclaredMethod("createActionBarMenu", Boolean.TYPE)
        method.setAccessible(True)
        self.hook_method(method, MyHook(self))
```
