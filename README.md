# for-vibecoders

RU:
этот репозиторий создан специально для людей, что хотят вайбкодингом делать плагины для **ExteraGram 12.5.1+ и AyuGram на его основе**
репо — это общая коллекция: анализы и файлы плагинов, описания где что работает, каталог плагинов других авторов, ссылки на полезные источники и т.п.
хотите добавить свой плагин? откройте PR в [`community-plugins.md`](community-plugins.md) или напишите в тг ([@jaxbastard](https://t.me/jaxbastard)), чтобы добавить плагин с анализом

EN:
this repo is built specifically for people who want to do vibe coding to make plugins for **ExteraGram 12.5.1+ and AyuGram based on it**
repo is a shared collection: plugin analyses and files, descriptions of what works where, a catalog of plugins by other authors, links to useful sources, etc
also, all files in this repo will be in russian — sorry about that, i suggest using an ai translator or standard google translate
want to add your plugin? open a PR to [`community-plugins.md`](community-plugins.md) or hit up tg ([@jaxbastard](https://t.me/jaxbastard)) to add it with an analysis

---

## 📁 RU: структура / EN: structure

| папка, файл | RU: что внутри | EN: what's inside |
|-------------|----------------|-------------------|
| `allpg/` | папки плагинов, каждая содержит .plugin и <n>-analysis.md | plugin folders, each contains .plugin and <n>-analysis.md |
| `plugins-index.md` | список плагинов с анализами в этом репо | plugins with analyses stored in this repo |
| `community-plugins.md` | каталог плагинов, библиотек и сторов других авторов (ссылками) | catalog of plugins, libraries and stores by other authors (links) |
| `community/` | разбор ~55 чужих плагинов: каталог, безопасность, Java/DEX внутри плагинов, формат Elyx | review of ~55 third-party plugins: catalog, security, embedded Java/DEX, Elyx format |
| `repo-plus-context7.md` | почему репо + context7 лучше использовать вместе | why repo + context7 work better together |
| `context7.json` | настройки индексации репо в context7 | config for indexing this repo in context7 |
| `skill/` | скилл для ИИ-агентов по написанию плагинов (на основе makarworld/exteragram-plugin-skill) | agent skill for writing plugins (based on makarworld/exteragram-plugin-skill) |

---

## ✨ RU: плагины сообщества / EN: community plugins

RU: несколько плагинов других авторов, полный список с лицензиями в [`community-plugins.md`](community-plugins.md)
EN: a few plugins by other authors, the full list with licenses is in [`community-plugins.md`](community-plugins.md)

| name | author | RU | EN |
|---|---|---|---|
| [Auto-Forwarder](https://github.com/0x11DFE/Auto-Forwarder-Plugin) | 0x11DFE | автопересылка по правилам | rule-based auto forwarding |
| [SecCrypt](https://github.com/megasoot/SecCrypt) | megasoot | шифрование сообщений и фото | message & photo encryption |
| [Link Guard](https://github.com/L0lopop/Link-Guard) | L0lopop | проверка ссылок и чистка трекеров | link inspection & tracker removal |
| [Th3ProxyTools](https://github.com/Th3Nekit/Th3ProxyTools) | Th3Nekit | менеджер прокси | proxy manager |
| [extCLI](https://github.com/vcvkk/extCLI) | vcvkk | терминал в клиенте | terminal inside the client |

---

## 🔗 RU: полезные ссылки / EN: useful links

RU:
- [исходники Telegram для Android](https://github.com/DrKLO/Telegram/tree/009e97356f966bb81eceba113d210230bf383122) — база для понимания внутренностей
- [документация ExteraGram plugins](https://plugins.exteragram.app/docs) — официальная дока по plugin API
- [канал с плагинами](https://t.me/jxbplug) — канал с плагинами. владелец: [@jaxbastard](https://t.me/jaxbastard)
- [ExteraGram sources](https://github.com/Podyshka1/extera-full-decompiled) — содержит декомпилированный ExteraGram 12.5.1 и 12.9.0 через jadx
- [exteragram-plugin-skill](https://github.com/makarworld/exteragram-plugin-skill) — скилл для ИИ-агентов по написанию плагинов
 
EN:
- [Telegram for Android source](https://github.com/DrKLO/Telegram/tree/009e97356f966bb81eceba113d210230bf383122) — base for understanding internals
- [ExteraGram plugins docs](https://plugins.exteragram.app/docs) — official plugin API documentation
- [plugins channel](https://t.me/jxbplug) — channel with plugins. owner: [@jaxbastard](https://t.me/jaxbastard)
- [ExteraGram sources](https://github.com/Podyshka1/extera-full-decompiled) — contains decompiled ExteraGram 12.5.1 and 12.9.0 via jadx
- [exteragram-plugin-skill](https://github.com/makarworld/exteragram-plugin-skill) — agent skill for building plugins

---

<sub>apache-2.0 · ExteraGram 12.5.1+ · AyuGram based on it</sub>
