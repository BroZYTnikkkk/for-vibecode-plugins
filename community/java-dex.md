# Java внутри плагина: вшитый DEX

> многие красивые плагины (Material Player, Chip Folders, Compact Bottom Nav, Text Animation, Photo Picker Plus и др.) почти не содержат Python. в `.plugin` лежит маленькая Python-обёртка и огромная base64-строка, внутри которой скомпилированный Java/Kotlin-код (DEX). этот файл объясняет, как это устроено и как такие плагины разбирать.

---

## зачем так делают

- **скорость.** отрисовка, анимации и `onDraw` на Python через Chaquopy заметно тормозят. Java работает с той же скоростью, что и сам клиент.
- **полноценное наследование.** из Python нельзя нормально унаследоваться от Java-класса (`View`, `ActionMode.Callback2`, `RecyclerView.Adapter`). `dynamic_proxy` умеет только интерфейсы. в DEX можно писать обычные подклассы.
- **память.** Log Overlay прямо пишет в описании: «переписано на чистый Java/DEX для устранения утечек памяти».

минус: код становится закрытым для чтения. чтобы понять такой плагин, DEX нужно декомпилировать (ниже).

---

## как Python-часть загружает DEX

общая схема у всех разобранных плагинов одинаковая:

```python
import base64
from java.nio import ByteBuffer
from dalvik.system import InMemoryDexClassLoader
from org.telegram.messenger import ApplicationLoader

DEX_B64 = "ZGV4CjAzNQ..."   # base64 от classes.dex (иногда сжатый)

class Plugin(BasePlugin):
    def on_plugin_load(self):
        dex_bytes = base64.b64decode(DEX_B64)
        parent = ApplicationLoader.applicationContext.getClassLoader()
        self.loader = InMemoryDexClassLoader(ByteBuffer.wrap(dex_bytes), parent)
        self.core = self.loader.loadClass("dev.rooni.StandardContextMenuHook")
        # вызов статического метода start(ClassLoader)
        cl = find_class("java.lang.ClassLoader")
        self.core.getMethod("start", cl).invoke(None, parent)

    def on_plugin_unload(self):
        self.core.getMethod("stop").invoke(None)   # Java сама снимает свои хуки
```
<sub>по мотивам «Системное меню текста» (@YouRooni)</sub>

ключевые моменты:

1. **родительский загрузчик — загрузчик приложения** (`applicationContext.getClassLoader()`). поэтому из DEX видны все классы Telegram (`org.telegram.ui.ChatActivity` и т.д.) и Xposed API.
2. **точка входа — статический метод.** обычно `start(ClassLoader)`, `init(Context, String pluginId)` или `load()`. второй вариант (NoForwardLimit) передаёт id плагина, чтобы Java могла читать его настройки.
3. **выгрузка.** Java-часть хранит список `XC_MethodHook.Unhook` и в `stop()` вызывает `unhook()` у каждого. Python-хуки (`self.hook_method`) движок снимает сам, а хуки, поставленные из Java, нет.
4. **`InMemoryDexClassLoader` есть только с Android 8.0.** NoForwardLimit проверяет `Build.VERSION.SDK_INT`, Продвинутый поиск при ошибке пишет DEX в кэш и грузит через обычный `DexClassLoader`.

### вызов методов DEX из Python

удобная обёртка из «Продвинутого поиска» (@dekma0091): ищет метод по имени и числу аргументов, не перечисляя Java-типы.

```python
def _invoke(self, method_name, *args):
    for method in self.clazz.getDeclaredMethods():
        if str(method.getName()) == method_name and len(method.getParameterTypes()) == len(args):
            method.setAccessible(True)
            return method.invoke(None, *args)
    raise RuntimeError(f"core method not found: {method_name}/{len(args)}")

# self._invoke("openSearch", context, int(peer_id), str(query))
```

### варианты упаковки

| как упаковано | пример | распаковка |
|---|---|---|
| чистый base64 в строке `DEX_B64 = "..."` | плагины @RnPlugins / @YouRooni | `base64.b64decode` |
| base64 от zlib | Photo Picker Plus, Продвинутый поиск | `zlib.decompress(base64.b64decode(s))` |
| base64 от xz/lzma | NoForwardLimit (@zwylair) | `lzma.decompress(base64.b64decode(s))` |
| base64 от zlib в комментариях `# __DEX_BEGIN__ … # __DEX_END__` | TempSub | склеить строки без `#` и пробелов, потом zlib |

у всех DEX начинается с байтов `dex\n035`. по ним легко проверить, что распаковка прошла правильно.

---

## как выглядит Java-сторона

хуки в DEX ставятся тем же Xposed API, что и в Python, только напрямую:

```java
import de.robv.android.xposed.XC_MethodHook;
import de.robv.android.xposed.XposedBridge;

public final class StandardContextMenuHook {
    private static final ArrayList<XC_MethodHook.Unhook> unhooks = new ArrayList<>();

    public static void start(ClassLoader cl) {
        Class<?> enterView = Class.forName("org.telegram.ui.Components.ChatActivityEnterView", false, cl);
        Class<?> editText  = Class.forName("org.telegram.ui.Components.EditTextBoldCursor", false, cl);

        // запоминаем поле ввода сообщения при создании ChatActivityEnterView
        unhooks.addAll(XposedBridge.hookAllConstructors(enterView, new XC_MethodHook() {
            public void afterHookedMethod(MethodHookParam p) { registerMessageField(p.thisObject); }
        }));
        // подменяем ActionMode.Callback у поля ввода на свой, который добавляет пункты меню
        unhooks.addAll(XposedBridge.hookAllMethods(editText, "startActionMode", new XC_MethodHook() {
            public void beforeHookedMethod(MethodHookParam p) {
                if (p.args.length > 0 && p.args[0] instanceof ActionMode.Callback)
                    p.args[0] = new SystemActionsCallback((TextView) p.thisObject, (ActionMode.Callback) p.args[0]);
            }
        }));
    }

    public static void stop() {
        for (XC_MethodHook.Unhook u : unhooks) u.unhook();
        unhooks.clear();
    }
}
```
<sub>сокращённый декомпилят «Системного меню текста» (@YouRooni)</sub>

