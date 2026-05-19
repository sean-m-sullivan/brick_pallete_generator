#!/usr/bin/env python3

import json
import os
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.dom import minidom

import requests
import yaml
from curl_cffi import requests as curl_requests
from dotenv import load_dotenv
from requests_oauthlib import OAuth1

load_dotenv()

# ------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------

DEBUG = False

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

CACHE_DIR = Path("cache")
CACHE_DIR.mkdir(exist_ok=True)

DATA_DIR = Path("data")

STUDIO_PALETTE_DIR = DATA_DIR / "studio_pallettes"

CANONICAL_DB_FILE = CACHE_DIR / "canonical_mapping.json"

FAILED_CACHE_FILE = CACHE_DIR / "failed_mappings.json"

OVERRIDE_FILE = CACHE_DIR / "manual_overrides.yaml"

BL_TO_LEGO_CACHE_FILE = CACHE_DIR / "bricklink_to_lego.json"

STUDIO_REFERENCE_FILE = CACHE_DIR / "studio_palette_reference.json"

SNAPSHOT_FILE = CACHE_DIR / "pab_snapshot.json"

COLOR_DATABASE_FILE = DATA_DIR / "color_database.json"

FORCE_REFRESH = False

ITEM_TYPE_MAP = {
    "PART": "P",
    "MINIFIG": "M",
    "SET": "S",
}

# ------------------------------------------------------------
# AUTH
# ------------------------------------------------------------

auth = OAuth1(
    os.environ["BRICKLINK_CONSUMER_KEY"],
    os.environ["BRICKLINK_CONSUMER_SECRET"],
    os.environ["BRICKLINK_TOKEN"],
    os.environ["BRICKLINK_TOKEN_SECRET"],
)

# ------------------------------------------------------------
# GRAPHQL
# ------------------------------------------------------------

TEST_QUERY = """
query PickABrickQuery($input: ElementQueryInput!, $sku: String) {
  searchElements(input: $input) {
    results {
      ...ElementLeaf
      __typename
    }
    total
    count
    __typename
  }
}

fragment ElementLeaf on SearchResultElement {
  id
  designId
  collapseDesignId
  name
  imageUrl
  maxOrderQuantity
  deliveryChannel
  colorHex
  contrastColorHex

  price {
    centAmount
    formattedAmount
    currencyCode
    formattedValue
    __typename
  }

  quantityInSet(sku: $sku)

  siblings {
    id
    colorHex
    contrastColorHex
    availability

    price {
      formattedAmount
      formattedValue
      __typename
    }

    __typename
  }

  availability

  __typename
}
"""

stats = {
    "bricklink_success": 0,
    "manual_override": 0,
    "rebrickable_fallback": 0,
    "unresolved": 0,
    "temporary_failure": 0,
    "canonical_cache": 0,
    "incremental_skipped": 0,
    "incremental_updated": 0,
    "incremental_removed": 0,
}


# ------------------------------------------------------------
# HELPERS
# ------------------------------------------------------------
def load_yaml_file(path, default):

    if path.exists():

        try:

            with open(
                path,
                encoding="utf-8",
            ) as f:

                data = yaml.safe_load(f)

                if data is None:
                    return default

                return data

        except Exception as e:

            print(f"Failed loading {path}: {e}")

    return default


def save_yaml_file(path, data):

    with open(
        path,
        "w",
        encoding="utf-8",
    ) as f:

        yaml.safe_dump(
            data,
            f,
            sort_keys=True,
            allow_unicode=True,
            default_flow_style=False,
        )


def load_json_file(path, default):

    if path.exists():

        try:

            with open(
                path,
                encoding="utf-8",
            ) as f:

                return json.load(f)

        except Exception as e:

            print(f"Failed loading {path}: {e}")

    return default


def save_json_file(path, data):

    with open(
        path,
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            data,
            f,
            indent=2,
            sort_keys=True,
        )


# ------------------------------------------------------------
# LOAD STATE
# ------------------------------------------------------------

manual_overrides = load_yaml_file(
    OVERRIDE_FILE,
    {},
)

failed_cache = load_json_file(
    FAILED_CACHE_FILE,
    {},
)

canonical_db = load_json_file(
    CANONICAL_DB_FILE,
    {},
)

print(f"Loaded canonical cache: " f"{len(canonical_db)} entries")

color_database = load_json_file(
    COLOR_DATABASE_FILE,
    {},
)

print(f"Loaded color database: " f"{len(color_database.get('bricklink', {}))} " f"BrickLink colors")

studio_reference = {}

# ------------------------------------------------------------
# Channel Priority for parts
# ------------------------------------------------------------


