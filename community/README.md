# плагины сообщества: разбор

> здесь собраны плагины exteraGram / AyuGram других авторов, которые были разобраны для этого репо. самих `.plugin` файлов тут нет: у них нет открытой лицензии, поэтому репо хранит только описание и то, чему у плагина можно научиться. сами плагины ищите у авторов (ник указан в таблице).
>
> - [security.md](security.md) — как проверять чужие плагины и почему два плагина исключены
> - [java-dex.md](java-dex.md) — плагины с вшитым Java-кодом (DEX): как устроены и как их разбирать
> - [../community-plugins.md](../community-plugins.md) — плагины с открытой лицензией на GitHub (ссылками)

пометки в таблицах:
- **[DEX]** основная логика на Java, подробнее в [java-dex.md](java-dex.md)
- **[elyx]** плагин в формате Elyx (ZIP-проект вместо одного файла)
- **[только смотреть]** полезно как пример реализации, использовать не советуем
- **[не доделан]** автор не закончил плагин

---

## внешний вид и интерфейс

| плагин | автор | что делает | чему научиться |
|---|---|---|---|
| Liquid Glass [Fork] | @PluginProject · @w3b_0s1nt | стеклянные шапки и панели (exteraGram 12.9.0+) | хуки `ActionBar` (фон, цвет, режим), `ChatActivity.createView/onResume/onDestroy`, работа с `BlurredBackgroundDrawable` |
| Square Liquid Glass | @immat0x1, правки @la_cringe | уменьшает скругление размытых фонов | маленький и понятный пример: хук трёх перегрузок `BlurredBackgroundDrawable.setRadius` и подмена аргументов |
| Visual Ecstasy | @exoseo → @HzzzPlugins | разноцветный liquid glass, виньетка и другая визуальная настройка | свои настройки на `BottomSheet` и `SeekBarView` |
| Chip Folders [DEX] | @RnPlugins | панель папок в стиле чипсов Material 3 | хуки `FilterTabsView` и `DialogsActivity` из Java |
| Compact Bottom Nav [DEX] | @YouRooni | нижняя панель без подписей, Glass и Material 3 | хуки `MainTabsLayout`, `GlassTabView` |
| Material Player [DEX] [не доделан] | @RnPlugins | плеер в стиле Material Expressive | новый экран поверх стандартного плеера |
| Player Widget [DEX] | @YouRooni | виджет плеера на рабочий стол | виджет Android из плагина |
| Media Glow | @itskotovski & @mishabotov | мягкая подсветка по краям фото и видео в полноэкранном просмотре | хуки отрисовки `PhotoViewer` |
| Text Animation [DEX] | @itskotovski & @mishabotov | анимация набора текста, плавающий курсор | отрисовка анимаций в Java |
| UiTweaks [только смотреть] | @luvztroy | десятки мелких настроек интерфейса чата | огромная коллекция хуков `ChatMessageCell`, `ChatActivityEnterView`, счётчиков непрочитанного, фильтров медиа. требует QuantaHut, который сильно тормозит Telegram |
| Search Bar Control | @itNotMax | закрепляет строку поиска, сворачивает истории | подмена аргумента `DialogsActivity.setScrollY`, отмена `openSelfStories`, поиск полей по цепочке суперклассов |
| Selfie Flash Color | — | выбор цвета вспышки экрана в селфи-камере | короткий пример хука с диалогом выбора цвета |
| HideShortcuts [DEX] | @RnPlugins | убирает чаты из ярлыков лаунчера | хуки `MediaDataController.buildShortcuts` |
| Photo Picker Plus [DEX] | @dekma0091 | пиллы, даты и папки в выборе фото | хуки `ChatAttachAlertPhotoLayout` |
| Custom Profile [DEX] | @RoflPlugins | кастомный профиль со своим сервером, лайками, комментариями, привязкой музыки | очень большой Java-проект (~400 классов). данные уходят на сервер автора, см. [security.md](security.md) |

## чаты и сообщения

