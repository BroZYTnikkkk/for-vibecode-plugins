# Анализ разработки плагина animtou
> Анимированные касания (SuperRipple-эффект) для AyuGram / ExteraGram
> Версия документа: 2.2.1 — дополнено поверх исходного анализа
> Новые источники: реальный `superripple_effect.agsl`, рабочий пример `AltSeekbar` (сторонний плагин)

---

## Архитектура: как это работает в целом

Плагин перехватывает **каждое касание** на уровне базового класса `android.view.View` через хук на `dispatchTouchEvent`. Это единственная точка входа всех тач-событий в Android — любой `View` во всём приложении проходит через неё. При обнаружении нажатия (ACTION_DOWN) плагин запускает `SuperRipple.animate()` — анимацию, которая уже встроена в Telegram, но нигде не вызывается при обычных касаниях.

Второй слой — патч AGSL-шейдера, который убирает непрозрачный фон эффекта (патчится сразу после создания каждого `SuperRipple`, который создаёт сам плагин, — см. разделы 8-9 ниже).

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

**Изменилось в 2.2.0 — «отголосок» на новые окна.** Изначальной идеей было сделать риппл на универсальном слое, по итогу решил, что эффект должен захватывать новые вьюхи в рантайм

Тупиковый путь, который не стал делать вообще: буквально «риппл поверх диалогов/попапов, независимо от того, что на экране». `RenderEffect`/`RuntimeShader` искажают только содержимое той же самой вью, на которую повешены — не видят и не могут исказить то, что нарисовано в других окнах под ними. Отдельное окно поверх всего (`WindowManager.addView`) само по себе пустое, искажать ему нечего. Реализовать можно было бы только через живой захват экрана (`MediaProjection`/`PixelCopy`) — принципиально другой движок эффекта, требующий системного разрешения на запись экрана при каждом использовании. Признал нецелесообразным.

Вместо этого — пока рябь ещё «жива» (эмпирическая оценка длительности — 300мс), поллингом проверяется, не появились ли новые decor view:

```python
ECHO_WINDOW_MS = 300
ECHO_POLL_INTERVAL_MS = 80

def _echo_poll():
    now = int(time.time() * 1000)
    if now >= _echo_state["active_until"]:
        return
    views = _read_mviews()
    if views is not None:
        size = views.size()
        if size != _echo_state["last_seen_size"]:
            _echo_state["last_seen_size"] = size
            for i in range(size):
                view = views.get(i)
                key = view.hashCode()
                if key in _echo_state["known_views"]:
                    continue
                _echo_state["known_views"].add(key)
                lx, ly = screen_to_local(view, _echo_state["x"], _echo_state["y"])
                make_ripple(view, lx, ly, _echo_state["intensity"])
    run_on_ui_thread(_echo_poll, ECHO_POLL_INTERVAL_MS)
```

На каждую новую вьюху — рябь заново, теми же координатами и интенсивностью. Это не буквальное продолжение одной и той же волны (физически невозможно для только что появившейся вью), а синхронизированный по координатам повтор — визуально ощущается как «риппл реагирует на всё, что появилось».

Хук на `WindowManagerGlobal.addView` для отслеживания новых окон рассматривал и отклонил — точная сигнатура этого метода гуляет между версиями Android, а гадать с сигнатурами рефлексии в этом проекте уже не раз выходило боком (см. историю с `find_class(...).getDeclaredMethod(...)` в LodraBu). Поллинг медленнее, но не завязан на конкретную сигнатуру — только на то же самое `mViews`, которое уже читаю стабильно.

**Оптимизация, потребовавшаяся сразу же:** первая версия отголоска сама добавила заметное подлагивание при открытии чатов — по времени совпадает с окном поллинга, конкурирующим за главный поток именно в момент, когда Telegram и так занят переходом между экранами. Две правки:

