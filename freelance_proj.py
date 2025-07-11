import os
import re
import argparse
import requests
import logging
from bs4 import BeautifulSoup, Comment
from urllib.parse import urljoin, urlparse, quote
from pathlib import Path
import time
import xml.etree.ElementTree as ET
import shutil

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    )
}

TAGS_RES_TYPES = {
    "img": "im_",
    "script": "js_",
    "link": "cs_",
    "source": "id_",
    "video": "id_",
    "audio": "id_",
    "iframe": "id_"
}

SKIP_DOMAINS = [
    "api.", "ssc.api.bbc.com", "scorecardresearch", "doubleclick.net", "chartbeat.com",
    "google-analytics.com", "googletagmanager.com", "googlesyndication.com", "googletagservices.com"
]

def setup_logging():
    logging.basicConfig(format='%(levelname)s: %(message)s', level=logging.INFO)

def is_skip_resource(url):
    for pattern in SKIP_DOMAINS:
        if pattern in url:
            return True
    return False

def page_local_path(url, base_url, output_dir):
    parsed = urlparse(url)
    path = parsed.path
    if not path or path == "/":
        path = "index.html"
    else:
        if path.endswith("/"):
            path += "index.html"
        elif "." not in path.split("/")[-1]:
            path = path.rstrip("/") + "/index.html"
        path = path.lstrip("/")
    return os.path.join(output_dir, path)

def resource_local_path(orig_url, base_url, output_dir):
    parsed = urlparse(orig_url)
    path = parsed.path
    if not path:
        path = "resource"
    path = path.lstrip("/")
    if parsed.query:
        path += "_" + re.sub(r'\W+', '', parsed.query)
    return os.path.join(output_dir, "assets", path)

def archive_resource_url(orig_url, timestamp, res_type="im_"):
    if orig_url.startswith("data:"):
        return orig_url
    if re.match(r"^https?://web\.archive\.org/web/\d{14,}[a-z]*_?/.+", orig_url):
        return orig_url
    return f"https://web.archive.org/web/{timestamp}{res_type}/{orig_url}"

def download_file(session, urls_by_snap, out_path, retries=4):
    for archive_url, timestamp in urls_by_snap:
        if archive_url.startswith("data:") or is_skip_resource(archive_url):
            logging.debug(f"SKIP: {archive_url}")
            return False
        attempt = 0
        backoff = 5
        while attempt < retries:
            try:
                r = session.get(archive_url, headers=HEADERS, timeout=30, stream=True)
                if r.status_code == 404:
                    break
                r.raise_for_status()
                out_path.parent.mkdir(parents=True, exist_ok=True)
                with open(out_path, "wb") as f:
                    for chunk in r.iter_content(4096):
                        f.write(chunk)
                return True
            except Exception as e:
                if hasattr(e, "errno") and e.errno == 111 or "Errno 111" in str(e):
                    logging.warning(f"[CONN REFUSED, RETRY] {archive_url} -> {e} | sleep {backoff}s")
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 60)
                    attempt += 1
                    continue
                else:
                    logging.warning(f"FAILED: {archive_url} ({attempt+1}/{retries}) -> {e}")
                    time.sleep(2)
            attempt += 1
    logging.error(f"[SKIPPED] {archive_url} after {retries} retries")
    return False

