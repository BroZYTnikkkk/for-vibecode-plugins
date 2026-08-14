# Анализ разработки плагина animtou
> Анимированные касания (SuperRipple-эффект) для AyuGram / ExteraGram

---

## Архитектура: как это работает в целом

Плагин перехватывает **каждое касание** на уровне базового класса `android.view.View` через хук на `dispatchTouchEvent`. Это единственная точка входа всех тач-событий в Android — любой `View` во всём приложении проходит через неё. При обнаружении нажатия (ACTION_DOWN) плагин запускает `SuperRipple.animate()` — анимацию, которая уже встроена в Telegram, но нигде не вызывается при обычных касаниях.

Второй слой — хук на конструктор `SuperRipple`, который патчит AGSL-шейдер, убирая непрозрачный фон эффекта.

---

## Ключевые решения и нюансы

### 1. Хук на `View.dispatchTouchEvent` — почему именно он

`dispatchTouchEvent(MotionEvent)` — это корневой метод доставки касаний в Android. Любой `View` (кнопка, список, фрагмент) вызывает именно его первым, до `onTouchEvent` и `onClick`. Хук на этот метод означает, что плагин видит **абсолютно каждое касание** во всём приложении, не привязываясь к конкретному экрану.

Почему не `onTouchEvent`? Потому что `onTouchEvent` может не вызваться, если `dispatchTouchEvent` перехвачен где-то выше. `dispatchTouchEvent` гарантированно вызывается всегда.

```python
view_cls = JClass.forName("android.view.View")
motion_event_cls = JClass.forName("android.view.MotionEvent")
dispatch_method = view_cls.getDeclaredMethod("dispatchTouchEvent", motion_event_cls)
dispatch_method.setAccessible(True)
self.view_unhook_ref = self.hook_method(dispatch_method, _animtouHook(self), priority=5)
```

Важно: `getDeclaredMethod` требует **точную сигнатуру** — передаётся `motion_event_cls` как тип аргумента. Без этого Java-рефлекшн не найдёт метод, потому что перегрузок у `dispatchTouchEvent` нет, но JVM требует явного указания.

---

### 2. `before_hooked_method`, а не `after_hooked_method`

Хук срабатывает **до** выполнения оригинального метода. Это важно: анимация запускается в момент, когда палец только коснулся экрана, а не после того, как `View` обработал касание. Так эффект выглядит мгновенным.

Если бы использовался `after_hooked_method` — анимация запускалась бы с задержкой, после завершения всей цепочки обработки события.

```python
def before_hooked_method(self, param):
    motion_event = param.args[0] if param.args and len(param.args) > 0 else None
    if motion_event is None:
        return
    self.plugin._handle_touch(param.thisObject, motion_event)
```

`param.args[0]` — это `MotionEvent`, первый (и единственный) аргумент `dispatchTouchEvent`. `param.thisObject` — сам `View`, на котором произошло касание.

---

### 3. Дедупликация по токену — защита от шторма событий

`dispatchTouchEvent` вызывается на **каждом** `View` по пути доставки события. Одно касание генерирует десятки вызовов: корневой `DecorView` → `ViewGroup` → дочерний `View` → и т.д. Без защиты один тап запустил бы сотни анимаций.

Решение — токен из `(downTime, actionMasked)`:

```python
token = (int(dt), int(action_masked))
if self._last_down_token is not None and self._last_down_token == token:
    return
self._last_down_token = token
```

`getDownTime()` возвращает время начала касания в мс — оно **одинаково** для всех событий одного тача, включая все промежуточные MOVE и UP, и уникально для каждого нового DOWN. Таким образом, первый `View`, через который прошло событие, ставит токен — все остальные его видят и пропускают.

Фильтр по `action_masked != 0` отсекает всё кроме `ACTION_DOWN` (код 0). MOVE (код 2) и UP (код 1) игнорируются — анимация нужна только при нажатии.

---

### 4. `getRawX/getRawY` вместо `getX/getY`

```python
try:
    rx = float(motion_event.getRawX())
    ry = float(motion_event.getRawY())
except Exception:
    rx = float(motion_event.getX())
    ry = float(motion_event.getY())
```