1. Кэш `Field`-объекта для `mViews` — раньше каждый вызов заново делал `getDeclaredField`+`setAccessible` (дорогой поиск в рефлексии), теперь это делается один раз за жизнь плагина:
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
2. Поллинг перестал пересобирать список на каждый тик — сначала дешёвая `views.size()`, и только если число реально изменилось, тогда уже полный перебор (см. код `_echo_poll` выше). В подавляющем большинстве тиков (обычная навигация внутри того же окна, без нового decor view) это сводится к «взять кэшированный `Field`, вызвать `.size()`, сравнить два int».

После этой правки стало заметно лучше, но подлагивание при открытии чатов было и раньше, до всякого отголоска — часть цены, судя по всему, неотъемлема для самого способа хука (`dispatchTouchEvent` базового `View` вызывается по разу на каждую вью в цепочке диспатча одного физического тапа, и часть этой цены — JNI-переход Python↔Java на каждый вызов, который своим кодом не убрать, не отказавшись от самого способа хука). Открытый вопрос, пока не решил.

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

Кэш хранит по одному `SuperRipple` на каждый `View` (ключ — `hashCode`). Лимит в 30 записей с вытеснением самой старой (FIFO через `next(iter(...))`) — защита от бесконтрольного роста, если пользователь открывает много разных окон.

`_max_cache_size = 30` — достаточно для всех реальных сценариев (активность + несколько диалогов).

Создание идёт через `_make_patched_ripple(view)` вместо голого `SuperRipple(view)` — патч шейдера применяется прямо здесь, сразу после создания.

**Так было не всегда — в 2.1.0 нашёл и убрал лишнее.** Изначально шейдер патчился через хук на **все конструкторы класса `SuperRipple`**:

```python
sr_cls = jclass("org.telegram.ui.Stars.SuperRipple")
self.hook_all_constructors(sr_cls, SuperRippleInitHook())
```

Это хук на уровне класса — он сработает для **любого** `new SuperRipple(...)` в приложении, включая те, что создаёт сам Telegram для настоящих Stars-анимаций (покупка подарков и т.п.), не только для тех, что создаёт плагин. Побочным эффектом патч (прозрачный фон, обнулённый `radius`) применялся бы и к оригинальному Stars UI, незаметно меняя его вид — то, чего плагин делать не должен.

При этом плагин **сам** создаёт все нужные ему `SuperRipple` — единственное место, `_ripple_cache[key] = SuperRipple(view)` (код выше). Поскольку это собственный вызов конструктора, патчить шейдер можно сразу после создания, без глобального хука на класс — ровно то, что делает `_make_patched_ripple` сейчас. `hook_all_constructors` и класс `SuperRippleInitHook` из плагина убраны — они больше не нужны, и заодно это дешевле: не висит хук, который дёргается на каждое создание `SuperRipple` где угодно в приложении, а не только там, где он реально нужен.

Заодно в том же проходе текст и патч шейдера стали читаться и парситься **один раз** (`_get_patched_shader_code`, модульный кэш `_patched_shader_code`, см. раздел 9), а не при создании каждого нового `SuperRipple` — `AndroidUtilities.readRes(...)` и `str.replace(...)` раньше выполнялись повторно на каждое новое окно/диалог.

---

### 9. Патч шейдера — точечно, на своих экземплярах

Оригинальный `SuperRipple` использует непрозрачный фон — шейдер прописывает `alpha = 1.0` в обоих return-путях. Для плагина это неприемлемо: рипл должен быть прозрачным (накладываться поверх UI, а не закрашивать его).

`patch_shader_code` меняет четыре конкретных места в AGSL-коде шейдера (в 2.1.0 их было три; четвёртая добавлена в 2.2.0, см. ниже):

```python
replace_map = {
    "return half4(0.0, 0.0, 0.0, 1.0);": "return half4(0.0, 0.0, 0.0, 0.0);",
    "return img.eval(uv) + half4(add, add, add, 1.);": (
        "half2 off = offset * dose;"
        "return half4(img.eval(uv + off).r, img.eval(uv).g, img.eval(uv - off).b, img.eval(uv).a) + half4(add, add, add, 0.0);"
    ),
    "sdfRoundedBox(uv - size * .5, size * .5, radius)": "sdfRoundedBox(uv - size * .5, size * .5, float4(0.0))",
}
```

