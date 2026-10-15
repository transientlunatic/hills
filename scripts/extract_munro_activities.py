"""
Filter Strava activities down to those that bagged at least one Munro.

Reads data/strava_raw/qualifying_activities.jsonl and cross-references every
tagged summit against the DoBIH hill database (data/hills.yaml) to work out
which are actual Munros (classification "M") as opposed to Munro Tops,
Corbetts, Grahams, hills outside Britain, etc.

The source file mixes three tagging eras, all handled here:
  - modern summitbag.com "⛰️ Name (height m)" markers
  - an older "#NN Name" personal-numbering scheme (no emoji, sometimes no
    height), used before the athlete adopted summitbag.com
  - activities with no structured tag at all, where the hill names only
    appear in the activity title/description as free text, flagged with a
    "(named in title only, ...)" note

Outputs:
  data/strava_raw/munro_activities.jsonl  - activities with >=1 Munro, each
                                             carrying its parsed `summits` list
  data/strava_raw/munro_summits.csv       - long format, one row per
                                             activity/Munro pair (for pandas)
  data/strava_raw/unmatched_summits.csv   - tagged summits that didn't match
                                             anything in the DoBIH database,
                                             for manual review
  data/strava_raw/ambiguous_summits.csv   - summits that matched >1 DoBIH hill
                                             sharing the same bare name, with
                                             no height to disambiguate by, and
                                             couldn't be resolved by context
"""
import csv
import json
import re
from difflib import get_close_matches
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
HILLS_YAML = ROOT / "data" / "hills.yaml"
DOBIH_CSV = ROOT / "data" / "DoBIH_v18_4.csv"
ACTIVITIES_JSONL = ROOT / "data" / "strava_raw" / "qualifying_activities.jsonl"
OUT_DIR = ROOT / "data" / "strava_raw"

# One-off manual resolutions for activities with no recoverable hill names in
# their Strava text at all. "Beating the Tyndrum 4" (2018-07-07) describes a
# GPS dropout ("Something fun happened to the GPS two munros in!") with no
# names given; cross-referencing its location+altitude streams against DoBIH
# coordinates finds three clean altitude peaks matching Ben Lui (recorded
# 1096.7m, 165m from the real 1131.4m summit), Beinn a' Chleibh (907m, 33m
# from 916.3m) before the dropout, and Beinn Dubhchraig (943.5m, 53m from
# 978m) after the GPS resumed elsewhere.
MANUAL_SUMMIT_OVERRIDES = {
    "1687583529": ["Ben Lui", "Beinn a' Chleibh", "Beinn Dubhchraig"],
}

EMOJI_SUMMIT_RE = re.compile(r"⛰️\s*([^•\n]+?)\s*\((\d[\d,]*(?:\.\d+)?)\s*m\)")
HASH_MARKER_RE = re.compile(r"#\d+\s")
ERA_NOTE_RE = re.compile(r"\([^)]*no summitbag tagging this era[^)]*\)")
TITLE_ONLY_RE = re.compile(r"named in title only")
BRACKET_ALIAS_RE = re.compile(r"^(.*?)\s*\[(.*?)\]\s*$")
COMPOUND_NAME_RE = re.compile(r"^(.*?)\s+-\s+(.*)$")


def normalize(name: str) -> str:
    name = name.strip()
    name = name.replace("’", "'").replace("‘", "'").replace("`", "'")
    name = re.sub(r"\s+", " ", name)
    return name.lower()


def load_hill_index():
    """Build normalized-name -> [hill row, ...] index from data/hills.yaml,
    enriched with DoBIH region for disambiguating shared hill names.

    DoBIH names sometimes carry a bracketed alias, e.g. "Ben Nevis [Beinn
    Nibheis]" or "Gulvain [Gaor Bheinn]" - Strava/summitbag descriptions tag
    summits using whichever of the two names is more common, so both the
    base name and the alias are indexed to the same hill.
    """
    with open(HILLS_YAML) as f:
        raw = yaml.safe_load(f)

    regions = pd.read_csv(DOBIH_CSV, low_memory=False, index_col="Number")["Region"]

    by_name = {}
    for number, row in raw.items():
        classifications = [c for c in row["Classification"].split(",") if c]
        region = regions.get(number)
        hill = {
            "number": number,
            "name": row["Name"],
            "metres": row["Metres"],
            "classifications": classifications,
            "region": region if isinstance(region, str) else "",
        }

        keys = {normalize(row["Name"])}
        alias_match = BRACKET_ALIAS_RE.match(row["Name"])
        if alias_match:
            keys.add(normalize(alias_match.group(1)))
            keys.add(normalize(alias_match.group(2)))

        # Compound DoBIH names like "Lochnagar - Cac Carn Beag" or "Buachaille
        # Etive Mor - Stob na Broige" get mentioned by either half in the
        # wild (the parent mountain's popular name, or just the specific top).
        compound_match = COMPOUND_NAME_RE.match(row["Name"])
        if compound_match:
            keys.add(normalize(compound_match.group(1)))
            keys.add(normalize(compound_match.group(2)))

        for key in keys:
            by_name.setdefault(key, []).append(hill)

    munro_norm_names = [
        k for k, hills in by_name.items() if any("M" in h["classifications"] for h in hills)
    ]
    return by_name, list(by_name.keys()), munro_norm_names


