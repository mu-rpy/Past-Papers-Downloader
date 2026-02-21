import urllib.request
import urllib.parse
import re
import os
import time
import json
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

OUTPUT_DIR = "downloaded_papers"
MAX_WORKERS = 4
BASE = "https://www.physicsandmathstutor.com"
PROGRESS_FILE = ".pmt_progress.json"

RATE_LIMIT_DELAY = 1.5
_rate_lock = threading.Lock()
_last_request_time = 0.0
_progress_lock = threading.Lock()

GCSE_CATEGORIES = [
    ("Biology",            "GCSE",  f"{BASE}/past-papers/gcse-biology/"),
    ("Chemistry",          "GCSE",  f"{BASE}/past-papers/gcse-chemistry/"),
    ("Physics",            "GCSE",  f"{BASE}/past-papers/gcse-physics/"),
    ("Maths",              "GCSE",  f"{BASE}/past-papers/gcse-maths/"),
    ("English Language",   "GCSE",  f"{BASE}/past-papers/gcse-english-language/"),
    ("English Literature", "GCSE",  f"{BASE}/past-papers/gcse-english-literature/"),
    ("Economics",          "GCSE",  f"{BASE}/past-papers/gcse-economics/"),
    ("Geography",          "GCSE",  f"{BASE}/past-papers/gcse-geography/"),
    ("Psychology",         "GCSE",  f"{BASE}/past-papers/gcse-psychology/"),
    ("Computer Science",   "GCSE",  f"{BASE}/past-papers/gcse-computer-science/"),
    ("Combined Science",   "GCSE",  f"{BASE}/past-papers/gcse-science/"),
    ("History",            "GCSE",  f"{BASE}/past-papers/gcse-history/"),
]

ALEVEL_CATEGORIES = [
    ("Biology",            "A-Level", f"{BASE}/past-papers/a-level-biology/"),
    ("Chemistry",          "A-Level", f"{BASE}/past-papers/a-level-chemistry/"),
    ("Physics",            "A-Level", f"{BASE}/past-papers/a-level-physics/"),
    ("Maths",              "A-Level", f"{BASE}/a-level-maths-papers/"),
    ("English Language",   "A-Level", f"{BASE}/past-papers/a-level-english-language/"),
    ("English Literature", "A-Level", f"{BASE}/past-papers/a-level-english-literature/"),
    ("Economics",          "A-Level", f"{BASE}/past-papers/a-level-economics/"),
    ("Geography",          "A-Level", f"{BASE}/past-papers/a-level-geography/"),
    ("Psychology",         "A-Level", f"{BASE}/past-papers/a-level-psychology/"),
    ("Computer Science",   "A-Level", f"{BASE}/past-papers/a-level-computer-science/"),
    ("History",            "A-Level", f"{BASE}/past-papers/a-level-history/"),
]

USES_SPEC = {("Biology", "A-Level"), ("Chemistry", "A-Level"), ("Physics", "A-Level")}


def load_progress(output_dir):
    path = Path(output_dir) / PROGRESS_FILE
    if path.exists():
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"  [WARN] Could not read progress file: {e}")
            backup = path.with_suffix(".json.bak")
            path.rename(backup)
            print(f"  [WARN] Corrupted progress file moved to {backup}, starting fresh.")
            return {}
    return {}


def scan_existing_files(output_dir):
    root = Path(output_dir)
    if not root.exists():
        return set()
    print("Scanning existing files on disk...")
    found = {f.name for f in root.rglob("*.pdf")}
    print(f"Found {len(found)} existing PDFs on disk.")
    return found


def save_progress(output_dir, progress):
    path = Path(output_dir) / PROGRESS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w") as f:
        json.dump(progress, f)
    tmp.replace(path)


def record_result(output_dir, progress, pdf_url, status):
    with _progress_lock:
        progress[pdf_url] = status
        save_progress(output_dir, progress)


def fetch_html(url):
    global _last_request_time
    with _rate_lock:
        elapsed = time.monotonic() - _last_request_time
        if elapsed < RATE_LIMIT_DELAY:
            time.sleep(RATE_LIMIT_DELAY - elapsed)
        _last_request_time = time.monotonic()

    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.read().decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"  [WARN] Failed to fetch {url}: {e}")
        return ""