def channel_priority(channel):

    priorities = {
        "pab": 3,
        "bap": 2,
        "out_of_stock": 1,
        "unknown": 0,
    }

    return priorities.get(
        str(channel).lower(),
        0,
    )


# ------------------------------------------------------------
# STUDIO PALETTE REFERENCE PARSER
# ------------------------------------------------------------


def parse_studio_palette_reference():

    global studio_reference

    reference = {}

    if not STUDIO_PALETTE_DIR.exists():

        print("No studio palette dir")

        return {}

    for palette_file in sorted(STUDIO_PALETTE_DIR.iterdir()):

        if not palette_file.is_file():
            continue

        palette_name = palette_file.name

        print(f"Parsing studio palette {palette_name}")

        current_part = None

        with open(
            palette_file,
            encoding="utf-8",
            errors="ignore",
        ) as f:

            for raw_line in f:

                line = raw_line.strip()

                if not line:
                    continue

                if line.startswith("0 "):

                    current_part = line[2:]

                    if current_part not in reference:

                        reference[current_part] = {
                            "seen_in": [],
                        }

                    if palette_name not in reference[current_part]["seen_in"]:

                        reference[current_part]["seen_in"].append(palette_name)

    studio_reference = reference

    save_json_file(
        STUDIO_REFERENCE_FILE,
        studio_reference,
    )

    print(f"Loaded {len(reference)} studio refs")


# ------------------------------------------------------------
# CHANNEL
# ------------------------------------------------------------


def get_channel(item):

    channel = item.get("deliveryChannel")

    if channel:
        return channel

    if item.get("availability") == "OUT_OF_STOCK":

        return "out_of_stock"

    return "unknown"


# ------------------------------------------------------------
# LEGO FETCH
# ------------------------------------------------------------


def fetch_lego_inventory(
    per_page=400,
):

    url = "https://www.lego.com/api/graphql/PickABrickQuery"

    headers = {
        "Referer": ("https://www.lego.com/" "en-us/pick-and-build/" "pick-a-brick"),
        "User-Agent": "Mozilla/5.0",
    }

    all_results = []

    page = 1

    while True:

        print(f"Fetching page {page}")

        json_body = {
            "operationName": "PickABrickQuery",
            "variables": {
                "input": {
                    "page": page,
                    "perPage": per_page,
                    "sort": {
                        "key": "RELEVANCE",
                        "direction": "DESC",
                    },
                    "query": "",
                    "fetchSiblings": True,
                    "availability": [
                        "AVAILABLE",
                        "OUT_OF_STOCK",
                    ],
                },
            },
            "query": TEST_QUERY,
        }

        response = curl_requests.post(
            url,
            json=json_body,
            headers=headers,
            impersonate="chrome124",
            timeout=60,
        )

        if response.status_code != 200:

            print(response.text)

            response.raise_for_status()

        data = response.json()

        search = data["data"]["searchElements"]

        results = search["results"]

        if not results:
            break

        expanded_results = []

        for item in results:

            #
            # Primary item
            #

            expanded_results.append(item)

            #
            # Sibling color variants
            #

            for sibling in item.get("siblings", []):

                sibling_copy = dict(item)

                #
                # Override with sibling-specific fields
                #

                sibling_copy.update(sibling)

                #
                # Preserve parent metadata
                #

                sibling_copy["designId"] = item.get("designId")

                sibling_copy["name"] = item.get("name")

                sibling_copy["deliveryChannel"] = item.get("deliveryChannel")

                sibling_copy["imageUrl"] = item.get("imageUrl")

                sibling_copy["maxOrderQuantity"] = item.get("maxOrderQuantity")

                expanded_results.append(sibling_copy)

        all_results.extend(expanded_results)

        if len(results) < per_page:
            break

        page += 1

        time.sleep(0.10)

    #
    # Deduplicate by LEGO element ID
    #
    # Prefer:
    # PAB > BAP > OUT_OF_STOCK
    #

    deduped = {}

    for item in all_results:

        element_id = str(item.get("id"))

        existing = deduped.get(element_id)

        if not existing:

            deduped[element_id] = item

            continue

        existing_priority = channel_priority(get_channel(existing))

        new_priority = channel_priority(get_channel(item))

        if new_priority > existing_priority:

            deduped[element_id] = item

    all_results = list(deduped.values())

    snapshot_data = {
        "timestamp": time.time(),
        "results": all_results,
    }

    save_json_file(
        SNAPSHOT_FILE,
        snapshot_data,
    )

    return all_results