def remove_archive_junk(soup):
    for s in soup.find_all("script"):
        src = s.get("src", "") if hasattr(s, "get") else ""
        txt = s.string or ""
        if (
            "web.archive.org" in src
            or "archive.org" in src
            or "web-static.archive.org" in src
            or "Wayback" in txt
            or "wayback" in txt
            or "wombat.js" in src
            or "banner-styles" in src
            or "ruffle.js" in src
            or "analytics.js" in src
            or "google-analytics.com" in src
        ):
            s.decompose()
    for l in soup.find_all("link", href=True):
        href = l.get("href", "")
        if "web.archive.org" in href or "archive.org" in href or "web-static.archive.org" in href:
            l.decompose()
    for style in soup.find_all("style"):
        if "wm-toolbar" in style.text or "wm-ipp" in style.text:
            style.decompose()
    for div in soup.find_all(attrs={"id": True}):
        try:
            div_id = div.get("id", "")
            if div_id and "wm-ipp" in div_id:
                div.decompose()
        except Exception:
            continue
    for iframe in soup.find_all("iframe"):
        src = iframe.get("src", "")
        if "web.archive.org" in src or "archive.org" in src:
            iframe.decompose()
    for meta in soup.find_all("meta", attrs={"content": True}):
        content = meta.get("content", "")
        if "web.archive.org" in content or "archive.org" in content:
            meta.decompose()
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        if "WAYBACK TOOLBAR" in comment or "archive.org" in comment or "ARCHIVE" in comment:
            comment.extract()
    for ns in soup.find_all("noscript"):
        ns.decompose()
    return soup

def rewrite_html(soup, urlmap, current_url, base_url, base_netloc, external_mode="original"):
    tags_attrs = [
        ("a", "href"), ("img", "src"), ("script", "src"), ("link", "href"),
        ("source", "src"), ("video", "src"), ("audio", "src"), ("iframe", "src")
    ]
    for tag, attr in tags_attrs:
        for t in soup.find_all(tag):
            if not t.has_attr(attr):
                continue
            orig_link = t[attr]
            link_real = orig_link

            if orig_link.startswith("/web/"):
                m = re.match(r"/web/\d+[a-zA-Z_]*/(https?://.+)", orig_link)
                if m:
                    link_real = m.group(1)
            elif "web.archive.org" in orig_link:
                m = re.match(r"https?://web\.archive\.org/web/\d+[a-zA-Z_]*/(https?://.+)", orig_link)
                if m:
                    link_real = m.group(1)
            else:
                link_real = urljoin(base_url, orig_link)

            parsed_link = urlparse(link_real)
            if parsed_link.netloc == base_netloc and link_real in urlmap:
                relpath = os.path.relpath(urlmap[link_real], os.path.dirname(urlmap[current_url]))
                t[attr] = relpath.replace("\\", "/")
            else:
                if tag == "a" and attr == "href":
                    t[attr] = link_real if external_mode == "original" else orig_link
                else:
                    t[attr] = orig_link
    return soup

def clean_wayback_assets(output_dir):
    static_dir = os.path.join(output_dir, "assets", "_static")
    if os.path.isdir(static_dir):
        shutil.rmtree(static_dir)
        logging.info(f"Удалена папка Wayback: {static_dir}")

