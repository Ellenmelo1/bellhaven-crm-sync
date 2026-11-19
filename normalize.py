# ============================================================
# NORMALIZE - clean text so two versions can be compared
# e.g. "1800 North Blanchard Street." -> "1800 n blanchard st"
# ============================================================

import re

# Abbreviation map: every long form becomes the short form
ABBREVIATIONS = {
    "street": "st", "avenue": "ave", "road": "rd", "drive": "dr",
    "boulevard": "blvd", "lane": "ln", "court": "ct", "place": "pl",
    "parkway": "pkwy", "highway": "hwy", "circle": "cir", "terrace": "ter",
    "north": "n", "south": "s", "east": "e", "west": "w",
    "northwest": "nw", "northeast": "ne", "southwest": "sw", "southeast": "se",
    "pk": "pike",                         # "Wilmington Pk" = "Wilmington Pike"
    "suite": "ste",
}


def normalize_text(text):
    text = (text or "").lower()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9 ]", " ", text)   # drop punctuation
    return " ".join(text.split())             # collapse extra spaces


def normalize_street(street):
    words = normalize_text(street).split()
    return " ".join(ABBREVIATIONS.get(w, w) for w in words)


def normalize_zip(zip_code):
    return re.sub(r"\D", "", zip_code or "")[:5]   # first 5 digits only