`half4` — это GLSL/AGSL тип `(r, g, b, a)`. Замена `a = 1.0` на `a = 0.0` делает фон шейдера прозрачным, оставляя только сам эффект рипла.

**Третья замена (сделана в 2.1.0) — обнуление радиуса скругления, устраняет обрезание по углам при анимации.** Реальный AGSL до патча:

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

Ключевая строка — `sdfRoundedBox(uv - size * .5, size * .5, radius)`: проверка "попадает ли смещённая рябью точка `uv` в скруглённый прямоугольник размером с View, с радиусами скругления по каждому углу `radius` (float4)". Если не попадает — считается, что вышли за пределы (раньше рисовалось сплошным чёрным, `alpha=1.0` — это первая замена).

Сам факт, что граница скруглённая, а не обычный прямоугольник, и есть причина, почему "обрезает" именно углы, а не любой край одинаково: у скруглённого прямоугольника кривизна границы сосредоточена ровно в углах, поэтому смещённая волной точка "вылетает" за эту границу там значительно охотнее, чем на прямом отрезке края. `radius` в оригинальном использовании (Stars-подарки, где `SuperRipple` применяется к скруглённой карточке/шторке) это осмысленно — эффект должен уважать скругление самой карточки. Когда плагин применяет `SuperRipple` к полноэкранному decor view, никакого "скругления карточки" там нет и не должно быть — а `radius`, судя по всему, всё равно выставляется в ненулевое значение внутри `setupSizeUniforms` (либо под скругление физического экрана, либо под дефолтное скругление Stars-шторки) и создаёт этот эффект в углах. Радиус принудительно обнуляется прямо в шейдере — независимо от того, что туда передаёт `setupSizeUniforms`. Граница становится обычным прямоугольником, углы ведут себя так же, как и любая другая точка края.

**Добавлено в 2.2.0 — «доза» (хроматическая аберрация).** Вторая замена расширена: вместо единого сэмпла `img.eval(uv)` теперь три отдельных сэмпла R/G/B со смещением по новому uniform `dose`. Понадобилось отдельно объявить сам uniform в начале исходника (`uniform float dose;` — без этого AGSL не скомпилировался бы, переменной раньше не существовало вообще):

```python
def patch_shader_code(code):
    code = "uniform float dose;\n" + code
    ...
```

Первая версия формулы сдвига была ошибочной — смещение считалось от центра **экрана**, статично, никак не привязанное к самой волне:
```glsl
half2 off = (uv - size * .5) * dose;
```
Переделано на смещение от `offset` — той же переменной, что двигает саму рябь (`offset += ripple.xy` в цикле по волнам):
```glsl
half2 off = offset * dose;
```
Так аберрация стала характеристикой самого риппла, а не отдельным несвязанным эффектом.

**Критичный регрессионный баг** в первой версии сборки нового `half4` для расщеплённых каналов альфа была жёстко прописана `0.0`:
```glsl
return half4(img.eval(uv + off).r, img.eval(uv).g, img.eval(uv - off).b, 0.0) + ...
```
До этого (`return img.eval(uv) + half4(...)`) альфа бралась из `img.eval(uv)` естественным образом — сложением, а не перезаписью. А тут её случайно заменил литералом. Поскольку `SuperRipple` кэшируется на вью и остаётся навешанным как `RenderEffect` даже после угасания самой ряби, разбитая альфа оставалась насовсем — вьюха рендерилась прозрачной не только во время анимации, а вообще всегда после первого тапа. Исправлено — код выше (`replace_map`) уже содержит рабочую версию с `img.eval(uv).a` вместо литерала.