| плагин | автор | что делает | чему научиться |
|---|---|---|---|
| Spoiler Remover | @JasonVurhyz | убирает спойлеры с текста и медиа | два режима: визуальный (хук `ChatMessageCell.setMessageObject`) и постоянный (правка входящих апдейтов `TL_updateNewMessage`) |
| noLinkPreview | @RnPlugins with @PluginIDE | `.лх ссылка текст` отправляет превью ссылки без самой ссылки | ссылка-entity на невидимый символ `U+2060` и сдвиг остальных entities |
| Replacing Characters | @Nikita218000 | правила автозамены текста перед отправкой | хук отправки с пользовательскими правилами |
| Quote | @mihailkotovski & @JasonVurhyz | цитаты-картинки из выбранных сообщений | хуки выделения сообщений в `ChatActivity`, нативный рендер в стикер |
| Extended Message Details | @thrzxd • @kotilnya | технические данные сообщения, копирование JSON | хук конструктора `MessageDetailsPopupWrapper` (AyuGram) |
| Spam Collapse [DEX] | @dekma0091 | сворачивает повторяющиеся сообщения | — |
| Advanced Chat Search | @anivplugins & @mraniv | расширенный поиск по чатам | хук адаптера поиска, `TL_contacts_search` |
| Продвинутый поиск [DEX] | @dekma0091 | поиск с фильтрами по дате, юзеру, типу медиа | вызов методов DEX по имени (см. [java-dex.md](java-dex.md)) |
| Recent Actions+ | @anivplugins @mraniv | доработанный журнал действий канала | фильтры `TL_channelAdminLogEventsFilter` |
| NoForwardLimit [DEX] | @zwylair | снимает лимит выделения сообщений для пересылки | Kotlin в DEX, сжатие lzma, хуки выделения в `ChatActivity` |
| Chat Lock | @eCubzPlugins | пароль на чаты и папки, команды `.лок .анлок` | системная блокировка через `KeyguardManager`, хуки `ChatActivity`/`DialogsActivity`, пункт в меню чата |
| TempSub | @itNotMax | подписка на канал с автоотпиской по дате | кнопка рядом с «Подписаться», `channels.joinChannel/leaveChannel`, архивация, периодическая проверка |
| DragnDrop Send | @koshbko | отправка файлов перетаскиванием из других приложений | `View.OnDragListener` через `dynamic_proxy`, `SendMessagesHelper.prepareSendingMedia` |
| Системное меню текста [DEX] | @YouRooni | действия Android в меню выделения текста | подкласс `ActionMode.Callback2` в Java (разобран в [java-dex.md](java-dex.md)) |
| Translatica Pro | @AGeekApple | перевод и пересказ сообщений прямо в чате | `messages.translateText`, `messages.summarizeText`, хук `ChatMessageCell.setMessageObject` |
| Audio Size Timer | @vutarn | размер файла рядом с таймером аудио | хуки `measureTime` и ячеек аудио |
| Media Transformer [DEX] | @eCubzPlugins | видео в кружки, аудио в голосовые | — |
| In-App Notifications (fork) | @meeownnews, форк @jaxbastard | уведомления внутри приложения | хуки `NotificationManager.notify` |

## голос и ИИ

| плагин | автор | что делает | чему научиться |
|---|---|---|---|
| n0transcriber | @n0white | расшифровка голосовых через Groq Whisper, очистка текста LLaMA | полная замена `TranscribeButton.onTap` и запись результата в нативную расшифровку Telegram |
| Voice to Text | @PESSDES_Plugins | расшифровка через Deepgram, текст в подпись голосового | `messages.editMessage` с цитатой |
| Termux Bridge | @S1mclick | скрипты и нейросети из Termux поверх клиента | локальный сокет с токеном, см. [security.md](security.md) |

## музыка, медиа, развлечения

| плагин | автор | что делает | чему научиться |
|---|---|---|---|
| Music Downloader | @s1mclick | поиск и скачивание из SoundCloud, Spotify, Tidal | команды `.find .download .rec` и меню сообщения |
| Pomme | @AGeekApple | музыкальный плеер из поиска чатов, плейлисты | много хуков плеера и `MediaController` |
| nowMedia | @RooniPlugin | карточка того, что играет в системе, трансляция в профиль | нужен отдельный APK-компаньон |
| Nowfy Lite [elyx] | @AGeekApple | карточка текущего трека | пример большого Elyx-проекта с модулями |
| Steam | @KangelPlugins & @MGEPlugins | текущая игра, профиль, библиотека Steam | команды `.snp .sp`, вывод в профиль |
| petpet | @limeplug | гифка petpet из аватарки, фото или стикера | три вида пунктов меню (сообщение, профиль, чат) с `condition` |
| BooruSearch [elyx] | @ArThirtyFour | поиск по booru-сайтам (18+) | архитектура на миксинах: роутеры, парсеры, настройки в разных модулях |

