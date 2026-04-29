# Chapter 01 — Plain Text / CSV

> "Just give us a CSV."
> — Every finance team, everywhere, always

## The Scene

FoodDash processes a million messages per second across twenty microservices. Orders flow from mobile apps through an API gateway, to a kitchen service, to driver dispatch, and eventually to the accounting pipeline. The data is rich: an Order contains a Customer, a list of OrderItems, each wrapping a MenuItem with allergens, thumbnails, and pricing. In Chapter 00 we established the domain models and the problem space. Now the finance team needs data.

It is the end of Q3. The finance team in New York needs a quarterly reconciliation export. They want every order from the past three months — order ID, customer, items, totals — dumped into something they can open in Excel. The request comes in a Slack message at 4:47 PM on a Friday:

> "Can you just give us a CSV? We need it by Monday."

The engineer on call — let's call her Priya — writes a quick exporter. She flattens each Order into rows (one per OrderItem, with order-level fields repeated), writes a header, and ships a `.csv` file to the shared drive. The finance team opens it in Excel on Monday morning. It works.

For about six hours.

At 2 PM, a Slack thread lights up. The finance team in Tokyo — yes, the company expanded — opened the same file in Excel on a Japanese-locale Windows machine. Excel guessed Shift-JIS encoding. The restaurant name "Borgér Palace" turned into `BÃ¶rgÃ©r Palace` — mojibake. The emoji burger vanished entirely.

By 3 PM, another report: an order from a restaurant whose menu item description reads "Two 4oz patties, American cheese, pickles, onion, secret sauce" — that description has five commas in it. The naive split in the downstream ETL pipeline parsed it as ten fields instead of five. The pipeline crashed.

By 4 PM, the finance analyst asks: "How do I see which items were in order #12345?" She discovers that the nesting is gone. Each item is its own row. The order-level fields (customer name, delivery address, payment method) are duplicated on every row. To reconstruct the original order, she would have to group rows by `order_id` — a VLOOKUP nightmare.

By end of day, the engineer has learned four hard lessons about CSV, all of which we will walk through in this chapter.


## How It Works: The CSV Format

CSV — Comma-Separated Values — is one of the oldest data interchange formats in computing. It predates JSON by decades, XML by years, and even the personal computer itself. IBM mainframes used comma-delimited files in the 1960s.

The idea is simple: represent tabular data as text, with fields separated by a delimiter (usually a comma) and records separated by newlines.

```
order_id,customer_name,item_name,price_cents
ord00001,Alice,Burger,1299
ord00002,Bob,Pizza,1599
```

That is a valid CSV file. Three columns, two data rows, one header row. Any programming language can parse it with `line.split(",")`. Any spreadsheet can open it. It is the lowest common denominator of data interchange.

### RFC 4180: The "Standard"

In 2005, RFC 4180 attempted to standardize CSV. The key rules:

1. **Fields are separated by commas.** (Or tabs, or pipes — but the RFC says commas.)

2. **Records are separated by CRLF** (`\r\n`). In practice, most implementations accept bare `\n` as well.

3. **The last record may or may not have a trailing newline.**

4. **An optional header row** may appear as the first line, with the same format as data rows.

5. **Quoting rules:**
   - If a field contains a comma, a double-quote, or a newline, the entire field must be enclosed in double-quotes.
   - A double-quote inside a quoted field is escaped by doubling it: `""`.

```
name,description
"Smash Burger","Two 4oz patties, American cheese"
"The ""Ultimate"" Burger","Our best seller"
```

6. **No encoding requirement.** RFC 4180 says nothing about character encoding. The file is just bytes. This is the root cause of the mojibake problem.

7. **No type information.** Every field is a string. The number `42`, the string `"42"`, the float `42.0`, and the boolean `True` are all indistinguishable in CSV.

### What RFC 4180 Does NOT Specify

- Character encoding (UTF-8? Latin-1? Shift-JIS?)
- How to represent null/missing values (empty string? `NULL`? `\N`?)
- How to represent nested data
- How to represent binary data
- How to represent arrays or maps
- Data types for columns
- A schema language