def scrape_subpage_links(index_url):
    html = fetch_html(index_url)
    base_path = urllib.parse.urlparse(index_url).path.rstrip("/")
    pattern = re.compile(
        r'href="(' + re.escape(BASE) + re.escape(base_path) + r'/[^"#]+?)"'
    )
    return list(dict.fromkeys(pattern.findall(html)))


def scrape_pdfs(page_url):
    html = fetch_html(page_url)
    return re.findall(
        r'href="(https://pmt\.physicsandmathstutor\.com/download/[^"]+\.pdf)"',
        html
    )


def get_folder(pdf_url, subject, level, page_url):
    u  = urllib.parse.unquote(pdf_url)
    pu = urllib.parse.unquote(page_url)
    slug = pu.rstrip("/").split("/")[-1]

    board = "Unknown"
    for b in ["aqa", "edexcel", "ocr-a", "ocr-b", "ocr", "caie", "cie-igcse", "cie",
              "wjec-eduqas", "eduqas", "wjec", "ccea"]:
        if slug.startswith(b):
            board = b.upper().replace("-", " ")
            break
    board = board.replace("WJEC EDUQAS", "Eduqas").replace("CIE IGCSE", "CAIE").replace("CIE", "CAIE")

    is_igcse = "igcse" in slug or "/IGCSE/" in u

    pm = re.search(r'/Paper-(\d+)', u) or re.search(r'paper[- ](\d+)', slug, re.I)
    cm = re.search(r'component[- ](\d+)', slug, re.I)
    um = re.search(r'unit[- ](\d+)', slug, re.I)
    if pm:
        paper_folder = f"Paper {pm.group(1)}"
    elif cm:
        paper_folder = f"Component {cm.group(1)}"
    elif um:
        paper_folder = f"Unit {um.group(1)}"
    else:
        paper_folder = "Other"

    tier = None
    tm = re.search(r'/Paper-\d*([FH])/', u, re.IGNORECASE)
    if tm:
        tier = "Foundation" if tm.group(1).upper() == "F" else "Higher"
    elif re.search(r'\bFoundation\b', u, re.I):
        tier = "Foundation"
    elif re.search(r'\bHigher\b', u, re.I):
        tier = "Higher"

    spec = None
    if (subject, level) in USES_SPEC:
        spec = "New-Spec" if "/New-Spec" in u else "Old-Spec"

    fname = u.split("/")[-1]
    if "/QP/" in u or re.search(r'\bQP\b', fname):
        doc_type = "Question-Papers"
    elif "/MS/" in u or re.search(r'\bMS\b', fname):
        doc_type = "Mark-Schemes"
    elif "/MA/" in u or re.search(r'\bMA\b', fname):
        doc_type = "Model-Answers"
    else:
        doc_type = "Other"

    top = "A-Level" if level == "A-Level" else "GCSE & IGCSE"

    parts = [top, subject]
    if is_igcse:
        parts.append("IGCSE")
    parts.append(board)
    parts.append(paper_folder)
    if tier:
        parts.append(tier)
    if spec:
        parts.append(spec)
    parts.append(doc_type)

    return os.path.join(*parts)


def encode_url(url):
    parsed = urllib.parse.urlsplit(url)
    encoded_path = urllib.parse.quote(parsed.path, safe="/:@!$&'()*+,;=")
    return urllib.parse.urlunsplit(parsed._replace(path=encoded_path))


