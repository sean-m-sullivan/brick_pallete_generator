#!/usr/bin/env python3

import json
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

# ------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------

DEBUG = False

REBRICKABLE_API_KEY = os.getenv("REBRICKABLE_API_KEY")

CACHE_DIR = Path("cache")

FAILED_CACHE_FILE = CACHE_DIR / "failed_mappings.json"

OVERRIDE_FILE = CACHE_DIR / "manual_overrides.json"

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
        )


# ------------------------------------------------------------
# LOAD FILES
# ------------------------------------------------------------

failed_cache = load_json_file(
    FAILED_CACHE_FILE,
    {},
)

manual_overrides = load_json_file(
    OVERRIDE_FILE,
    {},
)

# ------------------------------------------------------------
# REBRICKABLE LOOKUP
# ------------------------------------------------------------


def lookup_rebrickable(
    element_id,
):

    if not REBRICKABLE_API_KEY:

        print("Missing REBRICKABLE_API_KEY")

        return None

    url = "https://rebrickable.com/api/v3/lego/" f"elements/{element_id}/"

    headers = {
        "Authorization": (f"key {REBRICKABLE_API_KEY}"),
        "User-Agent": ("lego-recovery-script/1.0"),
    }

    #
    # Retry transient failures
    #

    for _attempt in range(3):

        try:

            print(f"\nRebrickable lookup " f"for {element_id}")

            response = requests.get(
                url,
                headers=headers,
                timeout=30,
            )

            print(f"   HTTP " f"{response.status_code}")

            #
            # Not found
            #

            if response.status_code == 404:

                print("   Element not found")

                return None

            #
            # Rate limited
            #

            if response.status_code == 429:

                print("   Rate limited")

                time.sleep(5)

                continue

            #
            # Server error
            #

            if response.status_code >= 500:

                print("   Server error")

                time.sleep(2)

                continue

            response.raise_for_status()

            data = response.json()

            if DEBUG:

                print(
                    json.dumps(
                        data,
                        indent=2,
                    )
                )

            #
            # Extract part
            #

            part = data.get(
                "part",
                {},
            )

            if not part:

                print("   Missing part data")

                return None

            #
            # BrickLink part IDs
            #

            bricklink_ids = part.get(
                "external_ids",
                {},
            ).get(
                "BrickLink",
                [],
            )

            if not bricklink_ids:

                print("   No BrickLink " "external IDs")

                return None

            bricklink_part = bricklink_ids[0]

            #
            # Extract color
            #

            color = data.get(
                "color",
                {},
            )

            if not color:

                print("   Missing color data")

                return None

            #
            # BrickLink color IDs
            #

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

                print("   No BrickLink " "color mapping")

                return None

            bricklink_color = bl_color_ids[0]

            #
            # Determine item type
            #

            bl_item_type = "PART"

            if bricklink_part.startswith("47"):

                bl_item_type = "MINIFIG"

            print("   RECOVERED: " f"{bricklink_part} " f"Color " f"{bricklink_color}")

            #
            # Be polite
            #

            time.sleep(1.2)

            return {
                "bl_part_no": (bricklink_part),
                "bl_color_id": (bricklink_color),
                "bl_item_type": (bl_item_type),
                "source": ("rebrickable_fallback"),
            }

        except requests.exceptions.Timeout:

            print("   Request timeout")

            time.sleep(2)

        except requests.exceptions.ConnectionError:

            print("   Connection error")

            time.sleep(2)

        except Exception as e:

            print(
                "   Lookup failed:",
                e,
            )

            time.sleep(2)

    #
    # Permanent failure
    #

    return None


# ------------------------------------------------------------
# MAIN
# ------------------------------------------------------------


def main():

    print(f"Found " f"{len(failed_cache)} " f"failed mappings")

    recovered = 0

    still_failed = 0

    for element_id in failed_cache:

        #
        # Skip existing overrides
        #

        if element_id in manual_overrides:

            continue

        mapping = lookup_rebrickable(element_id)

        if not mapping:

            still_failed += 1

            continue

        #
        # Save override
        #

        manual_overrides[element_id] = mapping

        save_json_file(
            OVERRIDE_FILE,
            manual_overrides,
        )

        recovered += 1

    print("\nDONE")

    print(f"Recovered: " f"{recovered}")

    print(f"Still failed: " f"{still_failed}")


if __name__ == "__main__":
    main()
