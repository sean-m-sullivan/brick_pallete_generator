#!/usr/bin/env python3

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
# BRICKLINK AUTH
# ------------------------------------------------------------

auth = OAuth1(
    os.environ["BRICKLINK_CONSUMER_KEY"],
    os.environ["BRICKLINK_CONSUMER_SECRET"],
    os.environ["BRICKLINK_TOKEN"],
    os.environ["BRICKLINK_TOKEN_SECRET"],
)

REBRICKABLE_API_KEY = os.environ.get(
    "REBRICKABLE_API_KEY"
)

# ------------------------------------------------------------
# OUTPUT
# ------------------------------------------------------------

OUTPUT_DIR = Path("output")

OUTPUT_DIR.mkdir(exist_ok=True)

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
# CACHE DIRECTORIES
# ------------------------------------------------------------

CACHE_DIR = Path("cache")

CACHE_DIR.mkdir(exist_ok=True)

# ------------------------------------------------------------
# CACHE FILES
# ------------------------------------------------------------

CACHE_FILE = (
    CACHE_DIR / "bricklink_cache.json"
)

OVERRIDE_FILE = (
    CACHE_DIR / "manual_overrides.json"
)

DUPLICATE_CACHE_FILE = (
    CACHE_DIR / "duplicate_cache.json"
)

BESTSELLER_CACHE_FILE = (
    CACHE_DIR / "bestseller_snapshot.json"
)

FAILED_CACHE_FILE = (
    CACHE_DIR / "failed_mappings.json"
)
# ------------------------------------------------------------
# SAFE JSON LOADER
# ------------------------------------------------------------


def load_json_file(path, default):

    if os.path.exists(path):

        try:

            with open(path, encoding="utf-8") as f:

                return json.load(f)

        except Exception as e:

            print(
                f"WARNING: Failed loading "
                f"{path}: {e}"
            )

    return default


# ------------------------------------------------------------
# SAVE JSON
# ------------------------------------------------------------