## From Scratch: Building a CSV Encoder

The file `csv_from_scratch.py` implements a complete CSV encoder and decoder without using Python's `csv` module. This is intentional — by building it ourselves, we see exactly where the complexity hides.

### The Quoting Algorithm

The encoder's core function is `csv_encode_row`. For each field, it decides whether quoting is needed:

```python
def csv_encode_row(fields: list[str]) -> str:
    encoded_fields = []
    for f in fields:
        needs_quoting = "," in f or '"' in f or "\n" in f or "\r" in f
        if needs_quoting:
            escaped = f.replace('"', '""')
            encoded_fields.append(f'"{escaped}"')
        else:
            encoded_fields.append(f)
    return ",".join(encoded_fields)
```

The logic:
1. Scan each field for dangerous characters: `,`, `"`, `\n`, `\r`.
2. If any are present, wrap the entire field in double-quotes and double any internal quotes.
3. Otherwise, emit the field as-is.

This is simple — about ten lines of code. But notice: the encoder must inspect every character of every field. There is no way to skip this scan. For a field that is 1,000 characters long and contains no special characters, we still scan all 1,000 characters just to confirm it is safe.

### The Parsing State Machine

Decoding is harder. The function `csv_decode_row` implements a state machine with four states:

- **FIELD_START**: We are at the beginning of a new field. If we see `"`, enter quoted mode. If we see `,`, emit an empty field. Otherwise, start accumulating an unquoted field.

- **IN_UNQUOTED**: We are inside an unquoted field. Accumulate characters until we hit `,` (field boundary) or end of input.

- **IN_QUOTED**: We are inside a quoted field. Accumulate everything until we see `"`. A `"` might be the end of the field, or it might be the first half of an escaped `""`.

- **AFTER_QUOTE**: We just saw `"` inside a quoted field. If the next character is `"`, it is an escaped quote — emit one `"` and go back to IN_QUOTED. If it is `,`, the field is over. If it is anything else, we have malformed CSV (our implementation is lenient and continues).

This is a classic finite automaton. Every character of input is examined exactly once, giving O(n) performance. There is no backtracking.

### The Flattening Problem

The hardest part of `csv_from_scratch.py` is not the encoding — it is the flattening. A FoodDash Order has this structure:

```
Order
  ├── customer: Customer
  │     ├── id, name, email, phone, address
  │     └── location: GeoPoint (lat, lng)
  ├── items: list[OrderItem]
  │     ├── menu_item: MenuItem
  │     │     ├── id, name, price_cents, description, category
  │     │     ├── is_vegetarian: bool
  │     │     ├── allergens: list[str]
  │     │     └── thumbnail_png: bytes
  │     ├── quantity: int
  │     └── special_instructions: str
  ├── metadata: dict[str, str]
  └── ... (status, payment, timestamps, etc.)
```

CSV is flat. One row = one record. How do you represent a tree in a table?

**Strategy: One row per OrderItem, with order-level fields repeated.**

This is the standard approach. An order with 3 items becomes 3 rows. Each row carries the full order ID, customer name, status, etc. — plus one item's details.

What gets lost:
- **Allergens list**: Variable-length. We could try `"gluten|dairy|nuts"` but that is a format-within-a-format.
- **Binary data (thumbnail_png)**: CSV is text. Binary data requires Base64 encoding, adding 33% overhead and losing the ability to visually inspect the field.
- **Metadata dict**: Variable keys. We would need to know all possible keys in advance to create columns.
- **Nested GeoPoint**: We could flatten to `customer_lat` and `customer_lng`, but this is a manual process for every nested object.
- **The structure itself**: Given the flat rows, reconstructing "which items belong to order X" requires grouping by `order_id`. This is implicit — nothing in the CSV format says "these three rows are one order."


## The Pain Points

The file `pain_points.py` demonstrates five concrete failure modes. Let's walk through each one.

### Pain Point 1: Delimiter Collision

A menu item's description reads:

```
Two 4oz patties, American cheese, pickles, onion, secret sauce
```

That string contains five commas. If a naive parser does `line.split(",")`, it sees:

