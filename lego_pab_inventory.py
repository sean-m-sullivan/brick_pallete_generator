#!/usr/bin/env python3

import csv
import json
import logging
import os
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.dom import minidom

import requests
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

# ------------------------------------------------------------
# CACHE FILES
# ------------------------------------------------------------

LEGO_TO_BL_CACHE_FILE = (
    CACHE_DIR / "lego_to_bricklink.json"
)

BL_TO_LEGO_CACHE_FILE = (
    CACHE_DIR / "bricklink_to_lego.json"
)

FAILED_CACHE_FILE = (
    CACHE_DIR / "failed_mappings.json"
)

OVERRIDE_FILE = (
    CACHE_DIR / "manual_overrides.json"
)

DUPLICATE_CACHE_FILE = (
    CACHE_DIR / "duplicate_cache.json"
)

SNAPSHOT_FILE = (
    CACHE_DIR / "bestseller_snapshot.json"
)

# ------------------------------------------------------------
# REBRICKABLE CSV FILES
# ------------------------------------------------------------

PART_CATEGORIES_CSV = (
    DATA_DIR / "part_categories.csv"
)

# ------------------------------------------------------------
# ITEM TYPE MAP
# ------------------------------------------------------------

ITEM_TYPE_MAP = {
    "PART": "P",
    "MINIFIG": "M",
    "SET": "S",
}

# ------------------------------------------------------------
# BRICKLINK AUTH
# ------------------------------------------------------------

auth = OAuth1(
    os.environ["BRICKLINK_CONSUMER_KEY"],
    os.environ["BRICKLINK_CONSUMER_SECRET"],
    os.environ["BRICKLINK_TOKEN"],
    os.environ["BRICKLINK_TOKEN_SECRET"],
)

# ------------------------------------------------------------
# GRAPHQL QUERY
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

# ------------------------------------------------------------
# JSON HELPERS
# ------------------------------------------------------------


def load_json_file(path, default):

    if path.exists():
        try:
            with open(
                path,
                encoding="utf-8",
            ) as f:
                return json.load(f)

        except Exception as e:
            print(
                f"WARNING: Failed loading {path}: {e}"
            )

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
        )

# ------------------------------------------------------------
# LOAD CACHES
# ------------------------------------------------------------

lego_to_bl_cache = load_json_file(
    LEGO_TO_BL_CACHE_FILE,
    {},
)

bl_to_lego_cache = load_json_file(
    BL_TO_LEGO_CACHE_FILE,
    {},
)

manual_overrides = load_json_file(
    OVERRIDE_FILE,
    {},
)

failed_cache = load_json_file(
    FAILED_CACHE_FILE,
    {},
)

duplicate_cache = load_json_file(
    DUPLICATE_CACHE_FILE,
    {},
)

# ------------------------------------------------------------
# CATEGORY LOOKUP
# ------------------------------------------------------------

part_categories = {}


def load_part_categories():

    if not PART_CATEGORIES_CSV.exists():

        print(
            "WARNING: Missing part_categories.csv"
        )

        return

    with open(
        PART_CATEGORIES_CSV,
        encoding="utf-8",
    ) as f:

        reader = csv.DictReader(f)

        for row in reader:

            part_categories[
                row["id"]
            ] = row["name"]

    print(
        f"Loaded {len(part_categories)} categories"
    )

# ------------------------------------------------------------
# CHANNEL HELPERS
# ------------------------------------------------------------


def get_channel(item):

    channel = item.get(
        "deliveryChannel"
    )

    if channel:
        return channel

    availability = item.get(
        "availability"
    )

    if availability == "OUT_OF_STOCK":
        return "out_of_stock"

    return "unknown"



def get_channel_filename(channel):

    mapping = {
        "pab": "bestseller",
        "bap": "standard",
        "out_of_stock": "out_of_stock",
        "unknown": "unknown",
    }

    return mapping.get(
        channel,
        channel,
    )

# ------------------------------------------------------------
# BRICKLINK LOOKUP
# ------------------------------------------------------------


