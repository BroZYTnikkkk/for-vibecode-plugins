# Class Proxy (extera_utils.classes)

Source: `from extera_utils.classes import Base, java_subclass, joverride, joverload, jmethod, jfield, jconstructor, jpreconstructor, jMVELmethod, jMVELoverride, jclassbuilder, jgetmethod, jsetmethod`

Create a real Java subclass at runtime and implement it in Python. Built on DexMaker — the result is an actual Java class passable anywhere that type is expected.

`new_instance()` returns a **Python peer**, not the raw Java instance. Use `.java` when an API explicitly requires the Java object.

## Quick Start

```python
from extera_utils.classes import Base, java_subclass, joverload, jfield
from java.util import ArrayList


@java_subclass(ArrayList)
class CountingList(Base):
    added_count = jfield("int", default=0)

    @joverload("add", ["java.lang.Object"])
    def add_item(self, value):
        self.added_count += 1
        return super().add_item(value)


items = CountingList.new_instance()
items.add("Hello")
items.add("world")
```

What happens:
- `CountingList` becomes a generated Java subclass of `java.util.ArrayList`
- `added_count` is a real Java field on the class
- `add(Object)` is overridden in Java and routed into Python
- `super().add_item(...)` calls the original parent Java implementation

## Creating a Java Subclass

```python
@java_subclass(SomeJavaClass)
class MySubclass(Base):
    ...
```

With interfaces:

```python
@java_subclass(FrameLayout, CustomDelegate1, CustomDelegate2)
class MyCell(Base):
    ...
```

Equivalent to `class GeneratedProxy extends FrameLayout implements CustomDelegate1, CustomDelegate2`.

### Custom generated class name

Requires app version code `>= 66690`. Control the middle of the generated name:

```python
@java_subclass(Object, custom_name="DialogCell")
class Test(Base):
    ...
# Generates: Proxy_Object_DialogCell_<hashcode>_<randomnum>
```

### Bind after definition

```python
class MySubclass(Base):
    ...

MySubclass.bind(SomeJavaClass)
MySubclass.bind(FrameLayout, CustomDelegate1, CustomDelegate2)  # with interfaces
```

### Get the Java class and create instances

```python
proxy_java_class = MySubclass.java_class()

instance = MySubclass.new_instance()
instance2 = MySubclass.new_instance("text", 123)   # Java constructor args

java_instance = instance.java
java_instance2 = MySubclass.new_java_instance("text", 123)
```

Separate Python init args:

```python
instance = MySubclass.new_instance("java ctor value", init_args=["python init value"])
```

Recover a Python peer from an existing Java instance:

```python
peer = MySubclass.from_java(existing_java)
```

## Overriding Methods

### Simple override (same Python name)

```python
@java_subclass(SomeJavaClass)
class MySubclass(Base):
    @joverride()
    def onClick(self, view):
        print("Clicked")
```

### Override with different Python name

```python
@joverride("equals")
def equals_(self, a, b):
    return a == b
```

### Overloaded methods — use `@joverload`

```python
@java_subclass(SomeJavaClass)
class MySubclass(Base):
    @joverload("setValue", ["int"])
    def set_value_int(self, value):
        print("int overload", value)

    @joverload("setValue", ["java.lang.String"])
    def set_value_text(self, value):
        print("string overload", value)
```

For overloaded Java methods, **prefer explicit signatures** over bare `@joverride()`.

### Type formats

- primitive names: `"int"`, `"boolean"`, `"long"`, `"byte"`, `"char"`, `"short"`, `"float"`, `"double"`, `"void"`
- fully-qualified class names: `"java.lang.String"`
- Java classes from `jclass(...)`

```python
from java import jclass
View = jclass("android.view.View")

@joverload("setView", [View])
def set_view(self, view):
    ...
```

### Calling parent methods with `super()`

For overridden methods, `super()` works like a normal Python call:

```python
@java_subclass(SomeJavaClass)
class MySubclass(Base):
    @joverride()
    def onClick(self, view):
        result = super().onClick(view)
        return result
```

For overloaded methods, call the Python method name you defined:

```python
@joverload("setValue", ["int"])
def set_value_int(self, value):
    return super().set_value_int(value)
```

Use `super()` **only** for methods marked with `@joverride(...)` / `@joverload(...)`.

## Adding New Java Methods

`@jmethod` declares a method that doesn't exist on the parent.

```python
@java_subclass(SomeJavaClass)
class MySubclass(Base):
    @jmethod("debugLabel", "java.lang.String", ["int"])
    def build_debug_label(self, value):
        return f"value={value}"
```

Signature forms:
- `@jmethod(return_type, [arg_types])`
- `@jmethod(name, return_type, [arg_types])`
- `@jmethod()` — infer from Python annotations: `def f(self, x: "int") -> "java.lang.String":`

Explicit types are still recommended when the Java signature matters.

## MVEL Methods (Java-side hot paths)

For frequently-called methods with simple logic, generate a method body executed by MVEL instead of calling into Python.

```python
from extera_utils.classes import Base, java_subclass, jMVELmethod

@java_subclass(SomeJavaClass)
class MySubclass(Base):
    debug_label = jMVELmethod(
        return_type="java.lang.String",
        arguments=[("prefix", "java.lang.String"), ("value", "int")],
        code='''
            return prefix + ": value=" + value + ", class=" + java.getClass().getSimpleName();
        ''',
    )
```

Override parent methods with MVEL: `jMVELoverride(...)`. For overloaded parents, pass explicit argument types. Inside MVEL overrides, the generated `SUPER_<methodName>(...)` bridge is available.

### MVEL context

