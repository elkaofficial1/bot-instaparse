import json
import re
import sys
import time
import hashlib
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from playwright.sync_api import sync_playwright

if len(sys.argv) < 2:
    print('Использование: python diagnose_instagram.py USERNAME')
    raise SystemExit(1)

username = sys.argv[1].strip().lstrip("@").strip("/")
stamp = time.strftime("%Y%m%d_%H%M%S")
out = Path(f"ig_diagnostic_{username}_{stamp}")
responses_dir = out / "responses"
responses_dir.mkdir(parents=True)

index = []
errors = []
saved_bytes = 0
MAX_TOTAL = 100 * 1024 * 1024
MAX_RESPONSE = 20 * 1024 * 1024
counter = 0

def clean_name(value):
    return re.sub(r"[^a-zA-Z0-9_.-]", "_", value)[:100]

def on_request(request):
    try:
        parsed = urlparse(request.url)
        params = parse_qs(parsed.query)
        post = None
        try:
            post = request.post_data_json
        except Exception:
            pass

        interesting = (
            "graphql" in request.url.lower()
            or "/api/v1/" in request.url.lower()
            or "query_hash" in request.url.lower()
            or "doc_id" in request.url.lower()
        )

        if interesting:
            index.append({
                "type": "request",
                "method": request.method,
                "url": request.url,
                "path": parsed.path,
                "query_params": params,
                "post_data": post,
            })
    except Exception as e:
        errors.append(f"request: {e}")

def on_response(response):
    global counter, saved_bytes

    try:
        url = response.url
        parsed = urlparse(url)
        headers = response.headers
        content_type = headers.get("content-type", "")
        interesting_url = (
            "graphql" in url.lower()
            or "/api/v1/" in url.lower()
            or "query_hash" in url.lower()
            or "doc_id" in url.lower()
        )

        if "json" not in content_type.lower() and not interesting_url:
            return

        body = response.body()
        if not body or len(body) > MAX_RESPONSE:
            return
        if saved_bytes + len(body) > MAX_TOTAL:
            return

        counter += 1
        saved_bytes += len(body)

        digest = hashlib.sha1(url.encode()).hexdigest()[:10]
        filename = f"{counter:04d}_{digest}.json"
        filepath = responses_dir / filename

        try:
            data = json.loads(body)
            filepath.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            parsed_ok = True
        except Exception:
            filepath = filepath.with_suffix(".txt")
            filepath.write_bytes(body)
            data = None
            parsed_ok = False

        index.append({
            "type": "response",
            "number": counter,
            "status": response.status,
            "url": url,
            "path": parsed.path,
            "content_type": content_type,
            "bytes": len(body),
            "file": str(filepath.relative_to(out)),
            "json": parsed_ok,
        })

    except Exception as e:
        errors.append(f"response: {e}")

def find_interesting_objects(value, path="$", found=None):
    if found is None:
        found = []

    if isinstance(value, dict):
        keys = list(value.keys())
        lower_keys = [str(k).lower() for k in keys]

        pin_keys = [
            k for k in keys
            if any(x in str(k).lower() for x in (
                "pin", "pinned", "highlight", "sticky"
            ))
        ]

        has_shortcode = any(
            str(k).lower() in ("shortcode", "code", "media_id", "id")
            for k in keys
        )
        has_owner = any(
            str(k).lower() in ("owner", "user", "username")
            for k in keys
        )

        if pin_keys or (has_shortcode and has_owner):
            found.append({
                "path": path,
                "pin_keys": pin_keys,
                "keys": keys,
                "object": value,
            })

        for key, child in value.items():
            find_interesting_objects(
                child, f"{path}.{key}", found
            )

    elif isinstance(value, list):
        for i, child in enumerate(value):
            find_interesting_objects(child, f"{path}[{i}]", found)

    return found