`getX/getY` возвращают координаты **относительно текущего View** — т.е. локальные. `getRawX/getRawY` — абсолютные экранные координаты. Поскольку хук висит на базовом `View`, а анимация применяется к `DecorView` (корень всего окна), нужны именно абсолютные координаты. Потом они пересчитываются через `screen_to_local`.

`getRawX/getRawY` — более новое API, поэтому есть fallback на `getX/getY` на случай ошибки.

---

### 5. `WindowManagerGlobal.mViews` — получение всех окон

```python
def get_all_decor_views():
    wmg_instance = WindowManagerGlobal.getInstance()
    views = get_private_field(wmg_instance, "mViews")
    for i in range(views.size()):
        result.append(views.get(i))
```

`WindowManagerGlobal` — синглтон Android, который управляет всеми окнами приложения. Приватное поле `mViews` содержит список всех корневых `View` — `DecorView` каждого активного окна (основное окно, диалоги, попапы, клавиатура и т.д.).

Почему это нужно? Telegram может показывать несколько окон одновременно (например, диалог поверх активности). Если запускать рипл только на `getRootView()` текущего `View`, то касание в диалоге не получит анимацию на фоновом окне. Перебирая все `mViews` — анимация везде.

```python
if len(all_views) > 1:
    for view in all_views:
        lx, ly = screen_to_local(view, rx, ry)
        make_ripple(view, lx, ly, self._cached_intensity)
else:
    decor = owner.getRootView()
    make_ripple(decor, rx, ry, self._cached_intensity)
```

Если окно одно — берём `getRootView()` как более простой и надёжный путь.

---

### 6. `screen_to_local` — пересчёт координат

```python
def screen_to_local(view, raw_x, raw_y):
    loc = [0, 0]
    view.getLocationOnScreen(loc)
    return raw_x - loc[0], raw_y - loc[1]
```

`getLocationOnScreen` заполняет массив `[x, y]` абсолютной позицией левого верхнего угла `View` на экране. Вычитая её из экранных координат касания, получаем локальные координаты внутри этого `View`. Без этого анимация была бы смещена, особенно на окнах с нестандартной позицией.

---

### 7. `SuperRipple` — что это и откуда

`SuperRipple` — внутренний класс Telegram из пакета `org.telegram.ui.Stars`. Изначально используется только для эффектов в Stars-покупках. Метод `animate(x, y, intensity)` запускает AGSL-шейдерную анимацию рипла прямо на переданном `View`.

Плагин переиспользует эту готовую систему, не реализуя собственную анимацию.

---

### 8. Кэш `SuperRipple` по `hashCode` — почему нельзя создавать каждый раз

```python
key = view.hashCode()
if key not in _ripple_cache or _ripple_cache[key] is None:
    _ripple_cache[key] = SuperRipple(view)
    if len(_ripple_cache) > _max_cache_size:
        oldest = next(iter(_ripple_cache))
        del _ripple_cache[oldest]
_ripple_cache[key].animate(x, y, intensity)
```

Создание `SuperRipple` — дорогая операция: выделяется буфер для шейдера, компилируется AGSL-код, аллоцируется `RenderEffect`. Если создавать новый объект на каждый тап — это гарантированный UI-джанк и утечка памяти.

Кэш хранит по одному `SuperRipple` на каждый `View` (ключ — `hashCode`). Лимит в 10 записей с вытеснением самой старой (FIFO через `next(iter(...))`) — защита от бесконтрольного роста, если пользователь открывает много разных окон.

`_max_cache_size = 10` — достаточно для всех реальных сценариев (активность + несколько диалогов).

---

### 9. `hook_all_constructors` + патч шейдера

```python
class SuperRippleInitHook(MethodHook):
    def after_hooked_method(self, param):
        code = patch_shader_code(AndroidUtilities.readRes(R.raw.superripple_effect))
        method = param.thisObject.getClass().getDeclaredMethod("setupSizeUniforms", Boolean.TYPE)
        method.setAccessible(True)
        set_private_field(param.thisObject, "shader", shader := RuntimeShader(code))
        method.invoke(param.thisObject, True)
        set_private_field(param.thisObject, "effect", RenderEffect.createRuntimeShaderEffect(shader, "img"))
```