```python
["Two 4oz patties", " American cheese", " pickles", " onion", " secret sauce"]
```

A field that should be one value is now five. The field count per row is wrong. Every downstream column is shifted. The pipeline crashes — or worse, silently assigns the wrong values to the wrong columns.

The fix is RFC 4180 quoting: wrap the field in double-quotes. But this means every encoder and decoder must implement the quoting protocol. "Just split on commas" — the thing that made CSV appealing — no longer works.

At the byte level, the comma character is `0x2C`. It serves double duty: as a delimiter *and* as a valid data character. This is called an **in-band delimiter** — the separator is drawn from the same alphabet as the data. Every in-band delimiter scheme eventually collides with real data.

### Pain Point 2: Encoding Mismatch

CSV files have no encoding declaration. The bytes `0xC3 0xB6` are:
- `ö` in UTF-8 (the two-byte encoding of U+00F6)
- `Ã` followed by `¶` in Latin-1 (each byte decoded independently)
- Something completely different in Shift-JIS

When Priya writes the CSV in UTF-8 and the Tokyo finance team opens it in Excel with Shift-JIS as the default encoding, every non-ASCII character becomes garbage. The restaurant name "Borgér Palace" turns into an unreadable mess. The emoji burger (4 bytes in UTF-8: `0xF0 0x9F 0x8D 0x94`) becomes four separate garbage characters.

There is no fix within CSV itself. You can add a UTF-8 BOM (`0xEF 0xBB 0xBF`) at the start of the file — Excel recognizes this and switches to UTF-8. But the BOM is not part of RFC 4180, not all readers respect it, and it breaks Unix tools that don't expect three magic bytes before the header row.

The root cause: CSV was designed in an era when ASCII was the only encoding that mattered. It has no metadata layer to declare its encoding. Every reader must guess.

### Pain Point 3: No Nesting

A FoodDash Order contains items. Each item contains a menu item. Each menu item has allergens (a list) and a thumbnail (binary). This is a tree with three levels of nesting.

CSV represents one level: rows and columns. Flattening a tree into a table requires:
1. Choosing which level becomes the "primary row" (OrderItem, in our case).
2. Repeating parent-level fields on every row (order ID, customer name, etc.).
3. Dropping variable-length children (allergens) or encoding them as delimited strings.
4. Dropping binary fields entirely.

The result: a typical FoodDash order with 3 items becomes 3 rows, each with 25 columns. Of those 25 columns, 17 are order-level fields that are identical across all 3 rows. That is 34 redundant cells — 68% waste.

Worse, the reader cannot know from the CSV alone that these 3 rows form one order. They must be grouped by `order_id`. If the file is sorted by item name instead of order ID, the grouping is lost.

### Pain Point 4: Type Ambiguity

Consider these Python values:

| Value | Type | CSV representation |
|-------|------|--------------------|
| `42` | int | `42` |
| `42.0` | float | `42.0` |
| `"42"` | str | `42` |
| `True` | bool | `True` |
| `"True"` | str | `True` |
| `None` | NoneType | `` (empty) |
| `""` | str | `` (empty) |

The integer `42` and the string `"42"` produce the same CSV text. The boolean `True` and the string `"True"` are identical. `None` and empty string are both empty. A CSV reader cannot distinguish any of these pairs.

In practice, this means every CSV consumer must hardcode type coercions: "column 3 is an integer, column 4 is a float, column 7 is a boolean." This is a schema — but it lives in the consumer's code, not in the data. When the producer adds a column, the consumer's hardcoded indices break silently.

### Pain Point 5: No Schema / Schema Evolution

CSV has no schema. The header row (when present) gives column names, but:
- Headers are optional.
- Headers carry no type information.
- Column order is the only structural contract.

If the producer adds a new column — say, `customer_email` between `customer_name` and `item_name` — every consumer that reads by column index breaks. The consumer that expected column 2 to be `item_name` now gets `customer_email`.

Even consumers that read by header name can break: if the new column name collides with an existing one, or if the consumer does not handle unknown columns gracefully.

There is no versioning mechanism. There is no way to say "this file uses schema v2." The producer and consumer must coordinate out-of-band — via documentation, Slack messages, or silent prayer.