def lookup_bricklink_mapping(
    element_id,
):

    url = (
        "https://api.bricklink.com/"
        f"api/store/v1/item_mapping/{element_id}"
    )

    try:

        response = requests.get(
            url,
            auth=auth,
            timeout=30,
        )

        response.raise_for_status()

        data = response.json()

        if DEBUG:
            print(
                json.dumps(
                    data,
                    indent=2,
                )
            )

        if (
            data["meta"]["code"] != 200
            or not data["data"]
        ):

            return None

        mapping = data["data"][0]

        bricklink_part = (
            mapping["item"]["no"]
        )

        bricklink_color = (
            mapping["color_id"]
        )

        item_type = (
            mapping["item"]["type"]
        )

        print(
            "   BrickLink match: "
            f"{bricklink_part} "
            f"Color {bricklink_color}"
        )

        time.sleep(0.5)

        return {
            "bl_part_no": (
                bricklink_part
            ),
            "bl_color_id": (
                bricklink_color
            ),
            "bl_item_type": (
                item_type
            ),
            "source": (
                "bricklink"
            ),
        }

    except Exception as e:

        print(
            "   BrickLink lookup failed:",
            e,
        )

        return None

# ------------------------------------------------------------
# REBRICKABLE FALLBACK
# ------------------------------------------------------------


def lookup_rebrickable_fallback(
    element_id,
):

    api_key = os.getenv(
        "REBRICKABLE_API_KEY"
    )

    if not api_key:

        return None

    url = (
        "https://rebrickable.com/api/v3/lego/"
        f"elements/{element_id}/"
    )

    headers = {
        "Authorization": (
            f"key {api_key}"
        ),
        "User-Agent": (
            "brick-palette-generator/1.0"
        ),
    }

    try:

        response = requests.get(
            url,
            headers=headers,
            timeout=30,
        )

        print(
            f"   Rebrickable HTTP "
            f"{response.status_code}"
        )

        if response.status_code != 200:

            return None

        data = response.json()

        if DEBUG:

            print(
                json.dumps(
                    data,
                    indent=2,
                )
            )

        part = data.get(
            "part",
            {},
        )

        color = data.get(
            "color",
            {},
        )

        if not part or not color:

            return None

        if part.get(
            "part_cat_id"
        ) == 57:

            print(
                "   Skipping DUPLO figure"
            )

            return None

        bricklink_ids = (
            part.get(
                "external_ids",
                {},
            ).get(
                "BrickLink",
                [],
            )
        )

        if not bricklink_ids:

            print(
                "   No BrickLink part mapping"
            )

            return None

        bl_color_ids = (
            color.get(
                "external_ids",
                {},
            ).get(
                "BrickLink",
                {},
            ).get(
                "ext_ids",
                [],
            )
        )

        if not bl_color_ids:

            print(
                "   No BrickLink color mapping"
            )

            return None

        bricklink_part = (
            bricklink_ids[0]
        )

        bricklink_color = (
            bl_color_ids[0]
        )

        print(
            "   Rebrickable fallback: "
            f"{bricklink_part} "
            f"Color "
            f"{bricklink_color}"
        )

        time.sleep(1.2)

        return {
            "bl_part_no": (
                bricklink_part
            ),
            "bl_color_id": (
                bricklink_color
            ),
            "bl_item_type": (
                "PART"
            ),
            "source": (
                "rebrickable_fallback"
            ),
        }

    except Exception as e:

        print(
            "   Rebrickable fallback failed:",
            e,
        )

        return None

# ------------------------------------------------------------
# RESOLVE ELEMENT
# ------------------------------------------------------------


def resolve_element_mapping(
    element_id,
):

    element_id = str(
        element_id
    )

    if element_id in manual_overrides:

        print(
            "   Using MANUAL override"
        )

        return manual_overrides[
            element_id
        ]

    if element_id in failed_cache:

        print(
            "   Previously failed"
        )

        return None

    if element_id in lego_to_bl_cache:

        print(
            "   Using cached mapping"
        )

        return lego_to_bl_cache[
            element_id
        ]

    mapping = lookup_bricklink_mapping(
        element_id
    )

    if not mapping:

        mapping = (
            lookup_rebrickable_fallback(
                element_id
            )
        )

        if mapping:

            manual_overrides[
                element_id
            ] = mapping

            save_json_file(
                OVERRIDE_FILE,
                manual_overrides,
            )

            failed_cache.pop(
                element_id,
                None,
            )

            save_json_file(
                FAILED_CACHE_FILE,
                failed_cache,
            )

    if not mapping:

        failed_cache[
            element_id
        ] = {
            "status": (
                "unresolved"
            ),
            "checked_at": (
                time.time()
            ),
        }

        save_json_file(
            FAILED_CACHE_FILE,
            failed_cache,
        )

        return None

    lego_to_bl_cache[
        element_id
    ] = mapping

    save_json_file(
        LEGO_TO_BL_CACHE_FILE,
        lego_to_bl_cache,
    )

    reverse_key = (
        f"{mapping['bl_part_no']}"
        f"|{mapping['bl_color_id']}"
        f"|{mapping['bl_item_type']}"
    )

    if reverse_key not in bl_to_lego_cache:

        bl_to_lego_cache[
            reverse_key
        ] = []

    if (
        element_id
        not in bl_to_lego_cache[
            reverse_key
        ]
    ):

        bl_to_lego_cache[
            reverse_key
        ].append(
            element_id
        )

    save_json_file(
        BL_TO_LEGO_CACHE_FILE,
        bl_to_lego_cache,
    )

    return mapping