def _direct_lookup(text, hill_index, all_norm_names, munro_norm_names, allow_loose_munro_fuzzy=False):
    """Exact then fuzzy match of a single candidate string. No disambiguation."""
    key = normalize(text)
    candidates = hill_index.get(key)
    if not candidates:
        close = get_close_matches(key, all_norm_names, n=1, cutoff=0.92)
        if close:
            candidates = hill_index[close[0]]
    if not candidates and allow_loose_munro_fuzzy:
        # Last-resort wider match (handles Gaelic transliteration drift like
        # "achallader" vs "achaladair"), restricted to Munro names only so a
        # loose guess can't misfire onto an unrelated non-Munro hill.
        close = get_close_matches(key, munro_norm_names, n=1, cutoff=0.85)
        if close:
            candidates = hill_index[close[0]]
    return candidates


def _candidates_for_fragment(text, hill_index, all_norm_names, munro_norm_names):
    """Try every single-fragment variant: as-is; a trailing "(...)" aside's
    content (DoBIH's primary name is sometimes the English/alt name the
    curator parenthesised, e.g. "Bod an Deamhain (The Devil's Point)"); with
    the aside stripped instead; progressively dropping trailing words
    (handles "Name again" style repeat-visit notes).
    """
    text = text.strip()
    if not text:
        return None

    candidates = _direct_lookup(text, hill_index, all_norm_names, munro_norm_names)
    if candidates:
        return candidates

    aside_match = re.search(r"\(([^)]*)\)", text)
    if aside_match:
        candidates = _direct_lookup(aside_match.group(1), hill_index, all_norm_names, munro_norm_names)
        if candidates:
            return candidates

    stripped = re.sub(r"\s*\([^)]*\)\s*", " ", text).strip()
    stripped = re.sub(r"\s+", " ", stripped)
    if stripped and stripped != text:
        candidates = _direct_lookup(stripped, hill_index, all_norm_names, munro_norm_names)
        if candidates:
            return candidates

    words = stripped.split()
    for n_drop in (1, 2):
        if len(words) - n_drop < 1:
            break
        trimmed = " ".join(words[: len(words) - n_drop])
        candidates = _direct_lookup(trimmed, hill_index, all_norm_names, munro_norm_names)
        if candidates:
            return candidates

    return None


def find_candidates(raw_text, hill_index, all_norm_names, munro_norm_names):
    """Resolve a free-text summit mention to a list of candidate hill rows.

    Tries every fallback in `_candidates_for_fragment` against the text as a
    whole, then against each ". "-delimited sentence fragment individually
    (handles both "Name. commentary" and "commentary. Name" - the hill name
    can be in either the leading or a trailing clause), falling back to a
    loose Munro-only fuzzy match as a last resort for spelling drift.
    """
    text = raw_text.strip()

    candidates = _candidates_for_fragment(text, hill_index, all_norm_names, munro_norm_names)
    if candidates:
        return candidates

    if ". " in text or text.endswith("."):
        for fragment in re.split(r"\.\s*", text):
            candidates = _candidates_for_fragment(fragment, hill_index, all_norm_names, munro_norm_names)
            if candidates:
                return candidates

    return _direct_lookup(text, hill_index, all_norm_names, munro_norm_names, allow_loose_munro_fuzzy=True)


