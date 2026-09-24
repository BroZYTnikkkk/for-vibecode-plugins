[animtou-analysis-v2.3.0-final.md](https://github.com/user-attachments/files/32606472/animtou-analysis-v2.3.0-final.md)
# Анализ разработки плагина animtou
> Анимированные касания (SuperRipple-эффект) для AyuGram / ExteraGram
> Версия документа: 2.3.0
> Источники: исходник `SuperRipple.java`

---

## Архитектура: как это работает в целом

Плагин перехватывает **каждое касание** на уровне базового класса `android.view.View` через хук на `dispatchTouchEvent`. Это единственная точка входа всех тач-событий в Android — любой `View` во всём приложении проходит через неё. При обнаружении нажатия (ACTION_DOWN) плагин запускает `SuperRipple.animate()` — анимацию, которая уже встроена в Telegram, но нигде не вызывается при обычных касаниях.

Второй слой — патч AGSL-шейдера, который убирает непрозрачный фон эффекта, добавляет хроматическую аберрацию и убирает нежелательное скругление границ. Патч применяется сразу после создания каждого `SuperRipple`, который создаёт сам плагин.

---

## Ключевые решения и нюансы

### 1. Хук на `View.dispatchTouchEvent` — почему именно он

`dispatchTouchEvent(MotionEvent)` — это корневой метод доставки касаний в Android. Любой `View` (кнопка, список, фрагмент) вызывает именно его первым, до `onTouchEvent` и `onClick`. Хук на этот метод означает, что плагин видит **абсолютно каждое касание** во всём приложении, не привязываясь к конкретному экрану.

Почему не `onTouchEvent`? Потому что `onTouchEvent` может не вызваться, если `dispatchTouchEvent` перехвачен где-то выше. `dispatchTouchEvent` вызывается в начале цепочки доставки события.

```python
view_cls = JClass.forName("android.view.View")
motion_event_cls = JClass.forName("android.view.MotionEvent")
dispatch_method = view_cls.getDeclaredMethod("dispatchTouchEvent", motion_event_cls)
dispatch_method.setAccessible(True)
self.view_unhook_ref = self.hook_method(dispatch_method, _animtouHook(self), priority=5)
```

Важно: `getDeclaredMethod` требует точную сигнатуру — передаётся `motion_event_cls` как тип аргумента.

---

### 2. `before_hooked_method`, а не `after_hooked_method`

Хук срабатывает **до** выполнения оригинального метода. Это важно: анимация запускается в момент, когда палец только коснулся экрана, а не после того, как `View` обработал касание.

При этом чтение `param.thisObject` защищено отдельно. Хук находится на базовом `View` и может встретить сторонний View, который Chaquopy не может корректно завернуть в Python-объект. В таком случае конкретное касание пропускается, а сам animtou продолжает работать.

```python
def before_hooked_method(self, param):
    try:
        motion_event = param.args[0] if param.args and len(param.args) > 0 else None
        if motion_event is None:
            return
    except Exception:
        return

    try:
        this_object = param.thisObject
    except Exception:
        return

    try:
        self.plugin._handle_touch(this_object, motion_event)
    except Exception as e:
        _show_copyable_error("animtou: hook error", e)
```

---

### 3. Дедупликация по токену — защита от шторма событий

`dispatchTouchEvent` вызывается на **каждом** `View` по пути доставки события. Одно касание генерирует десятки вызовов: корневой `DecorView` → `ViewGroup` → дочерний `View` → и т.д. Без защиты один тап запустил бы множество анимаций.

Решение — токен из `(downTime, actionMasked)`:

```python
token = (int(dt), int(action_masked))
if self._last_down_token is not None and self._last_down_token == token:
    return
self._last_down_token = token
```

`getDownTime()` одинаков для событий одного тача, поэтому первый `View`, через который прошло событие, ставит токен, а остальные его пропускают.

Фильтр по `action_masked != 0` отсекает всё кроме `ACTION_DOWN`.

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

`getX/getY` возвращают координаты относительно текущего View, а `getRawX/getRawY` — абсолютные экранные координаты. Поскольку анимация применяется к `DecorView`, нужны экранные координаты, которые затем пересчитываются через `screen_to_local`.

Этот fallback оставлен: он касается непосредственно получения координат и имеет рабочую альтернативу.

---

### 5. `WindowManagerGlobal.mViews` — получение всех окон

```python
def get_all_decor_views():
    wmg_instance = WindowManagerGlobal.getInstance()
    views = _get_mviews_field().get(wmg_instance)
    for i in range(views.size()):
        result.append(views.get(i))
```

`WindowManagerGlobal` — синглтон Android, который управляет окнами приложения. Приватное поле `mViews` содержит список корневых View активных окон.

Это нужно, потому что Telegram может показывать несколько окон одновременно. Если запускать ripple только на `getRootView()` текущего View, отдельный диалог или popup может не получить эффект.

Если окно одно, можно использовать корневой View напрямую. При нескольких окнах плагин проходит по `mViews` и пересчитывает координаты для каждого.

#### Кэширование `mViews`

Поиск Java-поля не выполняется при каждом обращении. `Field` сохраняется после первого поиска:

```python
_mviews_field_cache = {"field": None}

def _get_mviews_field():
    if _mviews_field_cache["field"] is not None:
        return _mviews_field_cache["field"]

    Class = jclass("java.lang.Class")
    wmg_class = Class.forName("android.view.WindowManagerGlobal")
    field = wmg_class.getDeclaredField("mViews")
    field.setAccessible(True)
    _mviews_field_cache["field"] = field
    return field
```

Это убирает повторные `getDeclaredField()` и `setAccessible()`.

---

### 6. Отголосок на новые окна

Риппл должен реагировать и на новые окна/диалоги, которые открываются, пока исходная анимация ещё идёт.

Пока рябь активна, плагин некоторое время проверяет `mViews`:

```python
ECHO_WINDOW_MS = 300
ECHO_POLL_INTERVAL_MS = 80
```

Если количество окон изменилось, выполняется обход новых View. Уже известные окна пропускаются.

```python
size = views.size()
if size != _echo_state["last_seen_size"]:
    _echo_state["last_seen_size"] = size
    for i in range(size):
        view = views.get(i)
        key = view.hashCode()
        if key in _echo_state["known_views"]:
            continue
        _echo_state["known_views"].add(key)
        lx, ly = screen_to_local(
            view,
            _echo_state["x"],
            _echo_state["y"]
        )
        make_ripple(
            view,
            lx,
            ly,
            _echo_state["intensity"]
        )
```

Проверка `views.size()` перед полным обходом нужна: в обычных тиках, когда новое окно не появилось, нет смысла заново перебирать весь список.

Раньше я рассматривал hook на `WindowManagerGlobal.addView`, но не использовал его: сигнатура может различаться между версиями Android. Polling по уже используемому `mViews` не требует угадывать такую сигнатуру.

---

### 7. Почему я не делаю отдельный ripple поверх всех окон

Отдельное окно через `WindowManager.addView()` не даёт доступа к содержимому окон под ним. `RenderEffect` и `RuntimeShader` работают с содержимым конкретного View/RenderNode и не могут сами по себе искажать другие окна.

Живой захват экрана через системные механизмы был бы уже другим движком эффекта и для этой задачи не нужен.

Поэтому я использую отдельный `SuperRipple` на каждом появившемся decor View, пока исходная анимация ещё активна. Это не одна физически продолжающаяся волна, а синхронизированный по координатам повтор.

---

### 8. `screen_to_local` — пересчёт координат

```python
def screen_to_local(view, raw_x, raw_y):
    loc = [0, 0]
    view.getLocationOnScreen(loc)
    return raw_x - loc[0], raw_y - loc[1]
```

`getLocationOnScreen` даёт абсолютную позицию левого верхнего угла View. Вычитание этой позиции из экранных координат касания даёт локальные координаты внутри конкретного окна.

---

### 9. `SuperRipple` — что это и откуда

`SuperRipple` — внутренний класс Telegram из `org.telegram.ui.Stars`. Он используется Telegram для shader-анимаций и имеет метод:

```python
ripple.animate(x, y, intensity)
```

Плагин переиспользует готовую Telegram-анимацию, а не реализует собственный ripple-движок.

Я намеренно не ставлю hook на все конструкторы `SuperRipple`: плагин сам создаёт нужные ему экземпляры, поэтому патч можно применять непосредственно к своему объекту.

Это важно, чтобы не менять оригинальные Stars-анимации Telegram, которые создаются в других местах приложения.

---

### 10. Кэш `SuperRipple` по `hashCode`

```python
key = view.hashCode()

if key not in _ripple_cache or _ripple_cache[key] is None:
    _ripple_cache[key] = _make_patched_ripple(view)

    if len(_ripple_cache) > _max_cache_size:
        oldest = next(iter(_ripple_cache))
        del _ripple_cache[oldest]

_ripple_cache[key].animate(x, y, intensity)
```

Создавать `SuperRipple` заново на каждый тап невыгодно: создаются shader/RenderEffect и связанные объекты. Поэтому хранится один объект на View.

Лимит кэша защищает от бесконтрольного роста при появлении большого количества окон. Вытесняется самая старая запись.

Патч применяется в `_make_patched_ripple(view)` сразу после создания объекта.

---

### 11. Патч шейдера — прозрачность, радиус и хроматическая аберрация

Оригинальный AGSL `SuperRipple` использует непрозрачный фон. Я изменяю конкретные участки shader-кода.

Основные изменения:

```python
replace_map = {
    "return half4(0.0, 0.0, 0.0, 1.0);":
        "return half4(0.0, 0.0, 0.0, 0.0);",

    "return img.eval(uv) + half4(add, add, add, 1.);":
        (
            "half2 off = offset * dose;"
            "return half4("
            "img.eval(uv + off).r,"
            "img.eval(uv).g,"
            "img.eval(uv - off).b,"
            "img.eval(uv).a"
            ") + half4(add, add, add, 0.0);"
        ),

    "sdfRoundedBox(uv - size * .5, size * .5, radius)":
        "sdfRoundedBox(uv - size * .5, size * .5, float4(0.0))",
}
```

Перед исходным кодом добавляется:

```glsl
uniform float dose;
```

#### Прозрачность

`alpha = 1.0` заменяется на `alpha = 0.0`, чтобы shader не закрашивал содержимое View непрозрачным фоном.

#### Обнуление radius

Оригинальный `SuperRipple` учитывает `radius`, рассчитанный для его исходного использования. При применении к полноэкранному decor View это приводит к нежелательному поведению по углам.

Поэтому проверка получает `float4(0.0)` вместо исходного `radius`.

#### Хроматическая аберрация

R, G и B берутся из разных координат:

```glsl
img.eval(uv + off).r
img.eval(uv).g
img.eval(uv - off).b
```

Смещение:

```glsl
half2 off = offset * dose;
```

привязано непосредственно к `offset` риппла.

Это лучше, чем ранний вариант:

```glsl
half2 off = (uv - size * .5) * dose;
```

потому что тот вариант зависел от положения относительно центра View, а не от самой волны.

Альфа остаётся:

```glsl
img.eval(uv).a
```

а не постоянным `0.0`. Это важно, потому что `SuperRipple` остаётся установленным как RenderEffect и после окончания самой анимации.

---

### 12. Кэш текста shader

Текст и патч shader не нужно читать и разбирать для каждого нового `SuperRipple`.

Код патча хранится в модульном кэше:

```python
_patched_shader_code = None
```

Первый вызов читает ресурс и выполняет `replace`, последующие получают уже готовую строку.

Так `AndroidUtilities.readRes(...)` и обработка строк не повторяются при создании каждого нового ripple.

---

### 13. Доступ к `SuperRipple.shader` в версии 2.3.0

В исходнике Telegram `SuperRipple` поле `shader` имеет тип `RuntimeShader` и объявлено как `public final`.

В runtime нельзя использовать:

```python
ripple.JA.shader = shader
```

Конкретный объект `SuperRipple` не предоставляет `JA`, поэтому такой путь приводит к:

```text
AttributeError: 'SuperRipple' object has no attribute 'JA'
```

При этом сам патч shader нужен: плагину требуется заменить исходный `RuntimeShader` на новый, содержащий прозрачность и chromatic aberration.

Поэтому я использую обычный Java reflection и кэширую найденный `Field`:

```python
_shader_field = None

def _get_shader_field(ripple):
    global _shader_field

    if _shader_field is None:
        field = ripple.getClass().getDeclaredField("shader")
        field.setAccessible(True)
        _shader_field = field

    return _shader_field
```

После создания нового shader:

```python
shader = RuntimeShader(code)
shader.setFloatUniform("dose", _current_dose)
_get_shader_field(ripple).set(ripple, shader)
```

Поиск поля выполняется один раз, а не при каждом создании ripple.

Я не заменяю этот доступ на `JA`: для конкретного runtime это оказалось несовместимо.

---

### 14. `effect` и `setupSizeUniforms`

`SuperRipple.effect` — публичное поле, поэтому private reflection для него не нужен.

После замены shader создаётся новый эффект:

```python
ripple.effect = RenderEffect.createRuntimeShaderEffect(
    shader,
    "img"
)
```

`setupSizeUniforms(boolean)` при этом остаётся private. Метод нужен для инициализации uniform-параметров нового shader.

Я ищу его один раз и кэширую:

```python
_setup_size_method = None
```

Дальше сохранённый `Method` используется повторно.

Точную сигнатуру `boolean` я оставляю в explicit reflection, потому что здесь важен конкретный overload.

---

### 15. `run_on_ui_thread` в `make_ripple`

```python
def make_ripple(view, x, y, intensity):
    def _internal():
        ...
        _ripple_cache[key].animate(x, y, intensity)

    run_on_ui_thread(_internal)
```

Работа с View и `SuperRipple` выполняется в UI-потоке.

Даже если конкретный hook сейчас вызывается из UI-потока, отдельный `run_on_ui_thread` оставляет границу выполнения безопасной для вызовов из других путей.

---

### 16. Проверка версии Android

В текущей версии плагина отдельной проверки:

```python
Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU
```

нет.

`Build` также не импортируется.

Для данного плагина эта локальная проверка не нужна: `SuperRipple` является частью целевой версии Telegram, для которой предназначен плагин, а сам код не должен дублировать проверку среды в каждой операции.

---

### 17. `priority=5` при регистрации хука

```python
self.view_unhook_ref = self.hook_method(
    dispatch_method,
    _animtouHook(self),
    priority=5
)
```

`priority=5` оставлен. Он определяет порядок выполнения hook'ов на одном методе и не относится к лишним операциям в горячем пути.

---

### 18. `on_plugin_unload`

```python
def on_plugin_unload(self):
    if self.view_unhook_ref:
        self.unhook_method(self.view_unhook_ref)
        self.view_unhook_ref = None

    _ripple_cache.clear()
```

Очистка `_ripple_cache` нужна, потому что Python-кэш удерживает ссылки на Java-объекты.

Я также оставляю явное снятие hook через сохранённый handle. Framework умеет автоматически удалять hook при выгрузке плагина, но явное снятие делает lifecycle самого плагина очевидным и безопасным для повторной загрузки.

---

### 19. Кэш интенсивности

```python
def _refresh_settings_cache(self):
    self._cached_intensity = self._clamp_intensity(
        self._as_float(
            self.get_setting("intensity", "0.55"),
            0.55
        )
    )
```

Значение интенсивности хранится в Python-переменной, чтобы не обращаться к настройкам при каждом тапе.

Диапазон:

```text
0.1–3.0
```

Контрол — `AltSeekbar`, а не текстовое поле.

Для UI используется масштаб:

```python
INTENSITY_UI_MIN = 1
INTENSITY_UI_MAX = 30
INTENSITY_SCALE = 0.1
```

То есть положение 1 соответствует `0.1`, а 30 — `3.0`.

```python
def _on_intensity_change(self, ui_value):
    real = self._clamp_intensity(
        round(float(ui_value)) * self.INTENSITY_SCALE
    )
    self._cached_intensity = real
    self.set_setting("intensity", str(real))
```

---

### 20. `AltSeekbar` — слайдер интенсивности

Штатного `Slider` из Material Components для этого экрана я не использую: прямое создание `com.google.android.material.slider.Slider` приводило к проблеме с Material-атрибутами темы.

Рабочий компонент — exteraGram:

```python
com.exteragram.messenger.preferences.components.AltSeekbar
```

Он вставляется в настройки через `Custom(view=...)`.

```python
def _build_seekbar(
    self,
    minimum,
    maximum,
    default,
    title,
    min_label,
    max_label,
    on_change
):
    from com.exteragram.messenger.preferences.components import AltSeekbar
    from java import dynamic_proxy

    class _Drag(dynamic_proxy(AltSeekbar.OnDrag)):
        def run(this, value):
            on_change(value)

    listener = _Drag()
    self._seekbar_refs.append(listener)

    bar = AltSeekbar(
        activity,
        listener,
        minimum,
        maximum,
        title,
        min_label,
        max_label
    )
    bar.setProgress(float(default))
    return Custom(view=bar)
```

Ссылки на listener сохраняются в `_seekbar_refs`, чтобы proxy-объект не был собран GC.

`minimum` и `maximum` конструктора должны быть `int`.

---

### 21. Кламп интенсивности

```python
INTENSITY_MIN = 0.1
INTENSITY_MAX = 3.0

def _clamp_intensity(self, value):
    return max(
        self.INTENSITY_MIN,
        min(self.INTENSITY_MAX, value)
    )
```

Кламп нужен как для значения из UI, так и для старого/некорректного значения, которое уже могло лежать в настройках.

В 2.3.0 эта защита сохраняется: диапазон, который показывает UI, соответствует диапазону реально применяемого эффекта.

---

### 22. «Доза» — хроматическая аберрация

Доза является uniform-переменной shader:

```glsl
uniform float dose;
```

Она задаётся при создании пропатченного `RuntimeShader`:

```python
shader.setFloatUniform("dose", _current_dose)
```

Поскольку `SuperRipple` кэшируется, изменение дозы должно приводить к созданию новых shader.

```python
_current_dose = 0.01

def _set_current_dose(value):
    global _current_dose
    _current_dose = value
    _ripple_cache.clear()
```

Для UI:

```python
DOSE_UI_MIN = 0
DOSE_UI_MAX = 30
DOSE_SCALE = 0.1
```

`0` означает выключенную аберрацию.

```python
def _on_dose_change(self, ui_value):
    ui_value = self._clamp_dose_ui(round(float(ui_value)))
    _set_current_dose(ui_value * self.DOSE_SCALE)
    self.set_setting("dose", str(ui_value))
```

---

### 23. `_as_float` — безопасный парсинг

```python
def _as_float(self, s, default):
    try:
        return float(str(s).strip().replace(",", "."))
    except Exception:
        return default
```

`replace(",", ".")` позволяет принимать дробные значения с запятой.

Эта функция отвечает только за преобразование значения. Проверка диапазона выполняется отдельно через `_clamp_intensity`.

Fallback здесь оставлен, потому что некорректное пользовательское значение действительно может попасть в настройки.

---

### 24. Автообновление через `zwylib`

```python
try:
    import zwylib
    zwylib.add_autoupdater_task(
        id,
        UPDATE_CHANNEL_ID,
        UPDATE_MESSAGE_ID
    )
except ImportError:
    run_on_ui_thread(
        lambda: BulletinHelper.show_error(
            "animtou доступен, но без автообновления"
        ),
        2000
    )
```

`zwylib` необязателен. При его отсутствии основная функциональность плагина продолжает работать.

Ручной Python-thread с `sleep(2)` здесь не нужен: задержка уже поддерживается `run_on_ui_thread(func, delay)`.

---

### 25. Открытие настроек через `PluginsController`

```python
PC = find_class(
    "com.exteragram.messenger.plugins.PluginsController"
)

if PC:
    PC.openPluginSettings(__id__)
```

Проверка `PC` оставлена, потому что класс может отсутствовать в другом окружении.

---

## Что я не стал убирать в 2.3.0

Я не удаляю защиту только потому, что она выглядит как «лишняя».

Оставлены проверки и fallback'и, у которых есть реальный сценарий:

- получение `param.thisObject`;
- получение координат;
- необязательный `zwylib`;
- `PluginsController`;
- пользовательский парсинг чисел;
- Java reflection;
- работа с UI-thread;
- очистка кэшей;
- дедупликация событий;
- ограничение размера кэша.

Удалены только конструкции, которые не выполняли полезной работы:

- неиспользуемые импорты `Any`, `List`;
- `Build` вместе с локальной проверкой Android;
- `_last_up_token`;
- пустой `after_hooked_method`;
- повторный поиск уже найденных reflection `Field`/`Method`.

---

## Полная схема работы — версия 2.3.0

```text
on_plugin_load()
    │
    ├── загрузка настроек в кэш
    │
    └── hook View.dispatchTouchEvent
            │
            └── before_hooked_method
                    │
                    ├── получить MotionEvent
                    ├── получить thisObject
                    ├── только ACTION_DOWN
                    ├── дедупликация по (downTime, action)
                    ├── получить raw X/Y
                    │
                    └── получить WindowManagerGlobal.mViews
                            │
                            └── Field берётся из кэша
                                    │
                                    └── для каждого DecorView
                                            │
                                            ├── screen_to_local()
                                            │
                                            └── make_ripple()
                                                    │
                                                    └── UI thread
                                                            │
                                                            ├── cache hit
                                                            │     └── animate()
                                                            │
                                                            └── cache miss
                                                                  │
                                                                  ├── SuperRipple(view)
                                                                  ├── получить shader Field из кэша
                                                                  ├── получить shader code из кэша
                                                                  ├── создать RuntimeShader
                                                                  ├── установить dose
                                                                  ├── заменить shader
                                                                  ├── создать RenderEffect
                                                                  ├── получить setupSizeUniforms
                                                                  │     из кэша
                                                                  ├── setup uniforms
                                                                  └── animate()

echo polling
    │
    ├── пока ripple активен
    ├── взять mViews
    ├── сравнить size()
    └── если появилось новое окно
            ├── найти новый DecorView
            ├── пересчитать координаты
            └── создать синхронизированный ripple

on_plugin_unload()
    │
    ├── снять сохранённый hook
    └── очистить _ripple_cache
```

---

## Паттерны, которые стоит переиспользовать

### Глобальный перехват касаний

```python
view_cls = JClass.forName("android.view.View")
motion_event_cls = JClass.forName("android.view.MotionEvent")
method = view_cls.getDeclaredMethod(
    "dispatchTouchEvent",
    motion_event_cls
)
method.setAccessible(True)
unhook_ref = self.hook_method(
    method,
    MyHook(self),
    priority=5
)
```

### Дедупликация событий через downTime-токен

```python
token = (
    int(motion_event.getDownTime()),
    int(motion_event.getActionMasked())
)

if self._last_token == token:
    return

self._last_token = token
```

### Получение всех окон приложения

```python
wmg = WindowManagerGlobal.getInstance()
field = _get_mviews_field()
views = field.get(wmg)
all_views = [views.get(i) for i in range(views.size())]
```

### Пересчёт экранных координат в локальные

```python
loc = [0, 0]
view.getLocationOnScreen(loc)
local_x = raw_x - loc[0]
local_y = raw_y - loc[1]
```

### Кэширование reflection

```python
_field = None

def get_field(obj):
    global _field

    if _field is None:
        _field = obj.getClass().getDeclaredField("name")
        _field.setAccessible(True)

    return _field
```

---

## Открытые вопросы

### Риппл не срабатывает при закрытии некоторых контекстных меню

При открытом меню «три точки» (в чате, в профиле, в канале) тап вне меню закрывает его, но при этом риппл может не запускаться на этот тап.

Вероятная причина — такие меню могут использовать отдельное окно или собственную обработку outside touch, из-за чего событие не проходит через ожидаемый путь `dispatchTouchEvent`.

Это отдельная проблема и в текущей архитектуре 2.3.0 не изменена.

---

## История версий

### 2.3.0

1. Удалены неиспользуемые импорты.
2. Убрана локальная проверка `Build.VERSION.SDK_INT` и импорт `Build`.
3. Убран неиспользуемый `_last_up_token`.
4. Убран пустой `after_hooked_method`.
5. `WindowManagerGlobal.mViews` использует кэшированный `Field`.
6. `SuperRipple.shader` использует кэшированный `Field` для замены shader.
7. `setupSizeUniforms(boolean)` ищется один раз и переиспользуется.
8. Исправлен ошибочный доступ `ripple.JA.shader`, из-за которого патч shader не применялся.
9. Патч прозрачности сохранён.
10. Патч хроматической аберрации сохранён.
11. `dose` uniform сохранён.
12. Поддержка нескольких окон и echo новых окон сохранена.
13. Кэш `SuperRipple` сохранён.
14. Работа через штатный `SuperRipple` сохранена.

### 2.2.1

- Небольшое изменение интерфейса внутри плагина.
- Сохранён механизм `AltSeekbar`.
- Сохранён патч shader и настройки эффекта.

### 2.2.0

- Добавлена новая настройка «уровень дозы» — хроматическая аберрация риппла.
- Интенсивность стала настоящим слайдером.
- Риппл начал реагировать на новые окна/диалоги, которые открываются, пока анимация ещё идёт.
- Добавлена оптимизация echo polling.
- Исправлен масштаб и привязка chromatic aberration к `offset`.
- Исправлена ошибка с альфой в shader.

### 2.1.0

- Патч shader перенесён с глобального constructor hook на экземпляры `SuperRipple`, которые создаёт сам плагин.
- Добавлена прозрачность фона.
- Добавлено принудительное обнуление `radius`.
- Добавлен кэш `SuperRipple`.
- Патч shader стал локальным и не затрагивает оригинальные Stars-анимации Telegram.