Inside MVEL, the root object is the generated Java instance:
- `java`: the same generated Java instance
- `python` / `py` / `self`: the attached Python peer
- `args`: `Object[]` of all method arguments
- `argc`: number of arguments
- `arg0`, `arg1`, ...: positional arguments
- named arguments from `arguments=[("name", "type"), ...]`

Keep MVEL bodies small and predictable. If logic needs Python objects or complex state, regular Python overrides are easier to maintain.

## Adding Java Fields

```python
@java_subclass(SomeJavaClass)
class MySubclass(Base):
    counter = jfield("int", default=0)
    title = jfield("java.lang.String", default="Hello")
```

Read/write like normal Python attributes:

```python
self.counter += 1
self.title = "Updated"
```

### Java-only getter/setter (hot paths)

Generate a Java-only accessor that doesn't call into Python:

```python
from extera_utils.classes import jfield, jgetmethod, jsetmethod

@java_subclass(SomeJavaClass)
class MySubclass(Base):
    shadow_value = jfield(
        "boolean",
        default=False,
        methods=[
            jgetmethod("isShadow"),
            jsetmethod("setShadow"),
        ],
    )
```

Generates: field `shadow_value` + Java `isShadow()` / `setShadow(boolean)` — fastest option for repeated UI queries.

## Constructors

Two stages: `@jpreconstructor` (before parent ctor) and `@jconstructor` (after Java object exists).

### Pre-constructor — modify args

```python
@jpreconstructor(["java.lang.String"])
def normalize_text(cls, text):
    return [text.strip()]   # None keeps original, list/tuple replaces, single value for 1-arg ctor
```

### Post-constructor — init Python state

```python
@java_subclass(SomeJavaClass)
class MySubclass(Base):
    initialized = jfield("boolean", default=False)

    @jconstructor(["java.lang.String"])
    def init_from_text(self, text):
        self.initialized = True
        self.last_text = text
```

### Generic init: `__init__` and `on_post_init`

```python
@java_subclass(SomeJavaClass)
class MySubclass(Base):
    def __init__(self, text):
        self.python_only_state = text

    def on_post_init(self, text):
        print("Java object ready:", self.java)
```

Init order: `@jpreconstructor` → Java parent ctor → Python `__init__` → matched `@jconstructor` → `on_post_init`.

By default, Python `__init__` receives the same args as the Java ctor. Override with `new_instance(..., init_args=[...])`.

## Accessing the Java Instance

Inside a managed subclass:
- `self.java` — the attached Java instance
- `self.this` — alias to `self.java`

```python
@java_subclass(SomeJavaClass)
class MySubclass(Base):
    @joverride()
    def onAttached(self):
        print(self.java.getClass().getName())
```

Fallback: if Python can't find an attribute on the peer, it falls back to the Java instance:

```python
self.getContext()
self.hashCode()
```

But if a Java API checks the exact runtime type, pass `instance.java`.

## Built-in Java Object Modifiers

Available directly in the Chaquopy fork for any Java object/class:

| Modifier | Scope | Effect |
|----------|-------|--------|
| `.JA` / `.JNA` | persistent | access (non-public declared members) on/off |
| `.JGS` / `.JNGS` | persistent | getter/setter preference on/off |
| `.JIR` / `.JNIR` | chain only | ignore result (chain returns receiver) |
| `.JS` / `.JNS` | chain only | safe optional chaining (`JNone` on missing) |

Defaults: getter/setter ON, access-all OFF, safe OFF, ignore-result OFF.

### Getter/Setter mode (default ON)

Field-like names prefer JavaBean accessors:

```python
title = obj.title       # uses getTitle() if it exists
obj.title = "Updated"   # uses setTitle(...)
```

Disable with `obj.JNGS`, re-enable with `obj.JGS`.

### AccessAll mode

```python
obj.JA
secret = obj.secretField    # private/protected now accessible
obj.secretMethod()
obj.JNA
```

Works on classes for static members too.

### IgnoreResult mode

Method chain keeps returning the original receiver:

```python
obj.JIR.setTitle("Hello").requestLayout().invalidate()
# Normal behavior resumes outside the chain.
value = obj.JIR.method1().method2().JNIR.method4()
```

### Safe mode

If any attribute/method is missing, the chain becomes `JNone` instead of raising:

```python
value = obj.JS.info.details.title     # JNone if any step missing
value = obj.JS.missing.anything.call()
```

Safe mode propagates through returned Java objects and converts `None` to `JNone` inside the chain.

### `JNone`

Sentinel from safe chains on access failure. Falsy, swallows attribute access and calls, comparable by identity.

```python
from java import JNone

result = obj.JS.maybeNull.value
if result is JNone:
    print("No value")
```

## When to Use Class Proxy

Use when:
- a Java API requires **subclassing** (not interface proxying)
- you need `super()` to the parent implementation
- you need overload-specific behavior
- you want Java fields or extra Java methods on the object

Do **not** use when a simple `dynamic_proxy(...)` is enough for an interface. Also make sure the base Java class is actually subclassable — **final classes cannot be used** as a proxy base.

## Troubleshooting

- **`super()` does not work** — method must be declared with `@joverride(...)` / `@joverload(...)`, and the name/signature must match the Java parent.
- **My overload is not called** — verify the Java name and exact arg types (primitive types use primitive names like `"int"`, not wrapper classes).
- **Constructor hook not called** — verify the signature matches a real constructor, or you intentionally used a wildcard.
- **Field value always `None`** — declared with `jfield(...)`, valid field type, compatible default value.
- **Class generation fails immediately** — base class not final, constructor signatures match real ones, overload signatures match real Java arg types.