Тупиковый путь по масштабу дозы: изначально закладывал отдельный маленький масштаб (`DOSE_SCALE = 0.01`, UI 0–5), думал, что смещение канала должно быть очень маленьким числом. После перехода на привязку к `offset` (который уже сам по себе умеренная по величине, ограниченная физикой риппла величина) выяснил, что нужды в отдельном крошечном масштабе нет — итоговая версия использует тот же масштаб и диапазон, что и сила (см. раздел 14).

Патч применяется сразу после того, как плагин сам создаёт `SuperRipple(view)` — через `set_private_field` подменяются приватные поля `shader` и `effect` на пропатченные версии, `setupSizeUniforms` вызывается вручную, чтобы правильно инициализировать uniform-переменные нового шейдера. Значение `dose` выставляется отдельным вызовом сразу после создания шейдера: `shader.setFloatUniform("dose", _current_dose)`.

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

**Уточнение по доке:** по официальной странице [Xposed Method Hooking](https://plugins.exteragram.app/docs/xposed-hooking) хуки и так *"are automatically removed when your plugin is unloaded"* — то есть framework сам снимает регистрацию хука при выгрузке плагина, вручную вызывать `unhook_method` в `on_plugin_unload` не обязательно. Явный вызов в animtou — не ошибка и не костыль, а просто дополнительная подстраховка (например, на случай hot-reload плагина в рамках одной сессии, когда `on_plugin_unload` мог бы отработать раньше, чем framework успеет почистить регистрацию)

`_ripple_cache.clear()` освобождает все `SuperRipple`-объекты, предотвращая утечку Java-объектов через Python-кэш — это не связано с хуками и остаётся нужным независимо от автоматической очистки хуков.

---

### 14. Кэш интенсивности `_cached_intensity`

```python
def _refresh_settings_cache(self):
    self._cached_intensity = self._as_float(self.get_setting("intensity", "0.55"), 0.55)
```

`get_setting` обращается к хранилищу настроек — это относительно медленная операция (десериализация, I/O). Вызывать её на каждое касание было бы расточительно.

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

**Как это было сделано после отказа от кнопки «применить» (тоже рабочий вариант, но не актуальный — см. ниже, в 2.2.0 контрол сменился на слайдер):** `Input` в `ui.settings` и так поддерживает `on_change` — коллбэк, который framework вызывает сам при каждом изменении значения (значение под `key` при этом уже сохранено framework'ом).

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

**Найденный баг: значение ничем не ограничивалось.** Подпись поля обещала диапазон 0.1–3.0, но фактически можно было ввести хоть 500 — `_as_float` просто парсит число, без проверки границ, и такое значение действительно применялось к риплу. Исправлено добавлением явного клампа:

```python
INTENSITY_MIN = 0.1
INTENSITY_MAX = 3.0

def _clamp_intensity(self, value):
    return max(self.INTENSITY_MIN, min(self.INTENSITY_MAX, value))

def _on_intensity_change(self, new_value):
    parsed = self._as_float(new_value, self._cached_intensity)
    clamped = self._clamp_intensity(parsed)
    self._cached_intensity = clamped
    if clamped != parsed:
        self.set_setting("intensity", str(clamped), reload_settings=True)
```

Ограничивается не только применяемое значение (`_cached_intensity`), но и то, что хранится и показывается в самом поле — если ввести число за пределами диапазона, поле само перезапишется на ближайшую границу. `set_setting(key, value, reload_settings=True)` — официальный способ из доки `plugin-settings`: `reload_settings=True` пересобирает экран настроек, так что исправленное значение сразу видно в UI, а не только «применяется невидимо».

`_refresh_settings_cache()` (вызывается при загрузке плагина) тоже клампит прочитанное значение — если в хранилище с прошлых версий уже лежит что-то невалидное, при старте оно тоже приводится в границы.

**Изменилось в 2.2.0 — контрол сменился с текстового `Input` на слайдер.** Захотелось физический ползунок вместо ручного набора числа. В доке `ui.settings` штатного слайдера не нашлось (список контролов там подан как исчерпывающий: `Header, Input, Divider, Switch, Selector, Text, EditText`, без Slider).

Тупиковый путь: попробовал `com.google.android.material.slider.Slider` напрямую — он есть в зависимостях ETG, показалось логичным просто взять готовое. Конструктор `Slider(context)` падал:
```
java.lang.UnsupportedOperationException: Failed to resolve attribute at index 3
	at com.google.android.material.tooltip.TooltipDrawable.createFromAttributes
	at com.google.android.material.slider.BaseSlider.createLabelPool
```
Причина — `Slider` при создании сам строит всплывающую подсказку (`TooltipDrawable`) и лезет за Material-специфичными атрибутами темы. Тема приложения — `Theme.TMessages` → `Theme.AppCompat.Light` → ..., не `Theme.MaterialComponents.*`, нужных атрибутов там просто нет. 

Рабочий путь нашёл, разобрав реальный пример из стороннего плагина — и выяснил сразу две вещи, которых не было в доке:

1. В `ui.settings` **есть** `Custom(view=...)` — обёртка для вставки произвольной Java `View` в список настроек. Пропущена в примере доки, на практике работает.
2. У exteraGram есть **свой** компонент слайдера — `com.exteragram.messenger.preferences.components.AltSeekbar`, сделанный специально для их preferences-экранов, не сырой `SeekBarView` (не пришлось бы писать свой `UItem.UItemFactory`-класс через `class-proxy`, самый тяжёлый инструмент из всех, что разбирал, — пришлось бы, откажись от `Custom`).

```python
def _build_seekbar(self, minimum, maximum, default, title, min_label, max_label, on_change):
    from com.exteragram.messenger.preferences.components import AltSeekbar
    from java import dynamic_proxy

    class _Drag(dynamic_proxy(AltSeekbar.OnDrag)):
        def run(this, value):
            on_change(value)

    listener = _Drag()
    self._seekbar_refs.append(listener)

    bar = AltSeekbar(activity, listener, minimum, maximum, title, min_label, max_label)
    bar.setProgress(float(default))
    return Custom(view=bar)
```

`minimum`/`maximum` конструктора — строго `int` (Java-сторона не делает неявное `float → int` сужение, поймал `TypeError: Cannot convert float object to int`, когда там по невнимательности остался `float`). `listener` — `AltSeekbar.OnDrag`, однометодный интерфейс, реализуется напрямую через `dynamic_proxy`, без `client_utils`-обёрток (тот же паттерн, что уже проверен рабочим). Важная деталь из чужого примера, которую взял себе: ссылки на listener-объекты нужно **держать живыми** (`self._seekbar_refs.append(listener)`) — иначе `dynamic_proxy`-объект может собрать GC, и колбэк молча перестанет срабатывать.

Отдельно выяснил эмпирически (не из доки): бейдж рядом с заголовком в `AltSeekbar` не показывает сырой прогресс — он **интерполирует число между `min_label` и `max_label`**, распарсенными как числа, по позиции ползунка. Лейблы — не украшение, они определяют, что реально увидит пользователь как текущее значение.

Итоговая раскладка после нескольких неверных попыток (путал реальное применяемое значение с тем, что просто показывается на слайдере): сила реально работает в диапазоне 0.1–3.0, масштаб UI→реальное значение ×0.1, на слайдере отображается как `1–30`:

```python
INTENSITY_UI_MIN = 1
INTENSITY_UI_MAX = 30
INTENSITY_SCALE = 0.1

def _on_intensity_change(self, ui_value):
    real = self._clamp_intensity(round(float(ui_value)) * self.INTENSITY_SCALE)
    self._cached_intensity = real
    self.set_setting("intensity", str(real))
```

`_clamp_intensity`/`INTENSITY_MIN`/`INTENSITY_MAX` не поменялись по смыслу — та же функция и те же границы, что были для текстового поля, просто теперь применяются к значению, пришедшему от слайдера, а не распарсенному из текста. Тем же самым `_build_seekbar()` и по той же схеме масштабирования сделана и «доза» (хроматическая аберрация) — единственная действительно новая настройка в 2.2.0, детали формулы смещения и регрессионного бага с альфой — в разделе 9 выше. Ниже — то, что специфично именно для настройки дозы, не для шейдера.

---

### 15. «Доза» — новая настройка в 2.2.0, персистентный uniform вместо параметра вызова

В отличие от силы (которая передаётся заново при каждом вызове `.animate(x, y, intensity)`), доза не параметр вызова — это uniform-переменная, выставленная на уже созданном `RuntimeShader`. А `SuperRipple` кэшируется по вью (`_ripple_cache`, раздел 8) и переиспользуется между касаниями. Из этого следует нюанс, которого не было у силы: если просто поменять значение uniform-а, уже созданные и закэшированные шейдеры об этом не узнают.

Решение — модульная переменная плюс явный сброс кэша при изменении дозы:

```python
_current_dose = 0.01

def _set_current_dose(value):
    global _current_dose
    _current_dose = value
    _ripple_cache.clear()
```

`_ripple_cache.clear()` тут обязателен — иначе старые уже созданные `SuperRipple` на других вью так и останутся со старым значением дозы до следующего пересоздания (а пересоздаются они только когда вью впервые встречается — см. раздел 8). Само значение проставляется на шейдер сразу после создания, рядом с уже существующим `set_private_field(ripple, "shader", shader)`:

```python
shader.setFloatUniform("dose", _current_dose)
```

Диапазон и масштаб — по той же схеме и тем же `_build_seekbar()`, что и у силы (раздел 14), но с нижней границей `0` (честное «выкл.», а не малое ненулевое значение):

```python
DOSE_UI_MIN = 0
DOSE_UI_MAX = 30
DOSE_SCALE = 0.1

def _on_dose_change(self, ui_value):
    self._cached_dose_ui = self._clamp_dose_ui(round(float(ui_value)))
    _set_current_dose(self._cached_dose_ui * self.DOSE_SCALE)
    self.set_setting("dose", str(self._cached_dose_ui))
```

Подписи на слайдере — `"выкл."` вместо `str(DOSE_UI_MIN)` (это просто текст, не обязан быть числом) и `str(DOSE_UI_MAX)` для максимума.

---

### 16. `_as_float` — безопасный парсинг настройки

```python
def _as_float(self, s, default):
    try:
        return float(str(s).strip().replace(",", "."))
    except Exception:
        return default
```

Пользователь вводит интенсивность текстом. `.replace(",", ".")` — обработка локалей, где дробная часть пишется через запятую (русская раскладка). `str(s)` защищает от случая, когда значение оказалось не строкой. При любой ошибке — возвращается `default`.

Эта функция не изменилась — её просто стали вызывать из другого места (`_on_intensity_change` вместо `_refresh_settings_cache`, см. раздел 14). Она по-прежнему отвечает только за парсинг — за то, что число не выходит за диапазон, отвечает отдельная `_clamp_intensity` (тоже раздел 14), это разные задачи и разные функции.

---

### 17. Автообновление через `zwylib`

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

### 18. Открытие настроек через `PluginsController`

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

---

## Открытые вопросы (замечено, но не разобрано)

### Риппл не срабатывает при закрытии некоторых контекстных меню

При открытом меню «три точки» (в чате, в профиле, в канале) — тап вне меню закрывает его (стандартное поведение самого Telegram), но при этом риппл почему-то не запускается на этот тап. Обнаружено в 2.2.0, не исследовано. Правдоподобная гипотеза (не проверена): такие меню обычно реализованы через `PopupWindow` с собственной логикой закрытия по тапу снаружи (`OutsideTouchListener` или аналог) — если этот тап перехватывается на уровне, до которого не долетает `dispatchTouchEvent` базового `View` в том виде, в каком мы его хукаем, наш хук его просто не увидит. Требует отдельного разбора.