def crawl_multi_snapshots(snapshots, output_dir, recursive=True, external_mode="original"):
    base_url = snapshots[0][1]
    base_netloc = urlparse(base_url).netloc
    session = requests.Session()
    urlmap = {}
    seen = set()
    queue = [base_url]
    localpaths = []

    for ts, base_url_s in snapshots:
        pass

    while queue:
        current = queue.pop(0)
        if current in seen:
            continue
        seen.add(current)
        page_content = None
        used_ts = None
        for ts, base_url_s in snapshots:
            wb_url = f"https://web.archive.org/web/{ts}/{current}"
            try:
                r = session.get(wb_url, headers=HEADERS, timeout=20)
                if r.status_code == 200 and r.text.strip():
                    page_content = r.text
                    used_ts = ts
                    break
            except Exception:
                continue
        if not page_content:
            logging.warning(f"[NOT FOUND in any snapshot] {current}")
            continue

        soup = BeautifulSoup(page_content, "lxml")
        local_path = page_local_path(current, base_url, output_dir)
        urlmap[current] = local_path
        localpaths.append(current)
        os.makedirs(os.path.dirname(local_path), exist_ok=True)

        # --- PATCHED SECTION: правильна робота з архівними шляхами ---
        for tag, res_type in TAGS_RES_TYPES.items():
            for t in soup.find_all(tag):
                link = t.get("src") if tag != "link" else t.get("href")
                if not link or link.startswith("data:") or is_skip_resource(link):
                    continue

                if link.startswith("/web/"):
                    # Це вже архівний шлях — качаємо саме так
                    archive_url = "https://web.archive.org" + link
                    archive_candidates = [(archive_url, None)]
                    # Витягуємо оригінальний url для побудови локального шляху
                    m = re.match(r"/web/\d{14,}[a-z_]*_*/(https?://.+)", link)
                    if m:
                        link_full = m.group(1)
                    else:
                        link_full = link  # fallback
                else:
                    parsed = urlparse(link)
                    if not parsed.netloc:
                        link_full = urljoin(base_url, link)
                    else:
                        link_full = link
                    archive_candidates = []
                    for ts, _ in snapshots:
                        archive_url = archive_resource_url(link_full, ts, res_type)
                        archive_candidates.append((archive_url, ts))

                local_res = resource_local_path(link_full, base_url, output_dir)
                urlmap[link_full] = local_res
                if not os.path.exists(local_res):
                    download_file(session, archive_candidates, Path(local_res))

        soup = rewrite_html(soup, urlmap, current, base_url, base_netloc, external_mode=external_mode)
        soup = remove_archive_junk(soup)
        with open(local_path, "w", encoding="utf-8") as f:
            f.write(str(soup))

        if recursive:
            for tag in soup.find_all("a", href=True):
                href = tag["href"]
                if href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
                    continue
                next_url = href
                if href.startswith("/web/"):
                    m = re.match(r"/web/\d+[a-zA-Z_]*/(https?://.+)", href)
                    if m:
                        next_url = m.group(1)
                elif "web.archive.org" in href:
                    m = re.match(r"https?://web\.archive\.org/web/\d+[a-zA-Z_]*/(https?://.+)", href)
                    if m:
                        next_url = m.group(1)
                else:
                    next_url = urljoin(base_url, href)
                if urlparse(next_url).netloc == base_netloc and next_url not in seen and next_url not in queue:
                    queue.append(next_url)
    generate_sitemap(localpaths, os.path.join(output_dir, "sitemap.xml"))
    clean_wayback_assets(output_dir)

def generate_sitemap(localpaths, output):
    urls = set(localpaths)
    urlset = ET.Element('urlset', xmlns="http://www.sitemaps.org/schemas/sitemap/0.9")
    for url in urls:
        url_el = ET.SubElement(urlset, 'url')
        loc = ET.SubElement(url_el, 'loc')
        loc.text = url
    tree = ET.ElementTree(urlset)
    tree.write(output, encoding='utf-8', xml_declaration=True)

def download_all_images_via_cdx(site, timestamp, output_dir="images"):
    base_api = "http://web.archive.org/cdx/search/cdx"
    params = {
        "url": site + "*",
        "matchType": "prefix",
        "from": timestamp,
        "to": timestamp,
        "output": "json"
    }
    res = requests.get(base_api, params=params)
    data = res.json()

    records = [row for row in data[1:] if len(row) > 3]
    image_urls = []
    for row in records:
        original = row[2]
        mime = row[3]
        status = row[4]
        if status != "200":
            print(f"Недоступно: {original} (status {status})")
            continue
        if mime.startswith("image/"):
            image_urls.append(original)

    os.makedirs(output_dir, exist_ok=True)

    for img_url in image_urls:
        wayback_url = f"https://web.archive.org/web/{timestamp}id_/{quote(img_url, safe=':/')}"
        try:
            resp = requests.get(wayback_url, timeout=10)
            if resp.status_code == 200:
                filename = os.path.basename(img_url)
                with open(os.path.join(output_dir, filename), "wb") as f:
                    f.write(resp.content)
            else:
                print(f"Файл {img_url} повернув {resp.status_code}")
        except Exception as e:
            print(f"Помилка при завантаженні {img_url}: {e}")