def main():
    global saved_bytes

    with sync_playwright() as p:
        profile_dir = Path.home() / ".instagram-reels-checker-profile"
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=False,
            viewport={"width": 1440, "height": 1100},
            args=["--disable-blink-features=AutomationControlled"],
        )

        page = context.pages[0] if context.pages else context.new_page()
        page.on("request", on_request)
        page.on("response", on_response)
        page.on("requestfailed", lambda r: errors.append(
            f"FAILED {r.method} {r.url}: {r.failure}"
        ))

        print("\nОткрываю Instagram...")
        page.goto("https://www.instagram.com/", wait_until="domcontentloaded")
        page.wait_for_timeout(4000)

        if "login" in page.url.lower():
            print("\nВойди в Instagram вручную в открывшемся Chromium.")
            input("Когда увидишь свою ленту Instagram, нажми Enter здесь... ")

        urls = [
            f"https://www.instagram.com/{username}/",
            f"https://www.instagram.com/{username}/reels/",
        ]

        for number, url in enumerate(urls, 1):
            print(f"\n[{number}/2] Открываю {url}")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(6000)

                for scroll in range(5):
                    page.mouse.wheel(0, 850)
                    page.wait_for_timeout(1800)

                page.evaluate("window.scrollTo(0, 0)")
                page.wait_for_timeout(1000)

                prefix = "profile" if number == 1 else "reels"

                (out / f"{prefix}.html").write_text(
                    page.content(), encoding="utf-8"
                )
                page.screenshot(
                    path=str(out / f"{prefix}.png"),
                    full_page=True
                )

                dom = page.evaluate("""() => {
                    const cards = [];
                    const seen = new Set();

                    for (const a of document.querySelectorAll('a[href*="/reel/"]')) {
                        const url = a.href.split('?')[0];
                        if (seen.has(url)) continue;
                        seen.add(url);

                        let node = a;
                        const ancestors = [];

                        for (let i = 0; i < 7 && node; i++, node = node.parentElement) {
                            ancestors.push({
                                tag: node.tagName,
                                class: String(node.className || ''),
                                role: node.getAttribute('role'),
                                aria: node.getAttribute('aria-label'),
                                title: node.getAttribute('title'),
                                testid: node.getAttribute('data-testid'),
                                text: (node.innerText || '').slice(0, 1000),
                                html: node.outerHTML.slice(0, 5000)
                            });
                        }

                        cards.push({
                            url,
                            href: a.getAttribute('href'),
                            aria: a.getAttribute('aria-label'),
                            title: a.getAttribute('title'),
                            html: a.outerHTML.slice(0, 5000),
                            svgs: [...a.querySelectorAll('svg')].map(s => ({
                                aria: s.getAttribute('aria-label'),
                                title: s.querySelector('title')?.textContent,
                                html: s.outerHTML.slice(0, 3000)
                            })),
                            ancestors
                        });
                    }

                    return {
                        url: location.href,
                        title: document.title,
                        bodyText: (document.body?.innerText || '').slice(0, 30000),
                        cards,
                        scripts: [...document.scripts]
                            .map(s => ({
                                src: s.src,
                                type: s.type,
                                length: (s.textContent || '').length
                            }))
                            .filter(s => s.src || s.length)
                    };
                }""")

                (out / f"{prefix}_dom.json").write_text(
                    json.dumps(dom, ensure_ascii=False, indent=2),
                    encoding="utf-8"
                )

                print(f"  Карточек Reels: {len(dom['cards'])}")
                print(f"  HTML и DOM сохранены.")

            except Exception as e:
                errors.append(f"PAGE {url}: {e}")
                print(f"  Ошибка: {e}")

        print("\nОбрабатываю собранные JSON...")
        matches = []

        for path in responses_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                found = find_interesting_objects(data)

                if found:
                    matches.append({
                        "file": str(path.relative_to(out)),
                        "objects": found,
                    })
            except Exception as e:
                errors.append(f"parse {path}: {e}")

        (out / "interesting_objects.json").write_text(
            json.dumps(matches, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

        (out / "network_index.json").write_text(
            json.dumps(index, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

        (out / "errors.txt").write_text(
            "\n".join(errors), encoding="utf-8"
        )

        summary = {
            "username": username,
            "created": stamp,
            "responses_saved": counter,
            "bytes_saved": saved_bytes,
            "interesting_objects_files": len(matches),
            "requests_and_responses": len(index),
            "errors": len(errors),
            "output": str(out.resolve()),
        }

        (out / "SUMMARY.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

        print("\n========== ГОТОВО ==========")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        print("\nОкно Chromium можно закрыть.")
        context.close()

if __name__ == "__main__":
    main()