Оригинальный `SuperRipple` использует непрозрачный фон — шейдер прописывает `alpha = 1.0` в обоих return-путях. Для плагина это неприемлемо: рипл должен быть прозрачным (накладываться поверх UI, а не закрашивать его).

`patch_shader_code` меняет два конкретных места в AGSL-коде шейдера:

```python
replace_map = {
    "return half4(0.0, 0.0, 0.0, 1.0);": "return half4(0.0, 0.0, 0.0, 0.0);",
    "return img.eval(uv) + half4(add, add, add, 1.);": "return img.eval(uv) + half4(add, add, add, 0.0);",
}
```

`half4` — это GLSL/AGSL тип `(r, g, b, a)`. Замена `a = 1.0` на `a = 0.0` делает фон шейдера прозрачным, оставляя только сам эффект рипла.

Хук вешается `after_hooked_method` — после того, как конструктор `SuperRipple` отработал и создал объект. Затем через `set_private_field` подменяются приватные поля `shader` и `effect` на пропатченные версии. `setupSizeUniforms` вызывается вручную, чтобы правильно инициализировать uniform-переменные нового шейдера.

---

### 10. `run_on_ui_thread` в `make_ripple`

```python
def make_ripple(view, x, y, intensity):
    def _internal():
        ...
        _ripple_cache[key].animate(x, y, intensity)
    run_on_ui_thread(_internal)
```

Хук `dispatchTouchEvent` выполняется в UI-потоке, но `make_ripple` вызывается из `_handle_touch`, который в принципе может прийти с любого потока. Кроме того, вся работа с `View` в Android обязана выполняться в UI-потоке. `run_on_ui_thread` гарантирует это, выстраивая вызов в `Handler.post`.

Весь тяжёлый код (`hashCode`, обращение к кэшу, вызов `.animate()`) выполняется внутри `_internal` — уже в UI-потоке, что безопасно.

---

### 11. Проверка `Build.VERSION.SDK_INT < TIRAMISU`

```python
if Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU:
    return
```

`RenderEffect` и `RuntimeShader` появились в Android 12 (API 31), но `SuperRipple` в Telegram использует AGSL — Android Graphics Shading Language, появившийся только в Android 13 (API 33, Tiramisu). На более старых версиях просто ничего не происходит, плагин не падает.

---

### 12. `priority=5` при регистрации хука

```python
self.view_unhook_ref = self.hook_method(dispatch_method, _animtouHook(self), priority=5)
```

Приоритет определяет порядок выполнения, если на один метод повешено несколько хуков. `5` — нейтральное значение (не самое высокое и не самое низкое). Это гарантирует, что другие плагины с более высоким приоритетом могут встать перед animtou, не конфликтуя с ним.

---

### 13. Хранение `view_unhook_ref` и чистый `on_plugin_unload`

```python
self.view_unhook_ref = self.hook_method(dispatch_method, _animtouHook(self), priority=5)

def on_plugin_unload(self):
    if self.view_unhook_ref:
        self.unhook_method(self.view_unhook_ref)
        self.view_unhook_ref = None
    _ripple_cache.clear()
```

`hook_method` возвращает handle — ссылку на конкретную регистрацию хука. Сохранять её обязательно: `unhook_method` принимает именно её, а не класс или метод. Без явного снятия хука при выгрузке плагина — хук продолжит работать даже после его отключения, пока приложение не перезапустится.

`_ripple_cache.clear()` освобождает все `SuperRipple`-объекты, предотвращая утечку Java-объектов через Python-кэш.

---

### 14. Кэш интенсивности `_cached_intensity`

```python
def _refresh_settings_cache(self):
    self._cached_intensity = self._as_float(self.get_setting("intensity", "0.55"), 0.55)
```

`get_setting` обращается к хранилищу настроек — это относительно медленная операция (десериализация, I/O). Вызывать её на каждое касание (а касаний — сотни в секунду при скролле) было бы расточительно.

Значение кэшируется в Python-переменную при загрузке и при нажатии кнопки «применить» в настройках. В `_handle_touch` используется уже закэшированное значение — `self._cached_intensity`.

---

### 15. `_as_float` — безопасный парсинг настройки