# ------------------------------------------------------------
# BRICKLINK LOOKUP
# ------------------------------------------------------------


def lookup_bricklink_mapping(
    element_id,
):

    url = "https://api.bricklink.com/api/store/v1/" f"item_mapping/{element_id}"

    max_attempts = 3

    for attempt in range(max_attempts):

        try:

            #
            # Small pacing delay
            #

            time.sleep(0.10)

            response = requests.get(
                url,
                auth=auth,
                timeout=30,
            )

            response.raise_for_status()

            data = response.json()

            if data["meta"]["code"] != 200 or not data["data"]:

                return None

            mapping = data["data"][0]
            stats["bricklink_success"] += 1
            return {
                "bl_part_no": (mapping["item"]["no"]),
                "bl_color_id": (mapping["color_id"]),
                "bl_item_type": (mapping["item"]["type"]),
                "source": "bricklink",
            }

        except requests.exceptions.RequestException as e:

            error_message = str(e)

            print(
                f"BrickLink network failure " f"(attempt {attempt + 1}/" f"{max_attempts}):",
                error_message,
            )

            #
            # Final retry exhausted
            #

            if attempt == max_attempts - 1:

                return {
                    "_temporary_failure": True,
                    "_reason": error_message,
                }

            #
            # Exponential backoff
            #

            time.sleep(2 * (attempt + 1))

        except Exception as e:

            print(
                "BrickLink lookup failed:",
                e,
            )

            return None


# ------------------------------------------------------------
# Color Resolver
# ------------------------------------------------------------


def resolve_studio_color(
    bricklink_color_id,
):

    bricklink_colors = color_database.get(
        "bricklink",
        {},
    )

    color_entry = bricklink_colors.get(str(bricklink_color_id))

    if not color_entry:

        return bricklink_color_id

    ldraw = color_entry.get("ldraw")

    if not ldraw:

        return bricklink_color_id

    return ldraw["id"]


# ------------------------------------------------------------
# REBRICKABLE FALLBACK
# ------------------------------------------------------------


def lookup_rebrickable_fallback(
    element_id,
):

    api_key = os.getenv("REBRICKABLE_API_KEY")

    if not api_key:
        return None

    url = "https://rebrickable.com/api/v3/lego/" f"elements/{element_id}/"

    headers = {
        "Authorization": (f"key {api_key}"),
        "User-Agent": ("brick-palette-generator/1.0"),
    }

    try:

        response = requests.get(
            url,
            headers=headers,
            timeout=30,
        )

        if response.status_code != 200:
            return None

        data = response.json()

        part = data.get(
            "part",
            {},
        )

        color = data.get(
            "color",
            {},
        )

        bricklink_ids = part.get(
            "external_ids",
            {},
        ).get(
            "BrickLink",
            [],
        )

        if not bricklink_ids:
            return None

        bl_color_ids = (
            color.get(
                "external_ids",
                {},
            )
            .get(
                "BrickLink",
                {},
            )
            .get(
                "ext_ids",
                [],
            )
        )

        if not bl_color_ids:
            return None

        return {
            "bl_part_no": (bricklink_ids[0]),
            "bl_color_id": (bl_color_ids[0]),
            "bl_item_type": "PART",
            "source": ("rebrickable_fallback"),
        }

    except Exception as e:

        print(
            "Rebrickable fallback failed:",
            e,
        )

        return None


# ------------------------------------------------------------
# STUDIO PART FILE
# ------------------------------------------------------------


def build_studio_part_file(
    bricklink_part,
):

    if "pb" in bricklink_part or "pr" in bricklink_part:

        return f"bl_{bricklink_part}.dat"

    return f"{bricklink_part}.dat"


# ------------------------------------------------------------
# RESOLVE MAPPING
# ------------------------------------------------------------

temporary_failures = []

lookup_progress = {
    "total": 0,
    "processed": 0,
    "next_report": 5,
}