## Systems Constraints

### Encoding Speed

CSV encoding is fast — possibly the fastest text-based format to encode. The algorithm is:
1. For each field, check if quoting is needed (scan for `,`, `"`, `\n`).
2. If yes, wrap in quotes and double any internal quotes.
3. Join fields with commas, join rows with newlines.

This is O(n) in the total size of the data, with very small constants. There is no tree traversal, no key encoding, no type tagging. Just string concatenation.

For a typical FoodDash order (3 items, 25 columns per row), encoding takes single-digit microseconds on modern hardware.

### Decoding Speed

CSV decoding is also O(n) — the state machine processes each character exactly once. However, it is slower than encoding because:
1. State transitions have branch mispredictions.
2. Every field requires allocation of a new string.
3. The parser cannot skip fields — it must process every character even if the consumer only needs column 3.

There is no random access. To read the last field of the last row, you must scan the entire file. Binary formats like Avro or Parquet provide offset tables for O(1) field access; CSV has no such mechanism.

### Wire Size

CSV is moderately compact for text:
- No field names in data rows (unlike JSON, which repeats keys on every object).
- No structural delimiters beyond commas and newlines (JSON has `{`, `}`, `[`, `]`, `:`).
- Numbers are stored as text (the integer `1299` takes 4 bytes in CSV, 2 bytes as a 16-bit binary integer).

For the typical FoodDash order, the CSV encoding is roughly 800-1200 bytes depending on how many fields are included. This is comparable to JSON for small payloads, but CSV scales worse because it cannot represent nested data without duplication.

### Memory

CSV can be streamed line by line. A producer can emit one row at a time without buffering the entire dataset. A consumer can process one row at a time, discarding it after processing. This makes CSV excellent for large datasets that do not fit in memory.

This is a genuine advantage over JSON (which requires parsing the entire document to handle nesting) and over most binary formats (which require reading headers or offset tables).

### Schema

None. The column order is the implicit schema. The header row, when present, provides names but not types. There is no way to declare "column 3 is an integer" or "this field is optional" or "this file uses version 2 of the schema."

### Benchmark Results

Run the chapter to see live benchmarks on your machine:

```
uv run python -m chapters.ch01_plain_text_csv
```

The benchmarks compare from-scratch CSV encoding against Python's stdlib `csv` module. Both are O(n) and produce identical output; the stdlib version is typically faster because it is implemented in C.


## Production Depth

### Where CSV is Still King

CSV has survived for sixty years because it fills a niche that no other format covers as well:

**Spreadsheet interchange.** Every spreadsheet application on earth — Excel, Google Sheets, LibreOffice Calc, Numbers — can open a CSV file. No plugins, no configuration, no schema files. Double-click the file and it opens. For the finance team that needs to pivot on order totals, CSV is the format.

**Database import/export.** PostgreSQL's `COPY` command reads and writes CSV. MySQL's `LOAD DATA INFILE` reads CSV. Every database has a CSV import path. For bulk data loading, CSV (despite its flaws) is the universal language.

**Log files.** Structured logs in CSV can be tailed, grepped, and piped through Unix tools. `cut -d, -f3` extracts the third column. `sort -t, -k2` sorts by the second column. No parser needed.

**Data science pipelines.** Pandas `read_csv()` is often the first function a data scientist calls. CSV is the default download format for Kaggle datasets, government open data, and academic research.

### Where CSV Fails

**Nested data.** Any data with more than one level of nesting requires flattening, which loses structure and introduces duplication. FoodDash orders are a textbook example.

**Binary data.** Images, audio, serialized objects — none of these can be represented in CSV without Base64 encoding, which adds 33% overhead and makes the field unreadable.

**Real-time streaming.** CSV has no message boundaries. A stream of CSV rows has no way to signal "this is a complete message" versus "this row is part of a larger batch." Framing must be added externally.

**Schema evolution.** Adding, removing, or reordering columns breaks every consumer that reads by index. Even consumers that read by header name must handle unknown columns.

**Internationalization.** Without a defined encoding, CSV files are a minefield for non-ASCII text. The UTF-8 BOM helps but is not universal.