def download_file(pdf_url, folder, output_dir, progress, existing_files):
    if progress.get(pdf_url) == "ok":
        return f"  [SKIP] {pdf_url.split('/')[-1]} (already done)"

    filename = urllib.parse.unquote(pdf_url.split("/")[-1])

    if filename in existing_files and progress.get(pdf_url) != "fail":
        record_result(output_dir, progress, pdf_url, "ok")
        return f"  [SKIP] {filename}"

    dest = Path(output_dir) / folder / filename
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        safe_url = encode_url(pdf_url)
        req = urllib.request.Request(safe_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r, open(dest, "wb") as f:
            f.write(r.read())
        existing_files.add(filename)
        record_result(output_dir, progress, pdf_url, "ok")
        return f"  [OK]   {dest}"
    except Exception as e:
        record_result(output_dir, progress, pdf_url, "fail")
        return f"  [FAIL] {pdf_url}: {e}"


def process_category(subject, level, index_url, output_dir, progress, existing_files):
    print(f"\n{'='*60}")
    print(f"  {subject} ({level})")
    print(f"{'='*60}")

    sub_pages = scrape_subpage_links(index_url)
    if not sub_pages:
        print(f"  [WARN] No sub-pages found at {index_url}")
        return

    print(f"  Found {len(sub_pages)} board/paper listing pages (one per board+paper combo)")

    all_tasks = []
    for page_url in sub_pages:
        for pdf_url in scrape_pdfs(page_url):
            folder = get_folder(pdf_url, subject, level, page_url)
            all_tasks.append((pdf_url, folder))

    already_ok = sum(1 for url, _ in all_tasks if progress.get(url) == "ok")
    pending    = [(url, folder) for url, folder in all_tasks if progress.get(url) != "ok"]
    retrying   = sum(1 for url, _ in pending if progress.get(url) == "fail")

    print(f"  Found {len(all_tasks)} PDFs — {already_ok} done, {retrying} retrying, {len(pending) - retrying} new")

    if not pending:
        print("  All files already downloaded, skipping.")
        return

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(download_file, url, folder, output_dir, progress, existing_files): url
                   for url, folder in pending}
        for fut in as_completed(futures):
            print(fut.result())


def select_subcategories(categories, level_name):
    print(f"\nAvailable {level_name} subjects:")
    for i, (subject, level, _) in enumerate(categories, 1):
        print(f"  {i:2}. {subject}")
    print(f"  {'A':>2}. All subjects")

    raw = input(f"Select {level_name} subjects (e.g. 1,3,5 or A for all): ").strip()
    if raw.upper() == "A" or raw == "":
        return categories

    selected = []
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            idx = int(part) - 1
            if 0 <= idx < len(categories):
                selected.append(categories[idx])
            else:
                print(f"  [WARN] Invalid selection '{part}', skipping.")
        else:
            print(f"  [WARN] Invalid input '{part}', skipping.")
    return selected


def main():
    print("PMT Past Paper Downloader")
    print("=========================")
    print("What do you want to download?")
    print("  1 - GCSE only")
    print("  2 - A-Level only")
    print("  3 - Both")
    choice = input("Enter choice (1/2/3): ").strip()

    to_run = []
    if choice == "1":
        to_run = select_subcategories(GCSE_CATEGORIES, "GCSE")
    elif choice == "2":
        to_run = select_subcategories(ALEVEL_CATEGORIES, "A-Level")
    elif choice == "3":
        gcse_sel = select_subcategories(GCSE_CATEGORIES, "GCSE")
        alevel_sel = select_subcategories(ALEVEL_CATEGORIES, "A-Level")
        to_run = gcse_sel + alevel_sel
    else:
        print("Invalid choice, exiting.")
        return

    if not to_run:
        print("No subjects selected, exiting.")
        return

    output = input(f"Output directory (press Enter for '{OUTPUT_DIR}'): ").strip()
    if not output:
        output = OUTPUT_DIR

    progress = load_progress(output)
    total_done = sum(1 for v in progress.values() if v == "ok")
    total_fail = sum(1 for v in progress.values() if v == "fail")

    if progress:
        print(f"\nExisting session found — {total_done} done, {total_fail} failed.")
        reset = input("Start from scratch? This clears all progress (y/N): ").strip().lower()
        if reset == "y":
            progress = {}
            save_progress(output, progress)
            print("Progress cleared, starting fresh.")
        else:
            print("Resuming previous session (failed files will be retried).")
    else:
        print(f"\nStarting fresh download to '{output}'.")
    existing_files = scan_existing_files(output)

    print(f"Downloading {len(to_run)} categories...\n")
    for subject, level, index_url in to_run:
        process_category(subject, level, index_url, output, progress, existing_files)

    final_ok   = sum(1 for v in progress.values() if v == "ok")
    final_fail = sum(1 for v in progress.values() if v == "fail")
    print(f"\nDone. {final_ok} succeeded, {final_fail} failed.")
    if final_fail:
        print(f"Re-run the script to retry the {final_fail} failed files.")


if __name__ == "__main__":
    main()