def resolve_mapping(
    element_id,
):

    element_id = str(element_id)

    #
    # Manual override
    #

    if element_id in manual_overrides:
        stats["manual_override"] += 1
        return manual_overrides[element_id]

    #
    # Previously failed permanently
    #

    if element_id in failed_cache and not FORCE_REFRESH:

        cache_age = time.time() - failed_cache[element_id].get(
            "timestamp",
            0,
        )

        #
        # Retry unresolved entries
        # after 7 days
        #

        if cache_age < 604800:

            return None

    #
    # BrickLink lookup
    #

    mapping = lookup_bricklink_mapping(element_id)

    #
    # Temporary network/API failure
    #
    # Do NOT permanently cache
    #

    if mapping and mapping.get("_temporary_failure"):
        stats["temporary_failure"] += 1
        print(f"TEMPORARY FAILURE: " f"{element_id}")

        print(mapping.get("_reason"))

        temporary_failures.append(
            {
                "element_id": element_id,
                "reason": mapping.get("_reason"),
            }
        )

        return None

    #
    # Rebrickable fallback
    #

    if not mapping:

        mapping = lookup_rebrickable_fallback(element_id)

        if mapping:

            print(f"REBRICKABLE FALLBACK: " f"{element_id} " f"-> " f"{mapping['bl_part_no']}")
            stats["rebrickable_fallback"] += 1
            manual_overrides[element_id] = mapping

            save_yaml_file(
                OVERRIDE_FILE,
                manual_overrides,
            )

    #
    # Permanent failure
    #

    if not mapping:
        stats["unresolved"] += 1
        print(f"UNRESOLVED: " f"{element_id}")

        failed_cache[element_id] = {
            "status": "unresolved",
            "timestamp": time.time(),
        }

        save_json_file(
            FAILED_CACHE_FILE,
            failed_cache,
        )

        return None

    return mapping


# ------------------------------------------------------------
# BUILD CANONICAL DB
# ------------------------------------------------------------


def build_canonical_db(results):

    global canonical_db

    canonical = dict(canonical_db)

    lookup_progress["total"] = len(results)
    lookup_progress["processed"] = 0
    lookup_progress["next_report"] = 5

    for item in results:

        element_id = str(item["id"])

        lookup_progress["processed"] += 1

        processed = lookup_progress["processed"]

        total = lookup_progress["total"]

        percent = int((processed / total) * 100)

        if percent >= lookup_progress["next_report"]:

            print(f"BrickLink mapping progress: " f"{percent}% " f"({processed}/{total})")

            lookup_progress["next_report"] += 5

        existing = canonical.get(element_id)

        current_channel = get_channel(item)

        current_price = item.get("price", {}).get(
            "centAmount",
            0,
        )

        #
        # Incremental skip check
        #

        if existing:

            existing_price = existing.get(
                "price",
                {},
            ).get(
                "cent_amount",
                0,
            )

            existing_channel = existing.get("channel")

            if existing_price == current_price and existing_channel == current_channel and not FORCE_REFRESH:

                stats["incremental_skipped"] += 1
                stats["canonical_cache"] += 1

                continue

        #
        # Resolve mapping
        #

        mapping = resolve_mapping(element_id)

        if not mapping:
            continue

        bricklink_part = mapping["bl_part_no"]

        studio_part = build_studio_part_file(bricklink_part)

        studio_color = resolve_studio_color(mapping["bl_color_id"])

        canonical[element_id] = {
            "lego": {
                "element_id": element_id,
                "design_id": item.get("designId"),
                "name": item.get("name"),
            },
            "bricklink": {
                "part_no": bricklink_part,
                "color_id": mapping["bl_color_id"],
                "item_type": mapping["bl_item_type"],
            },
            "studio": {
                "part_file": studio_part,
                "color_id": studio_color,
                "known_studio_part": (studio_part in studio_reference),
            },
            "channel": get_channel(item),
            "price": {
                "cent_amount": (
                    item.get(
                        "price",
                        {},
                    ).get(
                        "centAmount",
                        0,
                    )
                ),
                "formatted": (
                    item.get(
                        "price",
                        {},
                    ).get(
                        "formattedAmount",
                        "$0.00",
                    )
                ),
            },
            "source": mapping["source"],
        }

        stats["incremental_updated"] += 1

    #
    # Remove stale entries
    #

    current_ids = {str(item["id"]) for item in results}

    stale_ids = [element_id for element_id in canonical if element_id not in current_ids]

    for stale_id in stale_ids:

        del canonical[stale_id]

    stats["incremental_removed"] += len(stale_ids)

    print(f"Removed stale entries: " f"{len(stale_ids)}")

    canonical_db = canonical

    save_json_file(
        CANONICAL_DB_FILE,
        canonical_db,
    )

    print(f"Saved canonical DB: " f"{len(canonical_db)} entries")


# ------------------------------------------------------------
# XML EXPORT
# ------------------------------------------------------------


