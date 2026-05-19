# LEGO Pick a Brick Palette Generator

Generates:

- BrickLink XML wanted lists
- Studio palette files
- Canonical LEGO ↔ BrickLink ↔ Studio/LDraw mappings
- Cross-database color normalization
- Reverse lookup indexes

using:

- LEGO Pick a Brick inventory
- BrickLink item mappings
- Rebrickable fallback data
- Studio palette references

---

## Features

- Incremental canonical DB updates
- BrickLink API retry handling
- Rebrickable fallback recovery
- Studio/LDraw palette generation
- Canonical cross-database color mappings
- Reverse BrickLink → LEGO index
- Manual override support
- Failed lookup persistence

---

## Requirements

- Python 3.11+
- BrickLink API credentials
- Rebrickable API key

---

## Installation

### Clone Repository

```bash
git clone <repo>
cd brick_pallete_generator
```

---

### Create Virtual Environment

#### Linux/macOS

```bash
python -m venv venv
source venv/bin/activate
```

#### Windows PowerShell

```powershell
python -m venv venv
venv\Scripts\Activate.ps1
```

---

### Install Dependencies

```bash
pip install -r requirements.txt
```

---

## Create `.env`

Create a file named:

```text
.env
```

Example:

```env
BRICKLINK_CONSUMER_KEY=your_key
BRICKLINK_CONSUMER_SECRET=your_secret
BRICKLINK_TOKEN=your_token
BRICKLINK_TOKEN_SECRET=your_token_secret
REBRICKABLE_API_KEY=your_api_key
```

---

## API Keys

This project requires:

- BrickLink API credentials
- Rebrickable API key

---

### BrickLink API

Register your account to [get your secrets here](https://www.bricklink.com/v2/api/register_consumer.page)

[API Auth documentation](https://www.bricklink.com/v3/api.page?page=auth)

You will need:

- Consumer Key
- Consumer Secret
- Token
- Token Secret

Add them to `.env`:

```env
BRICKLINK_CONSUMER_KEY=your_key
BRICKLINK_CONSUMER_SECRET=your_secret
BRICKLINK_TOKEN=your_token
BRICKLINK_TOKEN_SECRET=your_token_secret
```

---

### Rebrickable API

[Generate an API key here](https://rebrickable.com/users/Alphonse42/settings/#api)

Add to `.env`:

```env
REBRICKABLE_API_KEY=your_api_key
```

---

### API Rate Limits

The generator includes:

- retry handling
- pacing delays
- incremental caching
- failed lookup persistence

to reduce API load and avoid rate limits.

---

### Example `.env`

```env
BRICKLINK_CONSUMER_KEY=xxxxxxxx
BRICKLINK_CONSUMER_SECRET=xxxxxxxx
BRICKLINK_TOKEN=xxxxxxxx
BRICKLINK_TOKEN_SECRET=xxxxxxxx
REBRICKABLE_API_KEY=xxxxxxxx
```

---

## Build Canonical Color Database

Build the canonical color database from Rebrickable:

```bash
python tools/build_color_database.py
```

This generates:

```text
data/color_database.json
```

The color DB includes:

- Rebrickable colors
- BrickLink colors
- LEGO colors
- LDraw colors
- aliases
- variants

---

### First Run

The initial canonical mapping build may take a significant amount of time because BrickLink mappings must be resolved and cached, and they are slowed down to ensure you are not blocked or rate limited.

Subsequent runs are incremental and much faster.

---

## Generate LEGO Pick a Brick Inventory

Run:

```bash
python generate_pab_inventory.py
```

This will:

1. Fetch LEGO Pick a Brick inventory
2. Resolve BrickLink mappings
3. Apply Rebrickable fallback recovery
4. Build/update canonical mapping DB
5. Build reverse indexes
6. Export BrickLink XML files
7. Export Studio palette files

---

## Generated Outputs

### BrickLink XML

```text
output/lego_inventory_all.xml
output/lego_inventory_bestseller.xml
output/lego_inventory_standard.xml
output/lego_inventory_out_of_stock.xml
```

---

### Studio Palettes

```text
output/Pick a Brick All
output/Pick a Brick Bestseller
output/Pick a Brick Standard
output/Pick a Brick Out Of Stock
```

---

## Canonical Databases

### Canonical Mapping DB

```text
cache/canonical_mapping.json
```

Contains:

- LEGO element metadata
- BrickLink mapping
- Studio/LDraw mapping
- pricing
- channel
- source metadata

---

### Color Database

```text
data/color_database.json
```

Contains normalized cross-database color mappings.

---

## Manual Overrides

Overrides can be added to:

```text
cache/manual_overrides.yaml
```

Example:

```yaml
6489204:
  bl_part_no: 27262
  bl_color_id: 11
  bl_item_type: PART
  source: manual_override
```

---

## Incremental Updates

The canonical DB supports incremental updates.

Entries are skipped when:

- channel unchanged
- pricing unchanged
- mapping already resolved

Use:

```python
FORCE_REFRESH = True
```

for a full rebuild.

---

## Formatting / Linting

Project uses:

- Ruff
- Black
- isort

Run:

```bash
ruff check . --fix
black .
isort .
```

---

## Recommended Workflow

### Update color DB

```bash
python tools/build_color_database.py
```

### Update LEGO inventory + outputs

```bash
python generate_pab_inventory.py
```

### Commit updated outputs

```bash
git add .
git commit -m "Update Pick a Brick inventory"
```

---

## Troubleshooting

### BrickLink 429 / Rate Limited

The script automatically retries and slows requests.

---

### Empty color database

Run:

```bash
python tools/build_color_database.py
```

before generating inventory exports.

---

### Missing mappings

Unresolved mappings are stored in:

```text
cache/failed_mappings.json
```

Manual overrides can be added to:

```text
cache/manual_overrides.yaml
```

---

## License

This project is licensed under the GNU Affero General Public License v3.0 (AGPL-3.0).

You are free to:

- use
- modify
- distribute

provided that:

- derivative works remain open source
- source code is made available
- modifications are shared under the same license

Full license text available in:

```text
LICENSE
```