### TSV: Tab-Separated Values

TSV replaces the comma with a tab character (`0x09`). This avoids the "comma in data" problem — tabs are rare in natural text. But tabs are not unheard of (copy-paste from a web page can include tabs), and the quoting rules are less standardized. TSV trades one delimiter collision for a less likely one.

IANA registered the `text/tab-separated-values` media type in 1993 — twelve years before RFC 4180 standardized CSV. TSV forbids tabs and newlines in field values entirely (no quoting mechanism), which makes it simpler to parse but less expressive.

### CSV in Data Pipelines

Apache Spark, Pandas, DuckDB, and Polars all support CSV. It is always the slowest option:

- **Spark:** CSV reading is 10-100x slower than Parquet for the same data, because CSV requires full parsing (no column pruning, no predicate pushdown, no statistics).
- **Pandas:** `read_csv()` is heavily optimized with a C parser, but it still cannot match `read_parquet()` for large datasets.
- **DuckDB:** Can read CSV directly, but its internal columnar format is orders of magnitude faster for analytics.

CSV is the "import format" — you read it once, convert it to something better, and never touch the CSV again.


## Trade-offs Table

| Property | CSV |
|---|---|
| Human-readable | Yes -- open in any text editor or spreadsheet |
| Nesting | No -- flat rows and columns only |
| Types | No -- everything is a string |
| Schema | No -- implicit column order, optional header |
| Binary data | No -- text only (Base64 possible but adds overhead) |
| Encoding | Undefined -- UTF-8, Latin-1, Shift-JIS all valid |
| Encode speed | Fast -- O(n) string concatenation |
| Decode speed | Moderate -- O(n) state machine, no random access |
| Wire size | Moderate -- no field names, but text encoding of numbers |
| Streaming | Yes -- line-by-line processing, low memory |
| Schema evolution | No -- adding a column breaks index-based readers |
| Standardization | Partial -- RFC 4180 exists but compliance varies |
| Tooling | Excellent -- every language, database, and spreadsheet |
| Self-describing | No -- the data does not describe its own structure |


## The Bridge

CSV gave us the simplest possible wire format — text fields separated by commas. Any language can read it. Any spreadsheet can open it. The finance team got their export.

But we hit four walls:

1. **No nesting.** FoodDash Orders have items inside them, each with a menu item, each with allergens. Flattening this into rows loses structure, duplicates data, and drops variable-length fields entirely. The finance analyst cannot reconstruct the original order from the flat CSV without external logic.

2. **No types.** Is `42` a number or a string? Is `True` a boolean or a string? Is an empty cell null or an empty string? CSV does not know. Every consumer hardcodes type coercions, and every coercion is a potential bug.

3. **No defined encoding.** The same bytes can be UTF-8, Latin-1, or Shift-JIS. The CSV file contains no metadata to declare its encoding. The Tokyo team gets mojibake. The engineer adds a BOM. Half the Unix tools break on the BOM.

4. **Delimiter hell.** The comma is both a delimiter and a valid data character. Quoting rules fix this, but they add complexity — and naive parsers (including many production ETL scripts) do not implement quoting correctly.

We need a format that solves all four problems. One that supports nesting — objects inside objects, arrays inside objects. One that distinguishes types — numbers, strings, booleans, null. One that mandates UTF-8 — no encoding guessing. And one that does not use in-band delimiters — no comma-versus-data ambiguity.

That format already exists. Every web API speaks it. Every browser can parse it natively. It was designed for exactly the kind of structured, nested, typed data that CSV cannot handle.

It is JSON. See Chapter 02.


## Running This Chapter

```bash
# Run all demos and benchmarks
uv run python -m chapters.ch01_plain_text_csv

# Run individual modules
uv run python -m chapters.ch01_plain_text_csv.csv_from_scratch
uv run python -m chapters.ch01_plain_text_csv.csv_stdlib
uv run python -m chapters.ch01_plain_text_csv.pain_points
```

Open `visual.html` in a browser to see the interactive visualization of CSV encoding, hex dumps, and pain point demonstrations.