# ------------------------------------------------------------
# LEGO FETCH
# ------------------------------------------------------------


def fetch_lego_inventory(
    per_page=400,
):

    url = (
        "https://www.lego.com/"
        "api/graphql/PickABrickQuery"
    )

    headers = {
        "Referer": (
            "https://www.lego.com/"
            "en-us/pick-and-build/"
            "pick-a-brick"
        ),
        "User-Agent": (
            "Mozilla/5.0 "
            "(Windows NT 10.0; "
            "Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/124.0.0.0 "
            "Safari/537.36"
        ),
    }

    all_results = []

    page = 1

    while True:

        print(
            f"\nFetching page {page}..."
        )

        json_body = {
            "operationName": (
                "PickABrickQuery"
            ),
            "variables": {
                "input": {
                    "page": page,
                    "perPage": per_page,
                    "sort": {
                        "key": (
                            "RELEVANCE"
                        ),
                        "direction": (
                            "DESC"
                        ),
                    },
                    "availability": [
                        "AVAILABLE",
                        "OUT_OF_STOCK",
                    ],
                    "query": "",
                    "fetchSiblings": True,
                }
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

        print(
            "HTTP:",
            response.status_code,
        )

        response.raise_for_status()

        data = response.json()

        search = (
            data["data"][
                "searchElements"
            ]
        )

        results = search[
            "results"
        ]

        total = search[
            "total"
        ]

        print(
            f"Received "
            f"{len(results)} "
            f"results "
            f"(total: {total})"
        )

        if not results:
            break

        all_results.extend(
            results
        )

        if len(results) < per_page:
            break

        page += 1

        time.sleep(0.05)

    snapshot_data = {
        "timestamp": (
            time.time()
        ),
        "results": (
            all_results
        ),
    }

    save_json_file(
        SNAPSHOT_FILE,
        snapshot_data,
    )

    return all_results

# ------------------------------------------------------------
# XML GENERATION
# ------------------------------------------------------------


def build_xml(items):

    inventory = ET.Element(
        "INVENTORY"
    )

    for item in items:

        item_el = ET.SubElement(
            inventory,
            "ITEM",
        )

        ET.SubElement(
            item_el,
            "ITEMTYPE",
        ).text = item[
            "itemtype"
        ]

        ET.SubElement(
            item_el,
            "ITEMID",
        ).text = item[
            "itemid"
        ]

        ET.SubElement(
            item_el,
            "COLOR",
        ).text = str(
            item["color"]
        )

        ET.SubElement(
            item_el,
            "MAXPRICE",
        ).text = item.get(
            "maxprice",
            "0.0000",
        )

        ET.SubElement(
            item_el,
            "MINQTY",
        ).text = str(
            item.get(
                "qty",
                1,
            )
        )

        ET.SubElement(
            item_el,
            "CONDITION",
        ).text = "X"

        ET.SubElement(
            item_el,
            "REMARKS",
        ).text = item[
            "remarks"
        ]

        ET.SubElement(
            item_el,
            "NOTIFY",
        ).text = "N"

    xml_bytes = ET.tostring(
        inventory,
        encoding="utf-8",
    )

    xml_str = (
        minidom.parseString(
            xml_bytes
        ).toprettyxml(
            indent="  "
        )
    )

    xml_lines = (
        xml_str.splitlines()
    )

    return "\n".join(
        line
        for line in xml_lines
        if not line.startswith(
            "<?xml"
        )
    )

# ------------------------------------------------------------
# MAIN
# ------------------------------------------------------------


def main():

    logging.basicConfig(
        level=logging.INFO
    )

    load_part_categories()

    channel_exports = {}

    seen_combos = set()

    print(
        "Fetching LEGO inventory..."
    )

    results = fetch_lego_inventory()

    unique = {}

    for item in results:

        unique[
            item["id"]
        ] = item

    results = list(
        unique.values()
    )

    print(
        f"\nFound "
        f"{len(results)} "
        f"unique items"
    )

    for idx, item in enumerate(
        results,
        start=1,
    ):

        element_id = item.get(
            "id"
        )

        design_id = item.get(
            "designId"
        )

        channel = get_channel(
            item
        )

        name = item.get(
            "name",
            "Unknown",
        )

        print(
            f"[{idx}] "
            f"Element {element_id} "
            f"Design {design_id} "
            f"Channel {channel} "
            f":: {name}"
        )

        if not element_id:
            continue

        mapping = (
            resolve_element_mapping(
                element_id
            )
        )

        if not mapping:

            print(
                "   No mapping"
            )

            continue

        combo = (
            mapping[
                "bl_part_no"
            ],
            mapping[
                "bl_color_id"
            ],
        )

        channel_combo = (
            channel,
            combo[0],
            combo[1],
        )

        combo_key = (
            f"{combo[0]}"
            f"|{combo[1]}"
        )

        if (
            channel_combo
            in seen_combos
        ):

            print(
                "   DUPLICATE "
                f"{combo[0]} "
                f"Color {combo[1]}"
            )

            if (
                combo_key
                not in duplicate_cache
            ):

                duplicate_cache[
                    combo_key
                ] = {
                    "primary_element_id": (
                        element_id
                    ),
                    "duplicates": [],
                }

            duplicate_cache[
                combo_key
            ][
                "duplicates"
            ].append(
                element_id
            )

            save_json_file(
                DUPLICATE_CACHE_FILE,
                duplicate_cache,
            )

            continue

        seen_combos.add(
            channel_combo
        )

        if (
            channel
            not in channel_exports
        ):

            channel_exports[
                channel
            ] = []

        channel_exports[
            channel
        ].append(
            {
                "itemid": (
                    mapping[
                        "bl_part_no"
                    ]
                ),

                "itemtype": (
                    ITEM_TYPE_MAP.get(
                        mapping[
                            "bl_item_type"
                        ],
                        "P",
                    )
                ),

                "color": (
                    mapping[
                        "bl_color_id"
                    ]
                ),

                "qty": 1,

                "maxprice": (
                    f"{(
                        item.get(
                            'price',
                            {}
                        ).get(
                            'centAmount',
                            0,
                        ) / 100
                    ):.4f}"
                ),

                "remarks": (
                    f"{name} "
                    f"(LEGO Element "
                    f"{element_id}) "
                    f"[Channel "
                    f"{channel}]"
                ).replace(
                    "&",
                    " and ",
                ),
            }
        )

        print(
            f"   BL: "
            f"{mapping['bl_part_no']} "
            f"Color "
            f"{mapping['bl_color_id']}"
        )

    print(
        "\nGenerating XML exports..."
    )

    for (
        channel,
        items,
    ) in channel_exports.items():

        if not items:
            continue

        xml_output = build_xml(
            items
        )

        filename = (
            "lego_inventory_"
            f"{get_channel_filename(channel)}"
            ".xml"
        )

        output_path = (
            OUTPUT_DIR
            / filename
        )

        with open(
            output_path,
            "w",
            encoding="utf-8",
        ) as f:

            f.write(
                xml_output
            )

        print(
            f"Saved {output_path} "
            f"({len(items)} items)"
        )

    all_items = []

    for items in (
        channel_exports.values()
    ):

        all_items.extend(
            items
        )

    xml_output = build_xml(
        all_items
    )

    output_path = (
        OUTPUT_DIR
        / "lego_inventory_all.xml"
    )

    with open(
        output_path,
        "w",
        encoding="utf-8",
    ) as f:

        f.write(
            xml_output
        )

    print(
        f"\nSaved "
        f"{output_path} "
        f"({len(all_items)} items)"
    )

    print("\nDONE")


if __name__ == "__main__":
    main()
