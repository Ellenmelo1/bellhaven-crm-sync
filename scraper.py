# ============================================================
# SCRAPER - reads the Bellhaven website and returns every location
# ============================================================
# The website is the SOURCE OF TRUTH for which locations exist today.
#   1) Collect every /communities/<slug> link from the homepage AND
#      every page of the directory (the new Findlay location is only
#      linked from the homepage, not from the directory).
#   2) Visit each link and extract name, address and care offerings.
# ============================================================

import re
import json
import requests
from bs4 import BeautifulSoup
from config import BASE_URL

# Field labels shown on each community page
LABELS = ["Address", "Care Offerings", "Administrator", "Phone"]
COMMUNITY_LINK = re.compile(r"/communities/[\w-]+")


def fetch_html(url):
    """Download a page and return it parsed by BeautifulSoup."""
    response = requests.get(url, timeout=30)
    response.raise_for_status()          # stop on 404 / 500 etc.
    return BeautifulSoup(response.text, "html.parser")


def community_links_on(page):
    """Return every community detail link found on a parsed page."""
    links = set()
    for a in page.find_all("a", href=True):
        href = a["href"].replace(BASE_URL, "")
        if COMMUNITY_LINK.fullmatch(href):
            links.add(href)
    return links


def find_location_links():
    """Step 1: collect all location links (directory pages + homepage)."""
    links = set()                        # a set never stores duplicates

    page_number = 1
    while page_number <= 20:             # walk ?page=1, 2, 3... until empty
        found = community_links_on(fetch_html(f"{BASE_URL}/communities?page={page_number}"))
        if not found:
            break
        links |= found
        page_number += 1

    links |= community_links_on(fetch_html(BASE_URL + "/"))   # homepage-only links
    return sorted(links)


def read_location(path):
    """Step 2: open ONE location page and extract its fields."""
    page = fetch_html(BASE_URL + path)
    name = page.find("h1").get_text(strip=True)

    # Turn the page into lines of text and read what follows each label
    lines = [l.strip() for l in page.get_text("\n").split("\n") if l.strip()]

    def values_after(label):
        if label not in lines:
            return []
        i = lines.index(label) + 1
        values = []
        while i < len(lines) and lines[i] not in LABELS and not lines[i].startswith("←") \
                and "Back to" not in lines[i] and "©" not in lines[i]:
            values.append(lines[i])
            i += 1
        return values

    full_address = ", ".join(values_after("Address"))
    # Split "1800 N Blanchard St, Findlay, OH 45840" into street / city / state / zip
    m = re.search(r"^(.*?),\s*([^,]+?),\s*([A-Z]{2})\s*(\d{5})", full_address)
    street, city, state, zip_code = m.groups() if m else (full_address, "", "", "")

    return {
        "slug": path.split("/")[-1],
        "name": name,
        "street": street.strip(),
        "city": city.strip(),
        "state": state,
        "zip": zip_code,
        "care_offerings": values_after("Care Offerings"),
        "phone": " ".join(values_after("Phone")),
        "url": BASE_URL + path,
    }


def scrape_website():
    links = find_location_links()
    print(f"   found {len(links)} location links")
    return [read_location(link) for link in links]


if __name__ == "__main__":
    # Run on its own: python scraper.py
    locations = scrape_website()
    json.dump(locations, open("data/site_locations.json", "w"), indent=2)
    missing_address = [loc["name"] for loc in locations if not loc["zip"]]
    print(f"   saved {len(locations)} locations to data/site_locations.json")
    if missing_address:
        print(f"   WARNING - incomplete address: {missing_address}")