def save_json_file(path, data):

    with open(
        path,
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(data, f, indent=2)


# ------------------------------------------------------------
# LOAD CACHES
# ------------------------------------------------------------

mapping_cache = load_json_file(
    CACHE_FILE,
    {},
)

manual_overrides = load_json_file(
    OVERRIDE_FILE,
    {},
)

duplicate_cache = load_json_file(
    DUPLICATE_CACHE_FILE,
    {},
)

failed_cache = load_json_file(
    FAILED_CACHE_FILE,
    {},
)

bestseller_snapshot = load_json_file(
    BESTSELLER_CACHE_FILE,
    {},
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

    return mapping.get(channel, channel)


# ------------------------------------------------------------
# REBRICKABLE FALLBACK
# ------------------------------------------------------------


def lookup_rebrickable(element_id):

    if not REBRICKABLE_API_KEY:

        return None

    url = (
        "https://rebrickable.com/api/v3/lego/"
        f"parts/?search={element_id}"
    )

    headers = {
        "Authorization": (
            f"key {REBRICKABLE_API_KEY}"
        )
    }

    try:

        response = requests.get(
            url,
            headers=headers,
            timeout=30,
        )

        response.raise_for_status()

        data = response.json()

        results = data.get(
            "results",
            [],
        )

        if not results:

            return None

        part = results[0]

        part_num = part.get(
            "part_num"
        )

        if not part_num:

            return None

        print(
            "   Rebrickable matched "
            f"{part_num}"
        )

        #
        # Color unknown from Rebrickable
        #
        # Default to 0 for now
        #

        return {
            "bl_part_no": part_num,
            "bl_color_id": 0,
        }

    except Exception as e:

        print(
            "   Rebrickable lookup failed:",
            e,
        )

        return None


# ------------------------------------------------------------
# LEGO FETCH
# ------------------------------------------------------------


def fetch_lego_inventory(per_page=400):

    url = (
        "https://www.lego.com/api/graphql/"
        "PickABrickQuery"
    )

    headers = {
        "Referer": (
            "https://www.lego.com/en-us/"
            "pick-and-build/pick-a-brick"
        ),
        "User-Agent": (
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/122.0.0.0 "
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
                        "key": "RELEVANCE",
                        "direction": "DESC",
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
        )

        print(
            "HTTP:",
            response.status_code,
        )

        response.raise_for_status()

        data = response.json()

        search = data["data"][
            "searchElements"
        ]

        results = search["results"]

        total = search["total"]

        print(
            f"Received {len(results)} "
            f"results "
            f"(total available: {total})"
        )

        if not results:

            break

        all_results.extend(results)

        if len(results) < per_page:

            break

        page += 1

        time.sleep(0.05)

    #
    # Build channel summary
    #

    channels = {}

    for item in all_results:

        channel = get_channel(item)

        channels.setdefault(channel, 0)

        channels[channel] += 1

    print("\nChannel summary:")

    for channel, count in sorted(
        channels.items()
    ):

        print(
            f"  {channel}: {count}"
        )

    #
    # Save snapshot
    #

    snapshot_data = {
        "timestamp": time.time(),
        "total_results": len(all_results),
        "channels": channels,
        "results": all_results,
    }

    save_json_file(
        BESTSELLER_CACHE_FILE,
        snapshot_data,
    )

    return all_results


# ------------------------------------------------------------
# LEGO ELEMENT -> BRICKLINK
# ------------------------------------------------------------


def convert_element_to_bricklink(
    element_id
):

    element_id = str(element_id)

    #
    # Manual override first
    #

    if element_id in manual_overrides:

        print(
            "   Using MANUAL override"
        )

        return manual_overrides[
            element_id
        ]

    #
    # Failed cache
    #

    if element_id in failed_cache:

        print(
            "   Retrying previously "
            "failed mapping"
        )

    #
    # BrickLink lookup
    #

    url = (
        "https://api.bricklink.com/"
        "api/store/v1/"
        f"item_mapping/{element_id}"
    )

    response = requests.get(
        url,
        auth=auth,
        timeout=30,
    )

    print(
        "\nBRICKLINK RAW RESPONSE:"
    )

    print(response.text)

    data = response.json()

    #
    # Successful BrickLink mapping
    #

    if (
        data.get(
            "meta",
            {},
        ).get("code")
        == 200
        and data.get("data")
        and len(data["data"]) > 0
    ):

        mapping = data["data"][0]

        item = mapping.get("item")

        color_id = mapping.get(
            "color_id"
        )

        if (
            item
            and item.get("no")
            and color_id is not None
        ):

            return {
                "bl_part_no": item["no"],
                "bl_color_id": color_id,
            }

    #
    # Rebrickable fallback
    #

    print(
        "   Trying Rebrickable fallback"
    )

    rb_mapping = lookup_rebrickable(
        element_id
    )

    if rb_mapping:

        return rb_mapping

    #
    # Still unresolved
    #

    failed_cache[element_id] = {
        "status": "unresolved",
        "checked_at": time.time(),
    }

    save_json_file(
        FAILED_CACHE_FILE,
        failed_cache,
    )

    return None


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
        ).text = "P"

        ET.SubElement(
            item_el,
            "ITEMID",
        ).text = item["itemid"]

        ET.SubElement(
            item_el,
            "COLOR",
        ).text = str(item["color"])

        ET.SubElement(
            item_el,
            "QTY",
        ).text = "1"

        ET.SubElement(
            item_el,
            "REMARKS",
        ).text = item["remarks"]

    xml_bytes = ET.tostring(
        inventory,
        encoding="utf-8",
    )

    xml_str = minidom.parseString(
        xml_bytes
    ).toprettyxml(indent="  ")

    #
    # Remove XML declaration
    #

    xml_lines = xml_str.splitlines()

    xml_str = "\n".join(
        line
        for line in xml_lines
        if not line.startswith(
            "<?xml"
        )
    )

    return xml_str


# ------------------------------------------------------------
# MAIN
# ------------------------------------------------------------


def main():

    logging.basicConfig(
        level=logging.INFO
    )

    channel_exports = {}

    seen_combos = set()

    print(
        "Fetching LEGO inventory..."
    )

    results = fetch_lego_inventory()

    #
    # Deduplicate LEGO IDs
    #

    unique = {}

    for item in results:

        unique[item["id"]] = item

    results = list(unique.values())

    print(
        f"\nFound {len(results)} "
        "unique items"
    )

    #
    # Process items
    #

    for idx, item in enumerate(
        results,
        start=1,
    ):

        element_id = item.get("id")

        design_id = item.get(
            "designId"
        )

        channel = get_channel(item)

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

        if channel not in channel_exports:

            channel_exports[channel] = []

        if not element_id:

            continue

        try:

            #
            # Cache first
            #

            if element_id in mapping_cache:

                mapping = mapping_cache[
                    element_id
                ]

                print(
                    "   Using cached mapping"
                )

            else:

                mapping = (
                    convert_element_to_bricklink(
                        element_id
                    )
                )

                if not mapping:

                    print(
                        "   No BrickLink mapping"
                    )

                    continue

                mapping_cache[
                    element_id
                ] = mapping

                save_json_file(
                    CACHE_FILE,
                    mapping_cache,
                )

                print(
                    "   Cached new mapping"
                )

            combo = (
                str(
                    mapping[
                        "bl_part_no"
                    ]
                ),
                int(
                    mapping[
                        "bl_color_id"
                    ]
                ),
            )

            channel_combo = (
                channel,
                combo[0],
                combo[1],
            )

            combo_key = (
                f"{combo[0]}|"
                f"{combo[1]}"
            )

            #
            # Dedupe
            #

            if (
                channel_combo
                in seen_combos
            ):

                print(
                    "   DUPLICATE SKIPPED: "
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
                ].append(element_id)

                save_json_file(
                    DUPLICATE_CACHE_FILE,
                    duplicate_cache,
                )

                continue

            seen_combos.add(
                channel_combo
            )

            channel_exports[
                channel
            ].append(
                {
                    "itemid": combo[0],
                    "color": combo[1],
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

            time.sleep(0.02)

        except Exception as e:

            print(
                "   ERROR:",
                e,
            )

    #
    # Generate XML exports
    #

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

        channel_name = (
            get_channel_filename(
                channel
            )
        )

        filename = (
            f"lego_inventory_"
            f"{channel_name}.xml"
        )

        output_path = (
            OUTPUT_DIR / filename
        )

        with open(
            output_path,
            "w",
            encoding="utf-8",
        ) as f:

            f.write(xml_output)

        print(
            f"Saved {output_path} "
            f"({len(items)} items)"
        )

    #
    # Combined export
    #

    all_items = []

    for items in channel_exports.values():

        all_items.extend(items)

    xml_output = build_xml(
        all_items
    )

    all_output_path = (
        OUTPUT_DIR
        / "lego_inventory_all.xml"
    )

    with open(
        all_output_path,
        "w",
        encoding="utf-8",
    ) as f:

        f.write(xml_output)

    print(
        f"\nSaved "
        f"{all_output_path} "
        f"({len(all_items)} items)"
    )

    print("\nDONE")


if __name__ == "__main__":

    main()