def save_all_archived_pages(domain, timestamp, output_dir="pages_from_cdx"):
    base_api = "http://web.archive.org/cdx/search/cdx"
    params = {
        "url": domain + "/*",
        "matchType": "prefix",
        "from": timestamp,
        "to": timestamp,
        "output": "json"
    }
    res = requests.get(base_api, params=params)
    data = res.json()

    records = [row for row in data[1:] if len(row) > 3]
    pages = []
    for row in records:
        original = row[2]
        mime = row[3]
        status = row[4]
        if status == "200" and mime.startswith("text/html"):
            pages.append(original)

    os.makedirs(output_dir, exist_ok=True)

    for page_url in pages:
        wayback_url = f"https://web.archive.org/web/{timestamp}id_/{quote(page_url, safe=':/')}"
        try:
            resp = requests.get(wayback_url, timeout=15)
            if resp.status_code == 200:
                parsed = urlparse(page_url)
                path = parsed.path.lstrip("/")
                if not path or path.endswith("/"):
                    path = (path + "index.html").lstrip("/")
                if "." not in path.split("/")[-1]:
                    path += ".html"
                out_path = os.path.join(output_dir, path)
                os.makedirs(os.path.dirname(out_path), exist_ok=True)
                with open(out_path, "wb") as f:
                    f.write(resp.content)
                print(f"[OK] {page_url} -> {out_path}")
            else:
                print(f"[ERR] {page_url}: {resp.status_code}")
        except Exception as e:
            print(f"[FAIL] {page_url}: {e}")

    sitemap_path = os.path.join(output_dir, "sitemap.xml")
    urlset = ET.Element('urlset', xmlns="http://www.sitemaps.org/schemas/sitemap/0.9")
    for page_url in pages:
        url_el = ET.SubElement(urlset, 'url')
        loc = ET.SubElement(url_el, 'loc')
        loc.text = page_url
    tree = ET.ElementTree(urlset)
    tree.write(sitemap_path, encoding='utf-8', xml_declaration=True)
    print(f"[SITEMAP] Sitemap збережено у {sitemap_path}")

def main():
    setup_logging()
    print("Введите Wayback-ссылки для одного сайта (разные даты, по одной на строку).")
    print("Когда закончите — просто нажмите Enter на пустой строке:\n")
    links = []
    while True:
        link = input("> ").strip()
        if not link:
            break
        links.append(link)
    if not links:
        print("Ссылок не введено. Завершение.")
        return
    parser = argparse.ArgumentParser()
    parser.add_argument("--recursive", action="store_true", help="Обходить по ссылкам (по умолчанию одна страница)")
    parser.add_argument("-o", "--output", default="site_downloaded", help="Папка для сохранения")
    parser.add_argument("--external", choices=["delete", "original", "archive"], default="original",
                        help="Что делать с внешними ссылками: delete (убрать), original (оставить оригинал), archive (оставить как в архиве)")
    args = parser.parse_args()

    snapshots = []
    base_url = None
    for l in links:
        m = re.match(r"https?://web\.archive\.org/web/(\d+)[a-zA-Z_]*/(https?://.+)", l)
        if not m:
            print(f"Некорректная ссылка: {l}")
            return
        ts, b_url = m.group(1), m.group(2)
        if not base_url:
            base_url = b_url
        if b_url != base_url:
            print("Все ссылки должны быть на один и тот же сайт!")
            return
        snapshots.append((ts, b_url))

    crawl_multi_snapshots(snapshots, args.output, recursive=args.recursive, external_mode=args.external)

    print("\n[CDX-IMAGE] Зберігаю всі знайдені в архіві зображення у images/ ...")
    domain = urlparse(base_url).netloc
    download_all_images_via_cdx(domain, snapshots[0][0], output_dir=os.path.join(args.output, "all_images_from_cdx"))

    print("\n[CDX-PAGES] Зберігаю всі HTML-сторінки із архіву навіть без лінків...")
    save_all_archived_pages(domain, snapshots[0][0], output_dir=os.path.join(args.output, "all_html_from_cdx"))

if __name__ == "__main__":
    main()
