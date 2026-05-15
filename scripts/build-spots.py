#!/usr/bin/env python3
"""
Build the SPOTS_DATA inline JS block for index.html.

Queries NYC OpenData (Parking Regulation Locations and Signs, dataset nfid-uabd) for
all sanitation street-cleaning signs within ~1.5mi of 253 Cumberland St, parses them,
groups by (street, from, to, side), and emits a compact JS array of spots.

Re-run when ASP signs change (yearly is plenty). Replaces the block between
the SPOTS-DATA-START and SPOTS-DATA-END markers in index.html in place.

Usage:
    python3 scripts/build-spots.py

No dependencies beyond the Python 3 stdlib.
"""

import json
import re
import subprocess
from collections import defaultdict
from pathlib import Path

# 253 Cumberland St, Brooklyn (NYS Plane Long Island Zone, feet).
HOME_X = 991900
HOME_Y = 189300
RADIUS_FT = 7920  # ~1.5 mi, ~8-min bike

API_URL = (
    "https://data.cityofnewyork.us/resource/nfid-uabd.json"
    "?$limit=50000"
    "&$where=borough%3D%27Brooklyn%27"
    "%20AND%20record_type%3D%27Current%27"
    "%20AND%20upper(sign_description)%20like%20%27%25SANITATION%25%27"
)

DAY_TO_BIT = {
    "SUNDAY": 0, "MONDAY": 1, "TUESDAY": 2, "WEDNESDAY": 3,
    "THURSDAY": 4, "FRIDAY": 5, "SATURDAY": 6,
}
SIDE_TO_INT = {"N": 0, "S": 1, "E": 2, "W": 3}

DAY_RE = re.compile(
    r"\b(MONDAY|TUESDAY|WEDNESDAY|THURSDAY|FRIDAY|SATURDAY|SUNDAY)\b"
)
TIME_RE = re.compile(
    r"(\d{1,2}(?::\d{2})?)\s*(AM|PM|NOON|MIDNIGHT)\s*[-–]\s*"
    r"(\d{1,2}(?::\d{2})?)\s*(AM|PM|NOON|MIDNIGHT)",
    re.IGNORECASE,
)


def parse_time(t: str, suffix: str) -> int:
    """Return minutes since midnight for e.g. ('9:30', 'AM') or ('1', 'PM')."""
    suffix = suffix.upper()
    if suffix == "MIDNIGHT":
        return 0
    if suffix == "NOON":
        return 12 * 60
    if ":" in t:
        h, m = (int(x) for x in t.split(":"))
    else:
        h, m = int(t), 0
    if suffix == "AM":
        if h == 12:
            h = 0
    else:  # PM
        if h != 12:
            h += 12
    return h * 60 + m


def fetch() -> list:
    print(f"Fetching {API_URL}")
    # Use curl rather than urllib so the script works on systems where the
    # Python build lacks bundled SSL (common with Homebrew Python on macOS).
    result = subprocess.run(
        ["curl", "-fsS", "-H", "Accept: application/json", API_URL],
        check=True, capture_output=True, text=True,
    )
    data = json.loads(result.stdout)
    print(f"  {len(data)} sign records received")
    return data


def within_radius(d: dict) -> bool:
    try:
        x = float(d.get("sign_x_coord") or 0)
        y = float(d.get("sign_y_coord") or 0)
    except (TypeError, ValueError):
        return False
    return (x - HOME_X) ** 2 + (y - HOME_Y) ** 2 <= RADIUS_FT ** 2


def normalize_street(s: str) -> str:
    """Normalize sign field strings for stable indexing."""
    s = (s or "").strip().upper()
    # Collapse internal whitespace.
    s = re.sub(r"\s+", " ", s)
    # Common variants.
    s = s.replace("DE KALB", "DEKALB")
    s = s.replace("FT GREENE", "FORT GREENE")
    s = s.replace("STREET", "ST").replace("AVENUE", "AVE")
    s = s.replace("PLACE", "PL").replace("ROAD", "RD")
    s = s.replace("BOULEVARD", "BLVD").replace("PARKWAY", "PKWY")
    s = s.replace("EXTENSION", "EXT").replace("EXPRESSWAY", "EXPY")
    return s


