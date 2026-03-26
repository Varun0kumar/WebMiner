import asyncio
import json
import random
import requests
import argparse
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from process_data import process_data

# ---------------- CLI INPUT ---------------- #
parser = argparse.ArgumentParser(description="Advanced Distributed Web Scraper")
parser.add_argument("--url", required=True, help="Target website URL")
parser.add_argument("--proxies", help="Optional proxy file (one per line)")
args = parser.parse_args()

BASE_URL = args.url.rstrip("/")
SITEMAP_URL = urljoin(BASE_URL, "/sitemap.xml")

# ---------------- DOMAIN NAME ---------------- #
def get_domain_name(url):
    domain = urlparse(url).netloc.replace("www.", "")
    return domain.split(".")[0]

domain_name = get_domain_name(BASE_URL)
RAW_OUTPUT_FILE = f"{domain_name}_raw_data.json"

# ---------------- CONFIG ---------------- #
CONCURRENCY = 8
DELAY_RANGE = (1, 2)
MAX_RETRIES = 3

# ---------------- LOAD PROXIES ---------------- #
def load_proxies(file_path):
    try:
        with open(file_path, "r") as f:
            proxies = [line.strip() for line in f if line.strip()]
        print(f"✅ Loaded {len(proxies)} proxies")
        return proxies
    except:
        print("⚠️  Proxy loading failed")
        return []

PROXIES = load_proxies(args.proxies) if args.proxies else []

def get_random_proxy():
    return random.choice(PROXIES) if PROXIES else None

# ---------------- USER AGENTS ---------------- #
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    "Mozilla/5.0 (X11; Linux x86_64)"
]

# ---------------- SAFE REQUEST ---------------- #
def safe_request(url):
    for attempt in range(MAX_RETRIES):
        try:
            proxy = get_random_proxy()

            res = requests.get(
                url,
                timeout=10,
                headers={"User-Agent": random.choice(USER_AGENTS)},
                proxies={"http": proxy, "https": proxy} if proxy else None
            )

            if res.status_code == 200:
                return res
            else:
                print(f"⚠️  Status {res.status_code} → {url}")

        except Exception as e:
            print(f"❌ Request error (attempt {attempt+1}) → {url} | {e}")

    print(f"🚫 Failed completely → {url}")
    return None

# ---------------- WORDPRESS CHECK ---------------- #
def is_wordpress(base_url):
    try:
        res = safe_request(urljoin(base_url, "/wp-json/"))
        return res is not None
    except:
        return False

# ---------------- COMMON WP ENDPOINTS (Fallback) ---------------- #
def get_common_wp_endpoints(base_url):
    return [
        urljoin(base_url, "/wp-json/wp/v2/posts"),
        urljoin(base_url, "/wp-json/wp/v2/pages"),
        urljoin(base_url, "/wp-json/wp/v2/media"),
        urljoin(base_url, "/wp-json/wp/v2/categories"),
        urljoin(base_url, "/wp-json/wp/v2/tags"),
        urljoin(base_url, "/wp-json/wp/v2/users"),
        urljoin(base_url, "/wp-json/wp/v2/comments"),
        urljoin(base_url, "/wp-json/wp/v2/types"),
        urljoin(base_url, "/wp-json/wp/v2/statuses"),
        urljoin(base_url, "/wp-json/wp/v2/taxonomies")
    ]

# ---------------- DISCOVER WP ENDPOINTS ---------------- #
def discover_wp_endpoints(base_url):
    endpoints = []

    res = safe_request(urljoin(base_url, "/wp-json"))

    if not res:
        print("⚠️  WP discovery failed, using common endpoints")
        return get_common_wp_endpoints(base_url)

    try:
        data = res.json()
        routes = data.get("routes", {})

        for route in routes:
            # ❗ Skip regex/dynamic routes
            if "/wp/v2/" in route and "(" not in route and "?" not in route:
                endpoints.append(urljoin(base_url, route))

    except Exception as e:
        print(f"❌ WP parsing error → fallback used | {e}")
        return get_common_wp_endpoints(base_url)

    print(f"✅ Discovered {len(endpoints)} WP endpoints")

    # ✅ ADD THIS BLOCK HERE (AFTER DISCOVERY)
    important_keywords = ["posts", "pages", "media", "categories", "tags"]

    filtered = []
    for ep in endpoints:
        if any(k in ep for k in important_keywords):
            filtered.append(ep)

    print(f"✅ Filtered to {len(filtered)} useful endpoints")

    return filtered[:10]  # limit endpoints (important for speed)

# ---------------- FETCH WP DATA ---------------- #
def get_all_wp_data(base_url):
    endpoints = discover_wp_endpoints(base_url)
    data = []

    for url in endpoints:
        page = 1

        while True:
            try:
                res = safe_request(f"{url}?per_page=100&page={page}")
                if not res:
                    break

                items = res.json()

                if not isinstance(items, list) or not items:
                    break

                for item in items:
                    data.append({
                        "url": item.get("link", url),
                        "content": item.get("content", {}).get("rendered", "")
                    })

                page += 1

            except Exception as e:
                print(f"⚠️  Skipped (not accessible) → {url}")
                break

    return data

