# Анализ разработки плагина animtou
> Анимированные касания (SuperRipple-эффект) для AyuGram / ExteraGram
> Версия документа: 2.1.0 — дополнено поверх исходного анализа
> Новые источники: реальный `superripple_effect.agsl`

---

## Обновление 2.1.0 — что нового поверх исходного анализа

Всё ниже — новое поверх исходного анализа (он сохранён целиком, см. "Архитектура: как
это работает в целом" и далее).

### Точный диагноз бага «экран по углам обрезается при анимации»

Раздобыт реальный `superripple_effect.agsl` — вот что происходит на самом деле:

```glsl
half4 main(in float2 fragCoord) {
    float add = 0.0;
    float2 offset = float2(0.0);
    for (int i = 0; i < 7; ++i) {
        if (i >= count) break;
        float3 ripple = rippleOffset_ios(fragCoord, float2(centerX[i], centerY[i]), intensity[i], t[i]);
        offset += ripple.xy;
        add += ripple.z;
    }
    float2 uv = fragCoord + offset;
    if (sdfRoundedBox(uv - size * .5, size * .5, radius) > 0.0)
        return half4(0.0, 0.0, 0.0, 1.0);
    return img.eval(uv) + half4(add, add, add, 1.);
}
```

Ключевая строка — `sdfRoundedBox(uv - size * .5, size * .5, radius)`. Это проверка
"попадает ли смещённая рябью точка `uv` в скруглённый прямоугольник размером с View,
с радиусами скругления по каждому углу `radius` (float4)". Если не попадает — считается,
что мы "вышли" за пределы, и раньше это рисовалось сплошным чёрным (`alpha=1.0`) — это
уже было исправлено первым патчем в `patch_shader_code`.

Но сам факт, что граница — **скруглённая**, а не обычный прямоугольник, и есть причина,
почему "обрезает" именно углы, а не любой край одинаково: у скруглённого прямоугольника
кривизна границы сосредоточена ровно в углах, поэтому смещённая волной точка "вылетает"
за эту границу там значительно охотнее, чем на прямом отрезке края. `radius` в оригинальном
использовании (Stars-подарки, где `SuperRipple` применяется к скруглённой карточке/шторке)
это осмысленно — эффект должен уважать скругление самой карточки. Когда плагин применяет
`SuperRipple` к **полноэкранному decor view**, никакого "скругления карточки" там нет и
не должно быть — а `radius`, судя по всему, всё равно выставляется в ненулевое значение
внутри `setupSizeUniforms` (либо под скругление физического экрана, либо под дефолтное
скругление Stars-шторки) и создаёт этот эффект в углах.

**Фикс** — не Python-костыль, а прямая правка того же самого шейдер-кода, ровно тем же
методом (`patch_shader_code`), что уже использовался для двух других строк:

```python
"sdfRoundedBox(uv - size * .5, size * .5, radius)":
    "sdfRoundedBox(uv - size * .5, size * .5, float4(0.0))",
```

Радиус принудительно обнуляется прямо в шейдере — независимо от того, что туда
передаёт `setupSizeUniforms`. Граница становится обычным прямоугольником, углы ведут
себя так же, как и любая другая точка края.

### Находка: `hook_all_constructors(SuperRipple, ...)` был шире, чем нужно

Оригинальный код патчил шейдер через хук **на все конструкторы класса `SuperRipple`**:

```python
sr_cls = jclass("org.telegram.ui.Stars.SuperRipple")
self.hook_all_constructors(sr_cls, SuperRippleInitHook())
```

Это хук на уровне класса — он сработает для **любого** `new SuperRipple(...)` в
приложении, включая те, что создаёт сам Telegram для настоящих Stars-анимаций (покупка
подарков и т.п.), не только для тех, что создаёт плагин. То есть побочным эффектом
патч (прозрачный фон, а теперь ещё и обнулённый `radius`) применялся бы и к
оригинальному Stars UI, незаметно меняя его вид — то, чего плагин, скорее всего,
делать не должен.

При этом плагин **сам** создаёт все нужные ему `SuperRipple` — единственное место:

```python
_ripple_cache[key] = SuperRipple(view)
```

Поскольку это наш собственный вызов конструктора, патчить шейдер можно сразу после
создания, без глобального хука на класс:

```python
def _make_patched_ripple(view):
    ripple = SuperRipple(view)
    code = _get_patched_shader_code()
    method = ripple.getClass().getDeclaredMethod("setupSizeUniforms", Boolean.TYPE)
    method.setAccessible(True)
    shader = RuntimeShader(code)
    set_private_field(ripple, "shader", shader)
    method.invoke(ripple, True)
    set_private_field(ripple, "effect", RenderEffect.createRuntimeShaderEffect(shader, "img"))
    return ripple
```

`hook_all_constructors` и класс `SuperRippleInitHook` из плагина убраны — они больше
не нужны. Заодно это чуть дешевле: не висит хук, который дергается на каждое создание
`SuperRipple` где угодно в приложении, а не только там, где он нам реально нужен.

Также текст и патч шейдера теперь читаются и парсятся **один раз** (`_get_patched_shader_code`,
модульный кэш `_patched_shader_code`), а не при создании каждого нового `SuperRipple` —
`AndroidUtilities.readRes(...)` и три `str.replace(...)` за один такой вызов раньше
выполнялись повторно на каждое новое окно/диалог.

---

## Архитектура: как это работает в целом

Плагин перехватывает **каждое касание** на уровне базового класса `android.view.View` через хук на `dispatchTouchEvent`. Это единственная точка входа всех тач-событий в Android — любой `View` во всём приложении проходит через неё. При обнаружении нажатия (ACTION_DOWN) плагин запускает `SuperRipple.animate()` — анимацию, которая уже встроена в Telegram, но нигде не вызывается при обычных касаниях.

Второй слой — патч AGSL-шейдера, который убирает непрозрачный фон эффекта (патчится сразу после создания каждого `SuperRipple`, который создаёт сам плагин, — см. "Обновление 2.1.0" выше).

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

**Найденный на практике нюанс:** хук висит буквально на всех `View` в приложении — включая те, что добавляют другие плагины. У некоторых сторонних плагинов (например, `Custom Profile` от `@RoflPlugins`, который добавляет свой кастомный блок с фото в профиль) свой `View`-класс, который Chaquopy иногда не может корректно завернуть в питоновский объект именно при чтении `param.thisObject` — падает с `TypeError: cannot create ... proxy from ... instance`, ещё до вызова `_handle_touch`. Риппл при этом продолжает нормально работать на всём остальном интерфейсе — ломается только сам конкретный тап по этому чужому элементу.

Поэтому чтение `param.thisObject` вынесено в отдельный `try/except`, который тихо пропускает касание при такой ошибке — вместо того, чтобы каждый раз показывать буллетин с трейсом на то, что фактически не является багом animtou и ни на что не влияет:

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

Ошибки внутри самой `_handle_touch` (уже наша логика) по-прежнему всплывают буллетином — тихо пропускается только сам факт нечитаемого `thisObject`, а не любые проблемы вообще.

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
    _ripple_cache[key] = _make_patched_ripple(view)
    if len(_ripple_cache) > _max_cache_size:
        oldest = next(iter(_ripple_cache))
        del _ripple_cache[oldest]
_ripple_cache[key].animate(x, y, intensity)
```

Создание `SuperRipple` — дорогая операция: выделяется буфер для шейдера, компилируется AGSL-код, аллоцируется `RenderEffect`. Если создавать новый объект на каждый тап — это гарантированный UI-джанк и утечка памяти.

Кэш хранит по одному `SuperRipple` на каждый `View` (ключ — `hashCode`). Лимит в 10 записей с вытеснением самой старой (FIFO через `next(iter(...))`) — защита от бесконтрольного роста, если пользователь открывает много разных окон.

`_max_cache_size = 10` — достаточно для всех реальных сценариев (активность + несколько диалогов).

Создание идёт через `_make_patched_ripple(view)` вместо голого `SuperRipple(view)` —
патч шейдера применяется прямо здесь, сразу после создания, а не через глобальный хук
на конструктор (см. "Обновление 2.1.0" выше).

---

### 9. Патч шейдера — точечно, на своих экземплярах

Оригинальный `SuperRipple` использует непрозрачный фон — шейдер прописывает `alpha = 1.0` в обоих return-путях. Для плагина это неприемлемо: рипл должен быть прозрачным (накладываться поверх UI, а не закрашивать его).

`patch_shader_code` меняет три конкретных места в AGSL-коде шейдера:

```python
replace_map = {
    "return half4(0.0, 0.0, 0.0, 1.0);": "return half4(0.0, 0.0, 0.0, 0.0);",
    "return img.eval(uv) + half4(add, add, add, 1.);": "return img.eval(uv) + half4(add, add, add, 0.0);",
    "sdfRoundedBox(uv - size * .5, size * .5, radius)": "sdfRoundedBox(uv - size * .5, size * .5, float4(0.0))",
}
```

`half4` — это GLSL/AGSL тип `(r, g, b, a)`. Замена `a = 1.0` на `a = 0.0` делает фон шейдера прозрачным, оставляя только сам эффект рипла. Третья замена обнуляет радиус скругления границы эффекта — устраняет обрезание по углам (подробный разбор — в "Обновлении 2.1.0" выше).

Патч применяется сразу после того, как плагин сам создаёт `SuperRipple(view)` — через `set_private_field` подменяются приватные поля `shader` и `effect` на пропатченные версии, `setupSizeUniforms` вызывается вручную, чтобы правильно инициализировать uniform-переменные нового шейдера.

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

`hook_method` возвращает handle — ссылку на конкретную регистрацию хука, которую принимает `unhook_method`.

**Уточнение по доке:** по официальной странице [Xposed Method Hooking](https://plugins.exteragram.app/docs/xposed-hooking) хуки и так *"are automatically removed when your plugin is unloaded"* — то есть framework сам снимает регистрацию хука при выгрузке плагина, вручную вызывать `unhook_method` в `on_plugin_unload` не обязательно. Явный вызов в animtou — не ошибка и не костыль, а просто дополнительная подстраховка (например, на случай hot-reload плагина в рамках одной сессии, когда `on_plugin_unload` мог бы отработать раньше, чем framework успеет почистить регистрацию) — но рассчитывать, что без него хук "продолжит висеть после отключения плагина", неверно.

`_ripple_cache.clear()` освобождает все `SuperRipple`-объекты, предотвращая утечку Java-объектов через Python-кэш — это не связано с хуками и остаётся нужным независимо от автоматической очистки хуков.

---

### 14. Кэш интенсивности `_cached_intensity`

```python
def _refresh_settings_cache(self):
    self._cached_intensity = self._as_float(self.get_setting("intensity", "0.55"), 0.55)
```

`get_setting` обращается к хранилищу настроек — это относительно медленная операция (десериализация, I/O). Вызывать её на каждое касание (а касаний — сотни в секунду при скролле) было бы расточительно.

Значение кэшируется в Python-переменную один раз при загрузке плагина (`on_plugin_load` вызывает `_refresh_settings_cache()`). В `_handle_touch` используется уже закэшированное значение — `self._cached_intensity`.

**Как раньше обновлялся кэш при изменении настройки (тоже рабочий вариант):** в `create_settings()` была отдельная кнопка «применить», которая вызывала `_refresh_settings_cache()` по клику:

```python
Text(
    text="применить",
    accent=True,
    icon="ic_ab_done",
    on_click=lambda _v=None: self._refresh_settings_cache()
)
```

Это честно работало, но требовало от пользователя лишнего тапа после ввода числа — легко забыть нажать и не понять, почему изменения не применились.

**Как это сделано сейчас:** `Input` в `ui.settings` и так поддерживает `on_change` — коллбэк, который framework вызывает сам при каждом изменении значения (значение под `key` при этом уже сохранено framework'ом). Кнопка «применить» убрана, вместо неё:

```python
def _on_intensity_change(self, new_value):
    self._cached_intensity = self._as_float(new_value, self._cached_intensity)
```

```python
Input(
    key="intensity",
    text="интенсивность (0.1 - 3.0)",
    default=intensity_default,
    icon="msg_brightness_high",
    on_change=self._on_intensity_change,
)
```

Плюс: не нужен отдельный `get_setting` внутри — `new_value` уже пришло от framework'а, парсим сразу. Пользователю не нужно ничего нажимать отдельно — значение подхватывается сразу по мере ввода.

---

### 15. `_as_float` — безопасный парсинг настройки

```python
def _as_float(self, s, default):
    try:
        return float(str(s).strip().replace(",", "."))
    except Exception:
        return default
```

Пользователь вводит интенсивность текстом. `.replace(",", ".")` — обработка локалей, где дробная часть пишется через запятую (русская раскладка). `str(s)` защищает от случая, когда значение оказалось не строкой. При любой ошибке — возвращается `default`.

Эта функция не изменилась — её просто стали вызывать из другого места (`_on_intensity_change` вместо `_refresh_settings_cache`, см. раздел 14).

---

### 16. Автообновление через `zwylib`

```python
try:
    import zwylib
    zwylib.add_autoupdater_task(id, UPDATE_CHANNEL_ID, UPDATE_MESSAGE_ID)
except ImportError:
    run_on_ui_thread(
        lambda: BulletinHelper.show_error("animtou доступен, но без автообновления"),
        2000
    )
```

`zwylib` — внешняя библиотека, не гарантированно установленная. Плагин её не требует — работает без неё. При отсутствии показывается ошибка с задержкой в 2 секунды, чтобы не мешать остальной инициализации `on_plugin_load`.

**Как раньше делалась задержка (тоже рабочий вариант):** вручную поднимался отдельный Python-поток с `time.sleep`:

```python
def delayed_error():
    sleep(2)
    run_on_ui_thread(lambda: BulletinHelper.show_error("animtou доступен, но без автообновления"))
threading.Thread(target=delayed_error, daemon=True).start()
```

Рабочий подход, `daemon=True` гарантирует, что поток не помешает завершению приложения. Но это лишняя ручная многопоточность там, где она не нужна.

**Как это сделано сейчас:** по доке [Android Utilities](https://plugins.exteragram.app/docs/android-utils) у `run_on_ui_thread` уже есть встроенный необязательный параметр задержки в миллисекундах (`run_on_ui_thread(func, delay)`). Один вызов вместо потока + `sleep` + импорта `threading`/`time.sleep` — то же самое поведение, без ручного управления потоком.

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

### Патч приватных полей сразу после `new` — когда объект создаём мы сами

```python
obj = SomeJavaClass(args)
set_private_field(obj, "fieldName", new_value)
```

Хук на конструктор (`hook_all_constructors`) нужен, только если объект создаёт **не
наш код** — например, сам Telegram где-то внутри. Если создаём объект сами (как
`SuperRipple(view)` в этом плагине) — глобальный хук на класс лишний и может задеть
чужие вызовы того же конструктора.

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
    └── hook_method(View.dispatchTouchEvent) → _animtouHook
            └── before: _handle_touch(view, event)
                    ├── фильтр: только ACTION_DOWN (action_masked == 0)
                    ├── дедупликация по (downTime, action) токену
                    ├── получить raw координаты касания
                    ├── получить все DecorView через WindowManagerGlobal.mViews
                    └── для каждого View:
                            screen_to_local() → make_ripple() → run_on_ui_thread()
                                    ├── если SuperRipple для этого View ещё нет в кэше:
                                    │       _make_patched_ripple(view)
                                    │           ├── SuperRipple(view)
                                    │           └── патч шейдера (alpha=0, radius=0) прямо на нём
                                    └── SuperRipple.animate(x, y, intensity)

on_plugin_unload()
    ├── unhook_method(view_unhook_ref)
    └── _ripple_cache.clear()
```
