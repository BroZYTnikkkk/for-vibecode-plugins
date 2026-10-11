# формат Elyx (.elyx / .eaf)

Сводка по официальной документации exteraGram ([plugins.exteragram.app/docs/elyx](https://plugins.exteragram.app/docs/elyx)) и живому примеру [shareui/packit-source](https://github.com/shareui/packit-source). Исходники [KangelPlugins/PluginManager](https://git.kangel.xyz/KangelPlugins/PluginManager) прочитать не удалось: сервер закрыт для ботов (robots.txt) и недоступен из этого окружения. По README видно, что он собирается через ElyxBuilder (`elyb build`) и в корне у него лежит `refmap.json`, то есть это тоже Elyx-плагин.

> Правильное название формата **Elyx** (через «y»), расширения `.elyx` или `.eaf`.

## Что это такое

- Elyx не новый движок, а **упаковка поверх того же Python SDK**. Внутри всё равно класс-наследник `BasePlugin` с теми же `on_plugin_load`, хуками, `create_settings`, `ui.settings`, `client_utils`, `hook_utils` и т.д.
- Отличие от `.plugin`: вместо одного `.py` файла это **ZIP-архив с проектом**: много модулей и пакетов, ассеты (SVG, PNG, Lottie, JSON), отдельные файлы локализации, вшитые `.whl`, метаданные в отдельном файле, live-reload с ПК.
- Совместимость: в примерах `app_version: ">=12.5.1"`, `sdk_version: ">=1.4.5.3"` (PackIt требует `>=12.9.0`). Рантайм Python 3.11.

## Устройство архива

ZIP, переименованный в `.elyx` / `.eaf` (принимаются также `.elyx.zip`, `.eaf.zip`, есть поддержка запароленных архивов). В **корне** архива обязательно лежит `refmap.yml` (или `.yaml` / `.json`), без обёртки-папки.

```
my_plugin.elyx
├── refmap.yml        # карта путей
├── metainfo.yml      # метаданные
├── main.py           # точка входа, один класс BasePlugin
├── src/__init__.py, feature.py
├── assets/logo.svg
└── strings/strings_en.yml, strings_ru.yml
```

### refmap.yml — ключи

| Ключ | Что указывает | По умолчанию |
|---|---|---|
| `metainfo` | файл метаданных (YAML/JSON/Python) | `metainfo.*` в корне |
| `main` | entry-модуль с классом `BasePlugin` (берётся первый найденный) | `main.py` в корне |
| `assets` | папка ресурсов | `assets/` в корне |
| `strings` | файл или папка локалей | — |
| `wheels` | папка с `.whl` | — |
| `elyxbuilder` | служебная папка сборщика | — |

Реальный пример (PackIt):
```yaml
metainfo: packit/meta.yml
main: packit/src/python/BasePlugin.py
strings: packit/locales
assets: packit/res
elyxbuilder: packit/.elyxbuilder
wheels: packit/wheels
```

### metainfo.yml

Заменяет `__id__`, `__name__`, `__version__` и т.п. из `.plugin` (в `main.py` их больше нет).

| Поле | Обяз. | Смысл |
|---|---|---|
| `id` | да | 2–32 символа, `[A-Za-z0-9_]`, менять нельзя |
| `name` | да | отображаемое имя |
| `description` | нет | Markdown, поддерживает `{key}` из локалей |
| `author`, `version`, `icon` | нет | `icon` вида `exteraPlugins/1` |
| `app_version`, `sdk_version` | нет | выражения вида `">=12.5.1"` (`min_version` устарел) |
| `requirements` | нет | pip-пакеты через запятую, ставятся до импорта `main` |
| `requires` | нет | другие плагины: `plugin_id (2.1.0): https://…/x.elyx` |

## Публичный API `from elyx import …`

- `settings` — настройки плагина: `get(key, default)`, `set(key, value, reload_settings=False)`, `settings["k"]`, `clear_settings()`. То же хранилище, что и `BasePlugin.get_setting`.
- `strings` — локализация: `strings("greeting", name="Bob")`, `strings.title`, `strings.get("k", "fallback")`, `strings.get_with_locale`, `strings.pluralize(21, "file_forms")`. Локаль берётся из суффикса файла (`strings_ru.yml` → `ru`), фолбэк: текущая → `en` → сам ключ.
- `assets` — ресурсы: `assets.logo`, `assets["icons/add"]`, у объекта `Asset` есть `path`, `content_json()`, `to_drawable()`, `to_svg_drawable()`, `to_lottie_drawable()`, `to_image_location()` и др. Имена нормализуются (`empty-state.svg` → `assets.empty_state`).
- `metainfo`, `refmap`, `get_environment()` — данные о самом плагине.
- `import_module(name)` — динамический импорт локального модуля (вместо `importlib`).
- Java-хелперы: `Runnable`, `OnClickListener`, `Callback`…`Callback3`, `CallbackReturn`, `gen`, `gen2` (прокси Java-интерфейсов), `mvel_execute`, `LazyDict`, `Strings`, `SettingsController`.

Импортировать можно только из `elyx`, внутренние модули движка приватные.

## Импорты и изоляция

- Каждый плагин живёт в своём неймспейсе `ElyxPlugins.<id>.*`, поэтому одинаковые `src/utils.py` у разных плагинов не конфликтуют.
- Работают обычные и относительные импорты, `.pyc` (только Python 3.11), а также импорт `config.json` / `.yaml` / `.txt` как модулей.
- Нельзя называть свои пакеты `android`, `androidx`, `base_plugin`, `client_utils`, `com`, `de`, `elyx`, `hook_utils`, `importlib`, `java`, `org`, `ui`.
- При выгрузке Elyx чистит модули плагина, но потоки, сокеты и слушатели нужно останавливать самому в `on_plugin_unload`.

## Сборка: ElyxBuilder

```
pip install --upgrade ElyxBuilder
elyb new -g -n "My Plugin" -a myname --zipformat elyx   # шаблон проекта
elyb build --ast -v -nf      # сборка из исходников с проверкой AST
elyb build -c 2 -v -nf       # сборка в .pyc (нужен Python 3.11)
elyb watch 10 --args "--ast -v -nf"   # пересборка при изменениях
```

Результат кладётся в `builds/`. Ignore-листы задаются в `.elyxbuilder/config.yml` (`ignoreAll`, `optionalAssets`, `compilationIgnore`; в PackIt там ещё `obfuscationConfig`). Без ElyxBuilder можно просто заархивировать содержимое папки в ZIP и переименовать. Документация сборщика: [github.com/shareui/ElyxBuilder](https://github.com/shareui/ElyxBuilder).

## Установка и разработка

- Установка: открыть `.elyx` в exteraGram, посмотреть метаданные и предупреждения, установить. На устройстве плагин распаковывается в `/plugins/ElyxPlugins/<id>/`.
- Live-reload: dev-сервер на `127.0.0.1:42690` (`adb forward tcp:42690 tcp:42690`), JSON-протокол с командами `elyx_ping`, `get_elyx_plugins`, `elyx_compare_folder`, `elyx_changes`. Клиент `elyx_dev_client.py` в SDK не входит. Перед live-reload плагин нужно один раз поставить из архива.

## Продвинутое: что умеют реальные Elyx-плагины

PackIt кладёт в архив скомпилированный Kotlin (`dex/packit.dex`, грузится через `InMemoryDexClassLoader`) и нативные `.so` под `arm64-v8a` / `armeabi-v7a`. PluginManager по README тоже проверяет у плагинов DEX/SO и сетевые вызовы. То есть формат позволяет таскать с собой Java/Kotlin-код и нативные библиотеки, чего однофайловый `.plugin` нормально не умеет.

## как это выглядит у разобранных плагинов

три плагина из [каталога](README.md) пришли в формате Elyx. все собраны через ElyxBuilder (в архиве есть `.elyxbuilder/`), у всех код вынесен в одну папку, а `refmap` указывает внутрь неё:

```json
{
  "metainfo": "kpmplugin/metainfo.json",
  "main": "kpmplugin/src/main.py",
  "strings": "kpmplugin/locales",
  "assets": "kpmplugin/res",
  "elyxbuilder": "kpmplugin/.elyxbuilder"
}
```
<sub>Kangel Plugins Manager (@KangelPlugins)</sub>

| плагин | автор | как разложен код |
|---|---|---|
| Kangel Plugins Manager | @KangelPlugins | `src/` делится на `hooks/`, `mixins/`, `views/`, `security/`, `compat/` и отдельные модули магазина, установщика и разбора `.elyx`; локали в JSON на несколько языков |
| BooruSearch | @ArThirtyFour | плоский `src/`: `routers/` (по модулю на сайт), `parsers.py`, `handlers.py`, `settings.py`, `proxy.py`; главный класс собирается из миксинов |
| Nowfy Lite | @AGeekApple | `src/` с `rest/`, `themes/`, `addons/`, много PNG в ассетах; метаданные в `meta.yml` |

главный класс BooruSearch целиком собран из миксинов, по одному на модуль:

```python
from .routers import BooruRoutersMixin
from .parsers import BooruParsersMixin
from .settings import BooruSettingsMixin
from .handlers import BooruHandlersMixin
from .proxy import BooruProxyMixin

class BooruSearch(BooruRoutersMixin, BooruParsersMixin, BooruSettingsMixin,
                  BooruHandlersMixin, BooruProxyMixin, BasePlugin):
    ...
```
<sub>BooruSearch (@ArThirtyFour)</sub>

`BasePlugin` стоит последним, чтобы методы миксинов имели приоритет. каждый миксин работает с `self` как с плагином, поэтому `self.get_setting`, `self.add_hook` и т.д. доступны в любом модуле. метаданные можно хранить в JSON вместо YAML: так сделали Kangel и BooruSearch.

## .plugin и .elyx

| | `.plugin` | `.elyx` / `.eaf` |
|---|---|---|
| Что это | один `.py` файл | ZIP-проект |
| Метаданные | `__id__`, `__name__` и т.д. в коде | `metainfo.yml` |
| Модули | всё в одном файле | любые пакеты, изоляция по id |
| Ресурсы, локали | вшивать строками в код | `assets/`, `strings/` + API |
| Зависимости | `__requirements__` (pip) | pip + свои `.whl` + `requires` на другие плагины |
| Байткод | нет | можно `.pyc` (3.11) |
| Сборка | не нужна | ZIP вручную или `elyb build` |
| Когда брать | маленький плагин без ресурсов | многомодульный, с UI, ассетами, переводами |

## Источники

- [Elyx](https://plugins.exteragram.app/docs/elyx), [Quick Start](https://plugins.exteragram.app/docs/elyx/quick-start), [ElyxBuilder](https://plugins.exteragram.app/docs/elyx/elyxbuilder), [Project Structure](https://plugins.exteragram.app/docs/elyx/project-structure), [Metadata](https://plugins.exteragram.app/docs/elyx/metadata), [Modules](https://plugins.exteragram.app/docs/elyx/modules-and-imports), [Assets](https://plugins.exteragram.app/docs/elyx/assets), [Localization](https://plugins.exteragram.app/docs/elyx/localization), [Settings](https://plugins.exteragram.app/docs/elyx/settings), [Dependencies](https://plugins.exteragram.app/docs/elyx/dependencies), [Development](https://plugins.exteragram.app/docs/elyx/development), [Public API](https://plugins.exteragram.app/docs/elyx/public-api), [Troubleshooting](https://plugins.exteragram.app/docs/elyx/troubleshooting)
- [shareui/packit-source](https://github.com/shareui/packit-source): рабочий открытый Elyx-плагин, удобно смотреть как образец
- [KangelPlugins/PluginManager](https://git.kangel.xyz/KangelPlugins/PluginManager): прочитан только README