```python
def _as_float(self, s, default):
    try:
        return float(str(s).strip().replace(",", "."))
    except Exception:
        return default
```

Пользователь вводит интенсивность текстом. `.replace(",", ".")` — обработка локалей, где дробная часть пишется через запятую (русская раскладка). `str(s)` защищает от случая, когда `get_setting` вернул не строку. При любой ошибке — возвращается `default`.

---

### 16. Автообновление через `zwylib`

```python
try:
    import zwylib
    zwylib.add_autoupdater_task(id, UPDATE_CHANNEL_ID, UPDATE_MESSAGE_ID)
except ImportError:
    def delayed_error():
        sleep(2)
        run_on_ui_thread(lambda: BulletinHelper.show_error("animtou доступен, но без автообновления"))
    threading.Thread(target=delayed_error, daemon=True).start()
```

`zwylib` — внешняя библиотека, не гарантированно установленная. Плагин её не требует — работает без неё. При отсутствии показывается ошибка, но через 2 секунды и в отдельном потоке, чтобы не блокировать `on_plugin_load`. `daemon=True` означает, что поток не помешает завершению приложения.

`id` здесь — встроенная Python-функция, но в контексте плагина она переопределена или переиспользована как ссылка на `__id__` — идентификатор плагина.

---

### 17. Открытие настроек через `PluginsController`

```python
PC = find_class("com.exteragram.messenger.plugins.PluginsController")
if PC:
    PC.openPluginSettings(__id__)
```

Встроенного способа открыть настройки собственного плагина из пункта меню нет. Решение — напрямую вызвать `PluginsController.openPluginSettings` с `__id__` плагина. `find_class` возвращает `None` если класс не найден (например, в аю), поэтому есть проверка `if PC`.

---

## Паттерны, которые стоит переиспользовать

### Глобальный перехват касаний

```python
view_cls = JClass.forName("android.view.View")
motion_event_cls = JClass.forName("android.view.MotionEvent")
method = view_cls.getDeclaredMethod("dispatchTouchEvent", motion_event_cls)
method.setAccessible(True)
unhook_ref = self.hook_method(method, MyHook(self), priority=5)
```

### Дедупликация событий через downTime-токен

```python
token = (int(motion_event.getDownTime()), int(motion_event.getActionMasked()))
if self._last_token == token:
    return
self._last_token = token
```

### Получение всех окон приложения

```python
from android.view import WindowManagerGlobal
from hook_utils import get_private_field

wmg = WindowManagerGlobal.getInstance()
views = get_private_field(wmg, "mViews")
all_views = [views.get(i) for i in range(views.size())]
```

### Пересчёт экранных координат в локальные

```python
loc = [0, 0]
view.getLocationOnScreen(loc)
local_x = raw_x - loc[0]
local_y = raw_y - loc[1]
```

### Патч приватных полей после конструктора

```python
class MyInitHook(MethodHook):
    def after_hooked_method(self, param):
        obj = param.thisObject
        set_private_field(obj, "fieldName", new_value)
```

### Кэш Java-объектов с лимитом размера (FIFO)

```python
cache = {}
MAX = 10

key = obj.hashCode()
if key not in cache:
    cache[key] = ExpensiveJavaObject(obj)
    if len(cache) > MAX:
        del cache[next(iter(cache))]
cache[key].doSomething()
```

---

## Полная схема работы

```
on_plugin_load()
    │
    ├── hook_all_constructors(SuperRipple) → SuperRippleInitHook
    │       └── after: патч шейдера (убрать alpha=1.0 → alpha=0.0)
    │
    └── hook_method(View.dispatchTouchEvent) → _animtouHook
            └── before: _handle_touch(view, event)
                    ├── фильтр: только ACTION_DOWN (action_masked == 0)
                    ├── дедупликация по (downTime, action) токену
                    ├── получить raw координаты касания
                    ├── получить все DecorView через WindowManagerGlobal.mViews
                    └── для каждого View:
                            screen_to_local() → make_ripple() → run_on_ui_thread()
                                    └── SuperRipple.animate(x, y, intensity)

on_plugin_unload()
    ├── unhook_method(view_unhook_ref)
    └── _ripple_cache.clear()
```
