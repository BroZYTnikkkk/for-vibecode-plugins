# for-vibecode-plugins Repository Conventions

Repo: https://github.com/BroZYTnikkkk/for-vibecode-plugins (fork of [corerudo/for-vibecoders](https://github.com/corerudo/for-vibecoders)).
Raw base for fetching files: `https://raw.githubusercontent.com/BroZYTnikkkk/for-vibecode-plugins/main/`

The repo is a collection of **practical examples and analyses** of real exteraGram 12.5.1+ / AyuGram plugins. It is not a full API reference and not a limit on what plugins can do. Analyses are written in **Russian**.

## Layout

| Path | What's inside |
|------|---------------|
| `allpg/<Name>/<name>.plugin` | source of a plugin stored in this repo (Python, `.plugin` = source, no build step) |
| `allpg/<Name>/<name>-analysis.md` | what did not work and why, what works, architecture, links to docs |
| `plugins-index.md` | table of plugins in `allpg/` (name, version, description, plugin link, analysis link) |
| `community/README.md` | catalog of ~55 third-party plugins by topic, with a "чему научиться" (what to learn) column |
| `community/analyses/*.md` | detailed teardowns of single third-party plugins |
| `community/security.md` | how to vet third-party plugins, excluded/malicious plugins |
| `community/java-dex.md` | plugins with embedded Java (base64 DEX via `InMemoryDexClassLoader`) and how to decompile them |
| `community/elyx.md` | Elyx format as seen in real plugins |
| `community-plugins.md` | links to openly licensed plugins on GitHub |
| `skill/` | this skill: `reference/*.md`, `examples/*.py` |

## Before Writing or Editing a Plugin

1. Search `plugins-index.md`, `allpg/*/*-analysis.md` and `community/README.md` for a plugin that hooks the same screen/class. Reuse the proven pattern; the analyses explain **why** it works.
2. Read the "Что не работало и почему" section of related analyses — it lists real dead ends (e.g. `Hook` is not exported from `base_plugin`; `add_on_create_menu_hook` does not exist, menus go through `hook_method` + reflection — see `allpg/LodraBu/LodraBu-analysis.md`).
3. Class and method names can change between app versions (R8). Verify against the target version: [decompiled exteraGram 12.5.1 / 12.9.0](https://github.com/Podyshka1/extera-full-decompiled), [Telegram for Android sources](https://github.com/DrKLO/Telegram/tree/009e97356f966bb81eceba113d210230bf383122).
4. For SDK behavior the official docs win: https://plugins.exteragram.app/docs

## Adding Your Own Plugin to the Repo

```
allpg/<Name>/
  <name>.plugin            # source; __version__ as a plain top-level constant
  <name>-analysis.md       # in Russian: что не работало и почему / что работает / архитектура
```

- Add a row to `plugins-index.md` with links in the form `https://github.com/BroZYTnikkkk/for-vibecode-plugins/blob/main/allpg/<Name>/<file>` (URL-encode spaces as `%20`).
- Keep the analysis honest: record failed approaches with the error, then the fix.
- Optional but recommended: `ruff check allpg/<Name>/<name>.plugin`; suppress SDK-import complaints per line with `# noqa`.

## Third-Party Plugins

- No third-party plugin seen so far carries an open license, so **never commit their `.plugin` files**. Commit only our own analysis, the recipe, and short credited excerpts (author nick next to the snippet).
- Openly licensed plugins go into `community-plugins.md` as links.
- Plugins marked `[только смотреть]` or `[не доделан]` are references, not dependencies.

## Security Check (any foreign code, before copying from it)

Red flags — stop and report instead of reusing the code:

- `exec` / `compile` / `eval` on decoded data, base64 or XOR blobs (`bytes.fromhex`, `_ld=`), a `# === injected ===` block
- network calls to a bare `IP:port` or unknown hosts (`urllib`, `requests`, `http://…`)
- DEX downloaded at runtime and loaded with `InMemoryDexClassLoader` (embedded base64 DEX is common and fine to decompile with jadx; *downloaded* DEX is not)
- tracking other users, exfiltrating messages/sessions

Known cases are documented in `community/security.md` (infected Time Nickname copy, TheLooker).
