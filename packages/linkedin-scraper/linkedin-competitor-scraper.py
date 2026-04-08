#!/usr/bin/env python3
import argparse
import json
import random
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path


CONFIG_PATH = Path(__file__).parent / "linkedin-competitors.json"


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def save_config(config):
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)


def run_unipile(config, *args):
    cmd = ["node", "scripts/linkedin.mjs"] + list(args)
    result = subprocess.run(
        cmd,
        cwd=config["unipile_skill_dir"],
        capture_output=True,
        text=True,
        timeout=90,
    )
    if result.returncode != 0:
        return {
            "ok": False,
            "error": result.stderr[:500] or result.stdout[:500],
            "command": cmd,
        }
    try:
        return {"ok": True, "data": json.loads(result.stdout)}
    except json.JSONDecodeError:
        return {
            "ok": False,
            "error": f"Bad JSON: {result.stdout[:300]}",
            "command": cmd,
        }


def discover_employees(config, account_id, company_name):
    result = run_unipile(
        config,
        "search",
        account_id,
        "--category=people",
        f"--keywords={company_name}",
        "--limit=10",
    )
    if not result["ok"]:
        return [], result["error"]
    data = result["data"]
    if not data or not data.get("items"):
        return [], None
    employees = []
    for item in data["items"]:
        headline = (item.get("headline") or "").lower()
        if company_name.lower() in headline:
            employees.append(
                {
                    "name": item.get("name", "Unknown"),
                    "provider_id": item.get("id", ""),
                    "role": item.get("headline", ""),
                }
            )
    return employees[:10], None


def filter_posts_by_window(posts, window_days):
    cutoff = datetime.utcnow() - timedelta(days=window_days)
    filtered = []
    for p in posts:
        parsed = p.get("parsed_datetime")
        if not parsed:
            continue
        try:
            dt = datetime.fromisoformat(parsed.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            continue
        if dt >= cutoff:
            filtered.append(p)
    return filtered


def score_post(post):
    reactions = post.get("reaction_counter", 0)
    comments = post.get("comment_counter", 0)
    reposts = post.get("repost_counter", 0)
    return reactions + (comments * 3) + (reposts * 2)


def first_image_url(post):
    for attachment in post.get("attachments", []) or []:
        if attachment.get("type") == "img" and attachment.get("url"):
            return attachment["url"]
    return None


def maybe_download_image(url, dest_path):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=15)
        with open(dest_path, "wb") as f:
            f.write(resp.read())
        return str(dest_path)
    except Exception:
        return None


def post_url(post):
    if post.get("share_url"):
        return post["share_url"]
    social_id = post.get("social_id", "")
    if social_id.startswith("urn:li:activity:"):
        activity_id = social_id.split(":")[-1]
        return f"https://www.linkedin.com/feed/update/urn:li:activity:{activity_id}"
    return ""


def compact_post(post, rank):
    return {
        "rank": rank,
        "author": post.get("_employee", "Unknown"),
        "company": post.get("_company", ""),
        "role": post.get("_role", ""),
        "score": post.get("_score", 0),
        "date": (post.get("parsed_datetime") or "")[:10],
        "reactions": post.get("reaction_counter", 0),
        "comments": post.get("comment_counter", 0),
        "reposts": post.get("repost_counter", 0),
        "text": (post.get("text") or "").strip(),
        "text_preview": (post.get("text") or "").strip()[:240],
        "post_url": post_url(post),
        "has_image": bool(post.get("attachments")),
        "image_url": first_image_url(post),
    }