def disambiguate(candidates, height_m, context_text, sibling_hills):
    """Pick one hill from several sharing a bare name.

    Priority: tagged height, if given, matched against the *full* candidate
    set (a real height from the Strava tag is strong enough evidence to
    trust over any classification assumption - e.g. it correctly rules out
    a same-named Munro if the tagged height clearly belongs to some
    unrelated smaller hill instead).

    Without a height we have much weaker evidence, so before going further
    we narrow to Munro-classified candidates if any exist: a bare name like
    "Meall Buidhe" or "Carn Dearg" matches every DoBIH hill with that name
    regardless of classification - dozens, for common names, most of them
    obscure sub-1000ft bumps nowhere near the Munro in question - and every
    summit mention reaching this function already comes from Munro-round
    bookkeeping, so an unresolved guess should land on *a* Munro rather than
    on some unrelated hillock that happens to share the name.

    Then: region shared with other hills already resolved in the same
    activity -> region name appearing as text in the activity's own
    title/description -> unresolved (first remaining candidate, guessed).
    """
    if len(candidates) == 1:
        return candidates[0], True

    if height_m is not None:
        return min(candidates, key=lambda h: abs(h["metres"] - height_m)), True

    munro_candidates = [c for c in candidates if "M" in c["classifications"]]
    if munro_candidates:
        candidates = munro_candidates
    if len(candidates) == 1:
        return candidates[0], True

    sibling_regions = {h["region"] for h in sibling_hills if h["region"]}
    region_matches = [c for c in candidates if c["region"] in sibling_regions]
    if len(region_matches) == 1:
        return region_matches[0], True

    context_norm = normalize(context_text)
    text_matches = []
    for c in candidates:
        if not c["region"]:
            continue
        region_words = [w for w in re.split(r"[^a-z']+", c["region"].lower()) if len(w) > 3]
        if any(w in context_norm for w in region_words):
            text_matches.append(c)
    if len(text_matches) == 1:
        return text_matches[0], True

    return candidates[0], False  # unresolved guess - flagged by caller


def parse_emoji_format(description):
    return [(name.strip(), float(h.replace(",", ""))) for name, h in EMOJI_SUMMIT_RE.findall(description)]


def parse_hash_numbered(description):
    text = ERA_NOTE_RE.sub("", description)
    parts = re.split(r"#\d+\s*", text)
    results = []
    for chunk in parts[1:]:
        chunk = chunk.strip()
        if not chunk or chunk.startswith("("):
            continue
        m = re.match(r"^(.*?)\s*\((\d+(?:\.\d+)?)\s*m\)", chunk)
        if m:
            results.append((m.group(1).strip(), float(m.group(2))))
        else:
            results.append((chunk, None))
    return results


def parse_title_only(description):
    text = ERA_NOTE_RE.sub("", description).strip()
    text = re.sub(r",\s*$", "", text)
    tokens = re.split(r",\s*|\s+and\s+", text)
    results = []
    for tok in tokens:
        tok = re.sub(r"^and\s+", "", tok.strip(), flags=re.I).strip()
        if tok:
            results.append((tok, None))
    return results


def parse_activity(activity, hill_index, all_norm_names, munro_norm_names):
    """Returns (matched_summits, unmatched_mentions, ambiguous_mentions).

    Resolution runs in two passes so disambiguation-by-region doesn't depend
    on the order hills happen to be listed in: pass 1 resolves everything
    that's unambiguous or has a height to disambiguate by, and pass 2 then
    resolves the rest using the *full* set of sibling regions gathered in
    pass 1, not just earlier-listed ones.
    """
    description = activity.get("description") or ""

    if activity["id"] in MANUAL_SUMMIT_OVERRIDES:
        candidates_raw = [(name, None) for name in MANUAL_SUMMIT_OVERRIDES[activity["id"]]]
    elif "⛰️" in description:
        candidates_raw = parse_emoji_format(description)
    elif HASH_MARKER_RE.search(description):
        candidates_raw = parse_hash_numbered(description)
    elif TITLE_ONLY_RE.search(description):
        candidates_raw = parse_title_only(description)
    else:
        candidates_raw = []

    context_text = activity.get("name", "") + " " + description

    pending = []  # [raw_name, height_m, candidates]
    unmatched = []
    for raw_name, height_m in candidates_raw:
        candidates = find_candidates(raw_name, hill_index, all_norm_names, munro_norm_names)
        if not candidates:
            unmatched.append({"raw_name": raw_name, "tagged_height_m": height_m})
            continue
        pending.append([raw_name, height_m, candidates])

    resolved = [None] * len(pending)  # hill row per pending entry, once resolved
    is_flagged = [False] * len(pending)  # True if disambiguate() had to guess

    def sibling_hills():
        return [h for h in resolved if h is not None]

    easy = [i for i, (_, height_m, candidates) in enumerate(pending) if len(candidates) == 1 or height_m is not None]
    hard = [i for i in range(len(pending)) if i not in easy]

    for i in easy:
        _, height_m, candidates = pending[i]
        resolved[i], _ = disambiguate(candidates, height_m, context_text, sibling_hills())

    for i in hard:
        raw_name, height_m, candidates = pending[i]
        hill, ok = disambiguate(candidates, height_m, context_text, sibling_hills())
        resolved[i] = hill
        is_flagged[i] = not ok

    matched, ambiguous = [], []
    for i, (raw_name, height_m, candidates) in enumerate(pending):
        hill = resolved[i]
        matched.append(
            {
                "name": hill["name"],
                "raw_name": raw_name,
                "height_m": hill["metres"],
                "is_munro": "M" in hill["classifications"],
                "classifications": hill["classifications"],
                "dobih_number": hill["number"],
                "ambiguous": is_flagged[i],
            }
        )
        if is_flagged[i]:
            ambiguous.append(
                {
                    "raw_name": raw_name,
                    "tagged_height_m": height_m,
                    "candidate_names": "|".join(f"{c['name']} ({c['metres']}m, {c['region']})" for c in candidates),
                    "guessed": f"{hill['name']} ({hill['metres']}m)",
                }
            )

    return matched, unmatched, ambiguous