def parse_regulations(desc: str):
    """Extract list of (day_bit, start_min, end_min) tuples from a sign description.

    Returns [] if not parseable as a normal daytime sanitation rule. We skip
    overnight ("MOON & STARS") signs because the user can't act on them anyway.
    """
    up = (desc or "").upper()
    if "NO PARKING" not in up or "SANITATION" not in up:
        return []
    if "MOON" in up or "STARS" in up:
        # Overnight commercial cleaning. Out of scope for this app.
        return []
    days = DAY_RE.findall(up)
    if not days:
        return []
    m = TIME_RE.search(up)
    if not m:
        return []
    start = parse_time(m.group(1), m.group(2))
    end = parse_time(m.group(3), m.group(4))
    if end <= start:
        return []
    return [(DAY_TO_BIT[d], start, end) for d in days]


def build_spots(records: list):
    # group by (on_street, from_street, to_street, side_of_street)
    groups = defaultdict(list)
    for d in records:
        if not within_radius(d):
            continue
        regs = parse_regulations(d.get("sign_description", ""))
        if not regs:
            continue
        side = d.get("side_of_street", "").upper().strip()
        if side not in SIDE_TO_INT:
            continue
        street = normalize_street(d.get("on_street", ""))
        frm = normalize_street(d.get("from_street", ""))
        to = normalize_street(d.get("to_street", ""))
        if not (street and frm and to):
            continue
        try:
            x = float(d.get("sign_x_coord") or 0)
            y = float(d.get("sign_y_coord") or 0)
        except (TypeError, ValueError):
            x = y = 0
        groups[(street, frm, to, side)].append((regs, x, y))

    # Within each group, consolidate regulations.
    # A block-side may post multiple signs with the same rule, or occasionally
    # two rules (e.g., MON/THU 9:30-11). We collapse to (day_mask, start, end)
    # sets keyed by (start, end), OR-ing day bits.
    spots = []
    street_table = {}  # name -> idx
    def street_idx(name):
        if name not in street_table:
            street_table[name] = len(street_table)
        return street_table[name]

    for (street, frm, to, side), items in groups.items():
        by_window = defaultdict(int)  # (start, end) -> day_mask
        xs, ys = [], []
        for regs, x, y in items:
            if x and y:
                xs.append(x); ys.append(y)
            for day_bit, start, end in regs:
                by_window[(start, end)] |= 1 << day_bit

        if not xs:
            continue
        mid_x = round(sum(xs) / len(xs))
        mid_y = round(sum(ys) / len(ys))

        # Emit one spot per distinct time window on this block-side.
        for (start, end), day_mask in by_window.items():
            spots.append([
                street_idx(street),
                street_idx(frm),
                street_idx(to),
                SIDE_TO_INT[side],
                day_mask,
                start,
                end,
                mid_x - HOME_X,  # store relative coords to keep ints small
                mid_y - HOME_Y,
            ])

    # Sort by distance from home (smallest squared distance first) so default
    # picks and search ordering favor closer spots without runtime sorting.
    spots.sort(key=lambda s: s[7] * s[7] + s[8] * s[8])

    # Build reverse street table
    streets = [None] * len(street_table)
    for name, idx in street_table.items():
        streets[idx] = name
    return streets, spots


def format_block(streets, spots) -> str:
    streets_json = json.dumps(streets, separators=(",", ":"))
    rows = ",\n".join(
        "[" + ",".join(str(x) for x in row) + "]" for row in spots
    )
    return (
        "// Generated by scripts/build-spots.py from NYC OpenData (nfid-uabd).\n"
        f"// {len(spots)} block-side spots within ~1.5mi of 253 Cumberland St.\n"
        "// Spot row: [streetIdx, fromIdx, toIdx, side(0N1S2E3W), dayMask, startMin, endMin, dxFromHome, dyFromHome]\n"
        f"const STREETS = {streets_json};\n"
        f"const SPOTS = [\n{rows}\n];\n"
    )


def inline_into_index(block: str, html_path: Path):
    text = html_path.read_text()
    start = "// SPOTS-DATA-START"
    end = "// SPOTS-DATA-END"
    if start not in text or end not in text:
        raise SystemExit(
            f"Markers {start!r}/{end!r} not found in {html_path}. "
            "Add them around the spots block first."
        )
    pre, rest = text.split(start, 1)
    _, post = rest.split(end, 1)
    new = f"{pre}{start}\n{block}{end}{post}"
    html_path.write_text(new)
    print(f"  inlined {len(block):,} chars into {html_path}")


def main():
    records = fetch()
    streets, spots = build_spots(records)
    print(f"  {len(streets)} unique street names")
    print(f"  {len(spots)} block-side spot entries")
    block = format_block(streets, spots)
    repo_root = Path(__file__).resolve().parent.parent
    inline_into_index(block, repo_root / "index.html")
    print("done.")


if __name__ == "__main__":
    main()