def build_xml(entries):

    inventory = ET.Element("INVENTORY")

    for entry in entries:

        item = ET.SubElement(
            inventory,
            "ITEM",
        )

        ET.SubElement(
            item,
            "ITEMTYPE",
        ).text = ITEM_TYPE_MAP.get(
            entry["bricklink"]["item_type"],
            "P",
        )

        ET.SubElement(
            item,
            "ITEMID",
        ).text = entry[
            "bricklink"
        ]["part_no"]

        ET.SubElement(
            item,
            "COLOR",
        ).text = str(entry["bricklink"]["color_id"])

        ET.SubElement(
            item,
            "MAXPRICE",
        ).text = f"{entry['price']['cent_amount'] / 100:.4f}"

        ET.SubElement(
            item,
            "MINQTY",
        ).text = "1"

        ET.SubElement(
            item,
            "CONDITION",
        ).text = "X"

        ET.SubElement(
            item,
            "REMARKS",
        ).text = (
            f"{entry['lego']['name']} " f"(LEGO Element " f"{entry['lego']['element_id']})"
        )

        ET.SubElement(
            item,
            "NOTIFY",
        ).text = "N"

    xml_bytes = ET.tostring(
        inventory,
        encoding="utf-8",
    )

    xml_str = minidom.parseString(xml_bytes).toprettyxml(indent="  ")

    return "\n".join(line for line in xml_str.splitlines() if line.strip())


# ------------------------------------------------------------
# PALETTE EXPORT
# ------------------------------------------------------------


def build_palette(entries, name):

    lines = [
        f"~+{name}",
        "14",
        "-1",
    ]

    counts = {}

    #
    # Count part/color combinations
    #

    for entry in entries:

        part_file = entry["studio"]["part_file"]

        color_id = entry["studio"]["color_id"]

        key = (
            part_file,
            color_id,
        )

        counts[key] = counts.get(key, 0) + 1

    #
    # Emit palette entries
    #

    for (
        part_file,
        color_id,
    ), quantity in counts.items():

        #
        # Find example entry
        #

        example = next(entry for entry in entries if (entry["studio"]["part_file"] == part_file and entry["studio"]["color_id"] == color_id))

        lines.append(f"0 {part_file}")

        lines.append(f"1 {example['lego']['name']}")

        lines.append(f"2 {color_id}")

        lines.append(f"4 {quantity}")

    return "\n".join(lines)


# ------------------------------------------------------------
# EXPORTS
# ------------------------------------------------------------


def export_outputs():

    channels = {
        "bestseller": [],
        "standard": [],
        "out_of_stock": [],
        "all": [],
    }

    for entry in canonical_db.values():

        channel = entry["channel"]

        channels["all"].append(entry)

        if channel == "pab":

            channels["bestseller"].append(entry)

        elif channel == "bap":

            channels["standard"].append(entry)

        elif channel == "out_of_stock":

            channels["out_of_stock"].append(entry)

    # XML

    for (
        name,
        entries,
    ) in channels.items():

        xml_output = build_xml(entries)

        with open(
            OUTPUT_DIR / f"lego_inventory_{name}.xml",
            "w",
            encoding="utf-8",
        ) as f:

            f.write(xml_output)

        print(f"Saved XML {name}")

    # Studio palettes

    for (
        name,
        entries,
    ) in channels.items():

        palette_name = "Pick a Brick " + name.replace("_", " ").title()

        palette_output = build_palette(
            entries,
            palette_name,
        )

        with open(
            OUTPUT_DIR / palette_name,
            "w",
            encoding="utf-8",
        ) as f:

            f.write(palette_output)

        print(f"Saved palette " f"{palette_name}")


# ------------------------------------------------------------
# REVERSE INDEX
# ------------------------------------------------------------


def rebuild_reverse_index():

    reverse = {}

    for (
        element_id,
        entry,
    ) in canonical_db.items():

        key = f"{entry['bricklink']['part_no']}" f"|{entry['bricklink']['color_id']}" f"|{entry['bricklink']['item_type']}"

        if key not in reverse:
            reverse[key] = []

        reverse[key].append(element_id)

    save_json_file(
        BL_TO_LEGO_CACHE_FILE,
        reverse,
    )

    print(f"Saved reverse index " f"{len(reverse)}")


# ------------------------------------------------------------
# MAIN
# ------------------------------------------------------------


def main():

    parse_studio_palette_reference()

    print("Fetching LEGO inventory")

    results = fetch_lego_inventory()

    print(f"Unique LEGO items: " f"{len(results)}")

    build_canonical_db(results)

    rebuild_reverse_index()

    export_outputs()

    print(f"Temporary failures: {len(temporary_failures)}")

    for failure in temporary_failures:

        print(
            failure["element_id"],
            failure["reason"],
        )
    print()

    print("Lookup Statistics")

    for key, value in stats.items():

        print(f"{key}: {value}")

    print("DONE")


if __name__ == "__main__":
    main()
