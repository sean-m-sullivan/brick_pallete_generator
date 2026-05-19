#!/usr/bin/env python3

import ast
import json
import re
from pathlib import Path

from bs4 import BeautifulSoup
from curl_cffi import requests

DATA_DIR = Path("data")

OUTPUT_FILE = DATA_DIR / "color_database.json"

URL = "https://rebrickable.com/colors/"


def parse_name_list(raw_names):

    try:

        parsed = ast.literal_eval(raw_names)

        if isinstance(parsed, list):

            return parsed

    except (
        ValueError,
        SyntaxError,
    ):

        pass

    return [raw_names]


def build_variant_entry(
    source_id,
    names,
):

    return {
        "id": source_id,
        "name": names[0],
        "aliases": names[1:],
    }


def parse_multi_mapping(cell):

    text = cell.get_text(
        " ",
        strip=True,
    )

    if not text:
        return None

    #
    # Matches:
    #
    # 26 ['Black', 'BLACK']
    # 342 ['CONDUCT. BLACK']
    #
    # 117 ['Transparent Glitter', 'TR.W.GLITTER']
    # 122 ['Nature with Glitter']
    #
    matches = re.findall(
        r"(\d+)\s+(\[[^\]]+\])",
        text,
    )

    if not matches:
        return None

    parsed_entries = []

    for raw_id, raw_names in matches:

        names = parse_name_list(raw_names)

        parsed_entries.append(
            build_variant_entry(
                int(raw_id),
                names,
            )
        )

    primary = parsed_entries[0]

    return {
        "id": primary["id"],
        "name": primary["name"],
        "aliases": primary["aliases"],
        "variants": parsed_entries[1:],
    }


def find_colors_table(tables):

    for i, table in enumerate(tables):

        text = table.get_text(
            " ",
            strip=True,
        )

        print(f"\n=== TABLE {i} ===")

        print(text[:500])

        if "BrickLink" in text and "LDraw" in text:

            print(f"\nUsing table {i}")

            return table

    return None


def build_color_database():

    print(f"Fetching {URL}")

    response = requests.get(
        URL,
        timeout=60,
        impersonate="chrome124",
        headers={
            "User-Agent": ("Mozilla/5.0 " "(X11; Linux x86_64) " "AppleWebKit/537.36 " "(KHTML, like Gecko) " "Chrome/124.0.0.0 " "Safari/537.36"),
            "Referer": ("https://rebrickable.com/"),
        },
    )

    response.raise_for_status()

    print(f"HTTP {response.status_code}")

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    tables = soup.find_all("table")

    print(f"Found tables: " f"{len(tables)}")

    table = find_colors_table(tables)

    if not table:

        raise RuntimeError("Could not find colors table")

    rows = table.find_all("tr")

    print(f"Found rows: " f"{len(rows)}")

    color_database = {
        "rebrickable": {},
        "bricklink": {},
        "ldraw": {},
        "lego": {},
        "brickowl": {},
    }

    for row in rows:

        cols = row.find_all("td")

        if len(cols) < 12:
            continue

        #
        # Column layout:
        #
        # 0 = image
        # 1 = rebrickable id
        # 2 = name
        # 3 = rgb
        # 4 = num parts
        # 5 = num sets
        # 6 = first year
        # 7 = last year
        # 8 = LEGO
        # 9 = LDraw
        # 10 = BrickLink
        # 11 = BrickOwl
        #

        try:

            rebrickable_id = int(cols[1].get_text(strip=True))

        except ValueError:

            continue

        name = cols[2].get_text(strip=True)

        rgb = cols[3].get_text(strip=True)

        lego = parse_multi_mapping(cols[8])

        ldraw = parse_multi_mapping(cols[9])

        bricklink = parse_multi_mapping(cols[10])

        brickowl = parse_multi_mapping(cols[11])

        entry = {
            "rebrickable": {
                "id": rebrickable_id,
                "name": name,
            },
            "rgb": rgb,
            "lego": lego,
            "ldraw": ldraw,
            "bricklink": bricklink,
            "brickowl": brickowl,
        }

        #
        # Rebrickable
        #

        color_database["rebrickable"][str(rebrickable_id)] = entry

        #
        # LEGO
        #

        if lego:

            color_database["lego"][str(lego["id"])] = entry

            for variant in lego["variants"]:

                color_database["lego"][str(variant["id"])] = entry

        #
        # LDraw
        #

        if ldraw:

            color_database["ldraw"][str(ldraw["id"])] = entry

            for variant in ldraw["variants"]:

                color_database["ldraw"][str(variant["id"])] = entry

        #
        # BrickLink
        #

        if bricklink:

            color_database["bricklink"][str(bricklink["id"])] = entry

        #
        # BrickOwl
        #

        if brickowl:

            color_database["brickowl"][str(brickowl["id"])] = entry

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            color_database,
            f,
            indent=2,
            sort_keys=True,
        )

    print(f"\nSaved color database: " f"{OUTPUT_FILE}")

    print(f"Rebrickable colors: " f"{len(color_database['rebrickable'])}")

    print(f"BrickLink colors: " f"{len(color_database['bricklink'])}")

    print(f"LDraw colors: " f"{len(color_database['ldraw'])}")

    print(f"LEGO colors: " f"{len(color_database['lego'])}")

    print(f"BrickOwl colors: " f"{len(color_database['brickowl'])}")


if __name__ == "__main__":

    build_color_database()