`SystemActionsCallback` наследуется от `ActionMode.Callback2`, вызывает оригинальный callback и после него добавляет в меню «Поделиться» и все приложения, которые принимают `android.intent.action.PROCESS_TEXT`. из Python так сделать нельзя, потому что нужен подкласс абстрактного Java-класса.

### сборка своего DEX (общая схема)

в разобранных плагинах исходников нет, только результат. обычный путь такой:

1. написать Java/Kotlin, компилируя против `android.jar` и заглушек (stubs) нужных классов Telegram и `de.robv.android.xposed.*` (`compileOnly`, в DEX они не попадают);
2. собрать `classes.dex` через `d8` (Android build-tools);
3. закодировать в base64 (по желанию сжать zlib) и вставить строкой в `.plugin`.

часть плагинов @RnPlugins содержит в DEX отметку «Built with GennyBot (@GennyLabBot)», то есть собрана через этого бота.

---

## как декомпилировать DEX из плагина

1. вытащить base64 и распаковать (этот же скрипт находит все варианты из таблицы выше):

```python
import re, sys, base64, zlib, lzma

text = open(sys.argv[1], encoding="utf-8").read()
blobs = re.findall(r"[A-Za-z0-9+/=]{2000,}", text)
blobs += [re.sub(r"[#\s]", "", b) for b in re.findall(r"__DEX_BEGIN__(.*?)__DEX_END__", text, re.S)]
for n, blob in enumerate(blobs, 1):
    raw = base64.b64decode(blob + "=" * (-len(blob) % 4))
    for unpack in (lambda x: x, zlib.decompress, lzma.decompress):
        try:
            data = unpack(raw)
        except Exception:
            continue
        if data[:4] == b"dex\n":
            open(f"out_{n}.dex", "wb").write(data)
            print("saved", f"out_{n}.dex", len(data))
            break
```

2. открыть `out_1.dex` в [jadx](https://github.com/skylot/jadx/releases) (`jadx -d src out_1.dex` или jadx-gui). получится читаемый Java-код. Kotlin-код (NoForwardLimit) читается хуже из-за `Intrinsics.checkNotNull…`, но логика видна.

**скрипт ничего не выполняет**, он только декодирует строки. сам `.plugin` для этого запускать не нужно.

---

## что внутри DEX у разобранных плагинов

| плагин | автор | классов | что делает Java-часть (по декомпиляту) |
|---|---|---|---|
| Custom Profile | @RoflPlugins | ~400 | целый мини-клиент: свой сервер профилей, WebSocket, TLS, кастомный рендер профиля, хуки `onDraw`/`dispatchDraw`, адаптеров списков и `sendMessage` |
| Material Player [не доделан] | @RnPlugins | 30 | плагин не закончен автором. новый экран плеера в стиле Material Expressive, хуки `MainTabsActivity.createView`, `checkPlayer`; тексты песен через lrclib.net |
| Text Animation | @itskotovski & @mishabotov | 18 | анимации набора текста: появление букв, плавающий курсор, «рассыпание» стёртых символов |
| Продвинутый поиск | @dekma0091 | 8 | свой экран поиска по чатам с фильтрами по дате, юзеру и типу медиа |
| Photo Picker Plus | @dekma0091 | 6 | доработка `ChatAttachAlertPhotoLayout`: пиллы, даты, тулбар папок |
| NoForwardLimit | @zwylair | 6 | Kotlin; хуки `addToSelectedMessages`, `startMultiselect`, `limitReached`, `hideActionMode` у ChatActivity, чтобы снять лимит выделения сообщений |
| Settings Sync | @RnPlugins | 3 | синхронизация настроек exteraGram и плагинов (по описанию); хуки `fillItems`/`onClick` экрана настроек |
| Compact Bottom Nav | @YouRooni | 2 | хуки `MainTabsLayout`, `GlassTabView`, `DialogsActivity`: нижняя панель без подписей |
| Player Widget | @YouRooni | 2 | виджет плеера для рабочего стола Android |
| Spam Collapse | @dekma0091 | 2 | сворачивание повторяющихся сообщений |
| Системное меню текста | @YouRooni | 2 | см. пример выше |
| Chip Folders | @RnPlugins | 1 | панель папок-чипсов: хуки `FilterTabsView`, `DialogsActivity.onResume`, `canScrollHorizontally` |
| Log Overlay | @dexPlugin & др. | 1 | плавающее окно логов |
| Media Transformer | @eCubzPlugins | 1 | конвертация видео в кружки и аудио в голосовые |
| HideShortcuts | @RnPlugins | 1 | хуки `MediaDataController.buildShortcuts`/`pushDynamicShortcut`: убирает чаты из ярлыков лаунчера |
| TempSub | @itNotMax | 1 | заглушка, Python её не загружает |
