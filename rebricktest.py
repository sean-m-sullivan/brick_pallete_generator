#!/usr/bin/env python3

import json
import os
import time

import requests

from dotenv import load_dotenv

load_dotenv()

REBRICKABLE_API_KEY = os.getenv("REBRICKABLE_API_KEY")

if not REBRICKABLE_API_KEY:
    raise SystemExit("Missing REBRICKABLE_API_KEY")

headers = {"Authorization": (f"key {REBRICKABLE_API_KEY}")}

#
# Test IDs
#

ELEMENT_IDS = [
    "6569837",
    "6569839",
    "6569857",
    "6569862",
    "6585429",
    "6585846",
    "6586684",
    "6488925",
]

for element_id in ELEMENT_IDS:
    print("\n====================")
    print(f"ELEMENT {element_id}")
    print("====================")

    url = f"https://rebrickable.com/api/v3/lego/elements/{element_id}/"

    try:
        response = requests.get(
            url,
            headers=headers,
            timeout=30,
        )

        print(f"HTTP {response.status_code}")

        if response.status_code != 200:
            print(response.text)

            continue

        data = response.json()

        #
        # Pretty dump
        #

        print(
            json.dumps(
                data,
                indent=2,
            )
        )

        #
        # Extract part
        #

        part = data.get("part", {})

        part_name = part.get("name")

        part_num = part.get("part_num")

        print(f"\nPart: {part_num}")

        print(f"Name: {part_name}")

        #
        # BrickLink IDs
        #

        bricklink_ids = part.get("external_ids", {}).get("BrickLink", [])

        print(f"BrickLink IDs: {bricklink_ids}")

        #
        # Color info
        #

        color = data.get("color", {})

        print(f"Color name: {color.get('name')}")

        bl_color_ids = (
            color.get("external_ids", {}).get("BrickLink", {}).get("ext_ids", [])
        )

        print(f"BrickLink colors: {bl_color_ids}")

        #
        # Category
        #

        print(f"Category ID: {part.get('part_cat_id')}")

    except Exception as e:
        print(f"FAILED: {e}")

    time.sleep(1)