def run_scrape(window_days=None, pick_override=None, download_images=False):
    config = load_config()
    account_id = config["account_id"]
    companies = config["companies"]
    low, high = config["pick_count"]
    if pick_override is None:
        pick_n = random.randint(low, min(high, len(companies)))
    else:
        pick_n = min(max(1, pick_override), len(companies))
    selected = random.sample(companies, pick_n)

    all_posts = []
    errors = []
    warnings = []
    discovery_updates = 0

    for company in selected:
        name = company["name"]
        identifier = company.get("identifier", "")
        employees = company.get("employees", [])

        company_page = run_unipile(config, "posts", account_id, identifier, "--company", "--limit=20")
        if company_page["ok"] and company_page["data"] and company_page["data"].get("items"):
            for post in company_page["data"]["items"]:
                post["_company"] = name
                post["_employee"] = f"{name} (company page)"
                post["_role"] = "Company Page"
            all_posts.extend(company_page["data"]["items"])
        else:
            warnings.append(f"Company page fetch failed for {name}: {company_page.get('error', 'no data')}")

        if not employees:
            discovered, error = discover_employees(config, account_id, name)
            if error:
                warnings.append(f"Employee discovery failed for {name}: {error}")
            elif discovered:
                company["employees"] = discovered
                employees = discovered
                discovery_updates += 1

        for employee in employees[:10]:
            provider_id = employee.get("provider_id")
            if not provider_id:
                continue
            employee_posts = run_unipile(config, "posts", account_id, provider_id, "--limit=10")
            if not employee_posts["ok"] or not employee_posts["data"] or not employee_posts["data"].get("items"):
                continue
            for post in employee_posts["data"]["items"]:
                post["_company"] = name
                post["_employee"] = employee.get("name", "Unknown")
                post["_role"] = employee.get("role", "")
            all_posts.extend(employee_posts["data"]["items"])

    if discovery_updates:
        save_config(config)

    if not all_posts:
        return {
            "status": "error",
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "selected_companies": [c["name"] for c in selected],
            "errors": errors,
            "warnings": warnings,
            "message": "No posts fetched from any company.",
            "top_posts": [],
            "summary": {"company_counts": {}, "top_companies": []},
        }

    windows = [window_days or config["default_window_days"]] + config.get("fallback_windows_days", [])
    filtered = []
    selected_window = None
    for window in windows:
        filtered = filter_posts_by_window(all_posts, window)
        if filtered:
            selected_window = window
            break
    if not filtered:
        filtered = all_posts
        selected_window = None

    originals = [p for p in filtered if not p.get("is_repost", False)] or filtered
    for post in originals:
        post["_score"] = score_post(post)
    originals.sort(key=lambda p: p["_score"], reverse=True)
    top = originals[:10]

    images_dir = Path(config["images_dir"]) / "daily-scrape"
    if download_images:
        images_dir.mkdir(parents=True, exist_ok=True)

    top_posts = []
    company_counts = {}
    for idx, post in enumerate(top, start=1):
        item = compact_post(post, idx)
        company_counts[item["company"]] = company_counts.get(item["company"], 0) + 1
        if download_images and item["image_url"]:
            author_slug = (item["author"].split()[0] or "post").lower()
            img_path = images_dir / f"{idx:02d}-{author_slug}-original.jpg"
            item["downloaded_image_path"] = maybe_download_image(item["image_url"], img_path)
        top_posts.append(item)

    ordered_companies = sorted(company_counts.items(), key=lambda x: x[1], reverse=True)

    return {
        "status": "ok",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "selected_companies": [c["name"] for c in selected],
        "window_days_requested": window_days or config["default_window_days"],
        "window_days_used": selected_window,
        "total_posts_fetched": len(all_posts),
        "total_posts_considered": len(originals),
        "errors": errors,
        "warnings": warnings,
        "top_posts": top_posts,
        "summary": {
            "company_counts": company_counts,
            "top_companies": [name for name, _ in ordered_companies[:3]],
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--window-days", type=int, default=None)
    parser.add_argument("--pick-count", type=int, default=None)
    parser.add_argument("--download-images", action="store_true")
    parser.add_argument("--save-json", type=str, default="")
    args = parser.parse_args()

    result = run_scrape(
        window_days=args.window_days,
        pick_override=args.pick_count,
        download_images=args.download_images,
    )
    if args.save_json:
        target = Path(args.save_json)
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w") as f:
            json.dump(result, f, indent=2)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["status"] == "ok" else 1)


if __name__ == "__main__":
    main()