# ---------------- SITEMAP ---------------- #
def get_all_urls_from_sitemap(sitemap_url):
    urls = []

    res = safe_request(sitemap_url)
    if not res:
        return []

    soup = BeautifulSoup(res.text, "xml")

    for sm in soup.find_all("sitemap"):
        loc = sm.find("loc").text
        urls.extend(get_all_urls_from_sitemap(loc))

    for loc in soup.find_all("loc"):
        urls.append(loc.text)

    return list(set(urls))

# ---------------- FALLBACK LINK EXTRACTION ---------------- #
async def extract_links(page, base_url):
    try:
        anchors = await page.eval_on_selector_all(
            "a",
            "elements => elements.map(el => el.href)"
        )

        return list(set([link for link in anchors if link and base_url in link]))

    except Exception as e:
        print(f"⚠️  Link extraction failed: {e}")
        return []

# ---------------- CLEAN TEXT ---------------- #
def clean_text(html):
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style", "nav", "footer", "header", "form"]):
        tag.decompose()

    text = soup.get_text("\n", strip=True)

    # Remove cookie/privacy junk
    unwanted_phrases = [
        "We value your privacy",
        "Accept All",
        "Reject All",
        "cookies",
        "Consent Preferences"
    ]

    for phrase in unwanted_phrases:
        text = text.replace(phrase, "")

    return text

# ---------------- PLAYWRIGHT SCRAPER ---------------- #
async def scrape_page(page, url):
    for attempt in range(MAX_RETRIES):
        try:
            await page.goto(url, timeout=30000, wait_until="domcontentloaded")

            # small delay instead of networkidle (faster)
            await asyncio.sleep(1.5)

            # scroll for lazy content
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(1.5)

            html = await page.content()
            return clean_text(html)

        except Exception as e:
            print(f"⚠️  Retry {attempt+1} → {url}")

    print(f"🚫 Skipped (failed) → {url}")
    return None

# ---------------- WORKER ---------------- #
async def worker(name, browser, queue, results):
    proxy = get_random_proxy()

    context = await browser.new_context(
        user_agent=random.choice(USER_AGENTS),
        viewport={"width": 1280, "height": 800},
        proxy={"server": proxy} if proxy else None
    )

    page = await context.new_page()

    while queue:
        url = queue.pop(0)

        print(f"[{name}] → {url}")

        try:
            data = await scrape_page(page, url)
            if data:
                results.append({"url": url, "content": data})

        except Exception as e:
            print(f"❌ Worker error → {url} | {e}")

        await asyncio.sleep(random.uniform(*DELAY_RANGE))

    await context.close()

# ---------------- FILTER ---------------- #
def is_valid_url(url):
    invalid_ext = (".png", ".jpg", ".jpeg", ".svg", ".gif",".pdf", ".zip", ".xml")
    invalid_kw = ["wp-content", "cdn", "staging"]

    return not (url.endswith(invalid_ext) or any(k in url for k in invalid_kw))

# ---------------- MAIN ---------------- #
async def main():
    print(f"\n🚀 Target: {BASE_URL}\n")

    # STEP 1: Sitemap
    print("🔍 Fetching sitemap...")
    urls = get_all_urls_from_sitemap(SITEMAP_URL)

    # FALLBACK if sitemap fails
    if not urls:
        print("⚠️  Sitemap failed → using fallback crawling")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            try:
                await page.goto(BASE_URL)
                urls = await extract_links(page, BASE_URL)
                print(f"✅ Fallback found {len(urls)} URLs")
            except Exception as e:
                print(f"❌ Fallback failed → {e}")

            await browser.close()
    else:
        print(f"✅ {len(urls)} URLs found")

    # STEP 2: WordPress
    results = []

    if is_wordpress(BASE_URL):
        print("\n🔍 WordPress detected → fetching data...")
        wp_data = get_all_wp_data(BASE_URL)
        print(f"✅ {len(wp_data)} WP entries")
        results.extend(wp_data)
    else:
        print("⚠️  Not a WordPress site")

    # STEP 3: Scraping
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        queue = [u for u in urls if is_valid_url(u)]

        tasks = [
            worker(f"W{i}", browser, queue, results)
            for i in range(CONCURRENCY)
        ]

        await asyncio.gather(*tasks)
        await browser.close()

    # STEP 4: Save
    try:
        with open(RAW_OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

        print(f"\n✅ Saved {len(results)} records → {RAW_OUTPUT_FILE}")

    except Exception as e:
        print(f"❌ Save error: {e}")

    # STEP 5: Processing
    try:
        process_data(domain_name, RAW_OUTPUT_FILE)
    except Exception as e:
        print(f"❌ Processing failed: {e}")

# ---------------- RUN ---------------- #
if __name__ == "__main__":
    asyncio.run(main())