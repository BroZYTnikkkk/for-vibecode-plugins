# Text Formatting (extera_utils.text_formatting)

Source: `from extera_utils.text_formatting import parse_text, TLEntityType, RawEntity`

Parses HTML or Markdown text into a plain string + list of `TLRPC.MessageEntity` objects.

You usually do **not** need this module directly — `client_utils.send_message` / `send_text` / etc. accept a `parse_mode` argument that handles parsing for you. Use `parse_text` when you need to manually parse text for other purposes.

## `parse_text`

```python
from extera_utils.text_formatting import parse_text

def parse_text(text: str, parse_mode: str = "HTML", is_caption: bool = False) -> dict:
    ...
```

Parameters:
- `text`: input string with formatting tags or markdown.
- `parse_mode`: `"HTML"` (default) or `"Markdown"`.
- `is_caption`: if `True`, the returned dict key is `"caption"`; otherwise `"message"`.

Returns a dict with:
- `"message"` (or `"caption"`): plain text with formatting markers removed.
- `"entities"`: list of `TLRPC.MessageEntity`.

```python
from extera_utils.text_formatting import parse_text

html_input = "<b>Bold</b>, <i>Italic</i>, <a href='https://example.com'>Link</a>"
parsed = parse_text(html_input, parse_mode="HTML")
# {
#   "message": "Bold, Italic, and Link",
#   "entities": [TL_messageEntityBold(...), TL_messageEntityItalic(...), TL_messageEntityTextUrl(...)]
# }

md_input = "**Bold**, __Italic__, and [Link](https://example.com)"
parsed_md = parse_text(md_input, parse_mode="Markdown")
```

## Supported Formatting

### HTML tags

| Tag | Effect |
|-----|--------|
| `<b>`, `<strong>` | Bold |
| `<i>`, `<em>` | Italic |
| `<u>` | Underline |
| `<s>`, `<del>`, `<strike>` | Strikethrough |
| `<a href="...">` | Text link |
| `<code>` | Inline code |
| `<pre language="...">` | Preformatted block (`language` optional) |
| `<spoiler>`, `<tg-spoiler>` | Spoiler |
| `<blockquote>` | Blockquote (add `expandable` or `collapsed` attr for expandable) |
| `<emoji id="...">` | Custom emoji |

### Markdown syntax

| Syntax | Effect |
|--------|--------|
| `*bold*` | Bold |
| `_italic_` | Italic |
| `__underline__` | Underline |
| `~strikethrough~` | Strikethrough |
| `\|\|spoiler\|\|` | Spoiler |
| `` `code` `` | Inline code |
| ` ```code block``` ` | Preformatted block |
| ` ```python ... ``` ` | Code block with language |
| `[text](url)` | Text link |
| `![alt](tg://emoji?id=123)` | Custom emoji |
| `> Quote` | Blockquote |
| `**> Quote` | Expandable quote |

## Helper Classes

### `TLEntityType`

Enum of supported entity types: `CODE`, `PRE`, `STRIKETHROUGH`, `TEXT_LINK`, `BOLD`, `ITALIC`, `UNDERLINE`, `SPOILER`, `CUSTOM_EMOJI`, `BLOCKQUOTE`.

### `RawEntity`

Intermediate representation before conversion to `TLRPC`. Contains `offset`, `length`, and extra attributes like `url`, `language`, `document_id` (emojis), `collapsed` (blockquotes).

## Parse mode in send helpers

`parse_mode` is case-insensitive and currently supports only `html` and `markdown`. When provided, the SDK parses `message` or `caption` and fills entities:

```python
from client_utils import send_text

send_text(peer, "**Hello** from my *plugin*!", parse_mode="Markdown")
send_text(peer, "This is <b>bold</b>.", parse_mode="HTML")
```