## для разработчиков и системные

| плагин | автор | что делает | чему научиться |
|---|---|---|---|
| MiniApp DevTools | @xusanboyman200 | DevTools (eruda) внутри мини-приложений | хуки `WebView` и внедрение JS через `evaluateJavascript` |
| Log Overlay [DEX] | @dexPlugin & @koshbko & @mihailkotovski | плавающее окно логов | — |
| LogOverlay | @YouRooni | окно логов с командой и пунктом в боковом меню | хук логгера приложения |
| File Viewer & Editor | @JavaScript_XD | просмотр и правка текстовых файлов, `.openfile` | плавающее окно через `WindowManager` |
| neofetch | @bandaliyev | `.neo` отправляет данные устройства | самый простой пример команды с заменой текста и цитатой |
| exteraFetch | @shareui | то же самое в стиле neofetch | — |
| Server Status | @YouRooni | пинг датацентров и веб-сервисов | своя кнопка в настройках exteraGram (`MainPreferencesActivity.fillItems/onClick`) и экран на `UniversalFragment` |
| RAM-Info Pill | @YouRooni | память и батарея в виджете-пилле | регистрация своего пилла через `PillRegistry` |
| Settings Sync [DEX] | @RnPlugins | синхронизация настроек клиента и плагинов | — |
| Запись экрана | @swagnonher | запись экрана из клиента | `onActivityResult` для системного разрешения |
| Device Fingerprint Spoofer | @Daxo_OS | подмена модели устройства в списке сеансов | только для понимания; меняет то, что видит сервер Telegram |
| Plugin Security | @mihailkotovski & @mishabotov | проверка плагинов на опасный код, локально и через ИИ | эвристики поиска опасных паттернов, см. [security.md](security.md) |
| Plugin Verifier | @JasonVurhyz | локальная проверка плагинов и сверка с базой проверенных | распаковка вшитых DEX и подсветка кода в `BottomSheet`, см. [security.md](security.md) |
| Heroku Host | @swagnonher & @codrago | запуск юзербота Heroku внутри клиента | см. [security.md](security.md) |

## плагины для плагинов и библиотеки

| плагин | автор | что делает | чему научиться |
|---|---|---|---|
| Kangel Plugins Manager [elyx] | @KangelPlugins | менеджер и магазин плагинов | крупный Elyx-проект: хуки экранов плагинов, установщик, анализ плагинов |
| Sorter+ | @plugin_ai | сортировка плагинов по папкам | хуки `PluginsActivity` и `PluginCell` |
| Better Search | @shareui | лучший поиск в списке плагинов | хук `PluginsActivity.fillItems` |
| ShareUI | @shareui | делиться плагином через окно Telegram вместо системного | хук `PythonPluginsEngine.sharePlugin`, `ShareAlert` |
| ZwyLib | @zwylair | библиотека: автообновление, кэш, команды, логи, локализация | диспетчер команд с разбором аргументов |
| QuantaHut [только смотреть] | @luvztroy | библиотека для плагинов Quanta | реестр пунктов меню сообщений, поиск по настройкам. сильно тормозит Telegram |
| MandreLib | @swagnonher & @MandreAI_bot | большая библиотека: UI, TTS, уведомления, pip, hot-reload | автор прямо пишет «All Rights Reserved» |

---

## не вошли

- **Time Nickname** — заражённая копия, см. [security.md](security.md)
- **TheLooker** — слежка и закрытое ядро с чужого сервера, см. [security.md](security.md)
- дубликаты и старые версии (Material Player 1.0.0 ×3, Player Widget, Visual Ecstasy, Custom Profile) — оставлено по одной версии