def main():
    hill_index, all_norm_names, munro_norm_names = load_hill_index()

    activities = []
    with open(ACTIVITIES_JSONL) as f:
        for line in f:
            line = line.strip()
            if line:
                activities.append(json.loads(line))

    munro_activities = []
    summit_rows = []
    unmatched_rows = []
    ambiguous_rows = []
    unparsed_activities = []

    for activity in activities:
        matched, unmatched, ambiguous = parse_activity(activity, hill_index, all_norm_names, munro_norm_names)

        description = activity.get("description") or ""
        has_known_format = (
            activity["id"] in MANUAL_SUMMIT_OVERRIDES
            or "⛰️" in description
            or HASH_MARKER_RE.search(description)
            or TITLE_ONLY_RE.search(description)
        )
        if not has_known_format and not matched:
            unparsed_activities.append({"activity_id": activity["id"], "activity_name": activity["name"], "date": activity["date"]})

        for u in unmatched:
            unmatched_rows.append({"activity_id": activity["id"], "activity_name": activity["name"], "date": activity["date"], **u})
        for a in ambiguous:
            ambiguous_rows.append({"activity_id": activity["id"], "activity_name": activity["name"], "date": activity["date"], **a})

        munro_summits = [s for s in matched if s["is_munro"]]
        if not munro_summits:
            continue

        enriched = dict(activity)
        enriched["summits"] = matched
        enriched["munro_count"] = len(munro_summits)
        munro_activities.append(enriched)

        for s in matched:
            summit_rows.append(
                {
                    "activity_id": activity["id"],
                    "activity_name": activity["name"],
                    "date": activity["date"],
                    "sport_type": activity["sport_type"],
                    "distance_m": activity["distance_m"],
                    "elevation_gain_m": activity["elevation_gain_m"],
                    "summit_name": s["name"],
                    "height_m": s["height_m"],
                    "is_munro": s["is_munro"],
                    "classifications": "|".join(s["classifications"]),
                    "dobih_number": s["dobih_number"],
                    "ambiguous": s["ambiguous"],
                }
            )

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    with open(OUT_DIR / "munro_activities.jsonl", "w") as f:
        for a in munro_activities:
            f.write(json.dumps(a, ensure_ascii=False) + "\n")

    with open(OUT_DIR / "munro_summits.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(summit_rows[0].keys()))
        writer.writeheader()
        writer.writerows(summit_rows)

    with open(OUT_DIR / "unmatched_summits.csv", "w", newline="") as f:
        if unmatched_rows:
            writer = csv.DictWriter(f, fieldnames=list(unmatched_rows[0].keys()))
            writer.writeheader()
            writer.writerows(unmatched_rows)

    with open(OUT_DIR / "ambiguous_summits.csv", "w", newline="") as f:
        if ambiguous_rows:
            writer = csv.DictWriter(f, fieldnames=list(ambiguous_rows[0].keys()))
            writer.writeheader()
            writer.writerows(ambiguous_rows)

    unique_munros = {s["dobih_number"] for row in munro_activities for s in row["summits"] if s["is_munro"]}
    all_hills = {h["number"]: h for hills in hill_index.values() for h in hills}
    total_munros = sum(1 for h in all_hills.values() if "M" in h["classifications"])

    print(f"Activities read:            {len(activities)}")
    print(f"Activities with a Munro:    {len(munro_activities)}")
    print(f"Munro summit tags (rows):   {sum(a['munro_count'] for a in munro_activities)}")
    print(f"Unique Munros bagged:       {len(unique_munros)} / {total_munros}")
    print(f"Unmatched tagged summits:   {len(unmatched_rows)} (see unmatched_summits.csv)")
    print(f"Ambiguous (guessed) summits:{len(ambiguous_rows):>4} (see ambiguous_summits.csv)")
    print(f"Activities with no known tag format: {len(unparsed_activities)}")
    for u in unparsed_activities:
        print(f"   - {u['activity_id']} {u['date']} {u['activity_name']!r}")


if __name__ == "__main__":
    main()
