import urllib.request
import urllib.parse
import re
import sys
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

INPUT_FILE = "input.txt"
OUTPUT_DIR = "downloaded_papers"
MAX_WORKERS = 4

def scrape_page(url):
    req = urllib.request.Request(url.strip(), headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"  [ERROR] Could not fetch {url}: {e}")
        return []
    pattern = r'href="(https://pmt\.physicsandmathstutor\.com/download/[^"]+\.pdf)"'
    links = re.findall(pattern, html, re.IGNORECASE)
    return [urllib.parse.unquote(link) for link in links]

def parse_page_url(page_url):
    u = page_url.lower().rstrip("/")
    segments = u.split("/")

    SUBJECT_MAP = {
        "gcse-biology":           ("Biology",          "GCSE"),
        "gcse-chemistry":         ("Chemistry",        "GCSE"),
        "gcse-physics":           ("Physics",          "GCSE"),
        "gcse-maths":             ("Maths",            "GCSE"),
        "gcse-english-language":  ("English Language", "GCSE"),
        "gcse-english-literature":("English Literature","GCSE"),
        "gcse-economics":         ("Economics",        "GCSE"),
        "gcse-geography":         ("Geography",        "GCSE"),
        "gcse-psychology":        ("Psychology",       "GCSE"),
        "gcse-computer-science":  ("Computer Science", "GCSE"),
        "a-level-biology":        ("Biology",          "A-Level"),
        "a-level-chemistry":      ("Chemistry",        "A-Level"),
        "a-level-physics":        ("Physics",          "A-Level"),
        "a-level-maths":          ("Maths",            "A-Level"),
        "a-level-economics":      ("Economics",        "A-Level"),
        "a-level-geography":      ("Geography",        "A-Level"),
        "a-level-psychology":     ("Psychology",       "A-Level"),
        "a-level-computer-science":("Computer Science","A-Level"),
        "a-level-english-language":("English Language","A-Level"),
        "a-level-english-literature":("English Literature","A-Level"),
    }

    subject = "Unknown"
    level = "Unknown"
    for seg in segments:
        if seg in SUBJECT_MAP:
            subject, level = SUBJECT_MAP[seg]
            break

    if "igcse" in u and level == "GCSE":
        level = "IGCSE"

    paper_num = None
    for seg in reversed(segments):
        m = re.search(r'paper-(\d+)', seg)
        if m:
            paper_num = m.group(1)
            break

    return subject, level, paper_num

def get_subfolder(pdf_url, subject, level, paper_num):
    u = urllib.parse.unquote(pdf_url)

    subject_folder = f"{subject} ({level})"
    paper_folder   = f"Paper {paper_num}" if paper_num else "Paper Unknown"

    if "/New-Spec-Paper-" in u or "/New-Spec/" in u:
        spec = "New-Spec"
    else:
        spec = "Old-Spec"

    if "/QP/" in u or u.endswith("QP.pdf") or " QP" in u:
        doc_type = "Question-Papers"
    elif "/MS/" in u or u.endswith("MS.pdf") or " MS" in u:
        doc_type = "Mark-Schemes"
    else:
        doc_type = "Other"

    return f"{subject_folder}/{paper_folder}/{spec}/{doc_type}"

def sanitize_filename(url):
    filename = url.split("/")[-1]
    filename = urllib.parse.unquote(filename).strip()
    for ch in ['/', '\\', ':', '*', '?', '"', '<', '>', '|']:
        filename = filename.replace(ch, '_')
    return filename

def download_file(pdf_url, subject, level, paper_num, output_dir):
    pdf_url = pdf_url.strip()
    if not pdf_url or not pdf_url.startswith("http"):
        return None, "skipped"
    encoded_url = urllib.parse.quote(pdf_url, safe=":/?=&%")
    filename    = sanitize_filename(pdf_url)
    subfolder   = get_subfolder(pdf_url, subject, level, paper_num)
    dest_dir    = Path(output_dir) / subfolder
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path   = dest_dir / filename
    if dest_path.exists():
        return filename, "already exists"
    try:
        req = urllib.request.Request(encoded_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as response:
            with open(dest_path, "wb") as f:
                f.write(response.read())
        return filename, "ok"
    except Exception as e:
        return filename, f"FAILED: {e}"

def main():
    if not os.path.exists(INPUT_FILE):
        print(f"Error: {INPUT_FILE} not found.")
        print(f"Add one PMT past papers page URL per line and re-run.")
        sys.exit(1)

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        page_urls = [line.strip() for line in f if line.strip() and line.strip().startswith("http")]

    if not page_urls:
        print(f"No URLs found in {INPUT_FILE}.")
        sys.exit(1)

    print(f"Found {len(page_urls)} page(s). Scraping PDF links...\n")

    tasks = []
    for page_url in page_urls:
        subject, level, paper_num = parse_page_url(page_url)
        print(f"  Scraping : {page_url}")
        print(f"  Detected : {subject} ({level}) — Paper {paper_num}")
        links = scrape_page(page_url)
        print(f"  Found    : {len(links)} PDFs\n")
        for link in links:
            tasks.append((link, subject, level, paper_num))

    seen = set()
    unique_tasks = []
    for t in tasks:
        if t[0] not in seen:
            seen.add(t[0])
            unique_tasks.append(t)

    if not unique_tasks:
        print("No PDF links found. Check your URLs are valid PMT past papers pages.")
        sys.exit(1)

    total = len(unique_tasks)
    print(f"{total} total PDFs to download into '{OUTPUT_DIR}/'...\n")
    Path(OUTPUT_DIR).mkdir(exist_ok=True)

    ok = skipped = failed = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(download_file, pdf, subj, lvl, pnum, OUTPUT_DIR): pdf
            for pdf, subj, lvl, pnum in unique_tasks
        }
        for i, future in enumerate(as_completed(futures), 1):
            filename, status = future.result()
            if status == "ok":
                ok += 1
                tag = "OK"
            elif status == "already exists":
                skipped += 1
                tag = "SKIP"
            elif status == "skipped":
                skipped += 1
                tag = "SKIP"
            else:
                failed += 1
                tag = "FAIL"
            print(f"[{i:>3}/{total}] [{tag}] {filename or '(empty)'} — {status}")

    print(f"\nDone. {ok} downloaded, {skipped} skipped, {failed} failed.")
    print(f"Files saved in: {Path(OUTPUT_DIR).resolve()}")

if __name__ == "__main__":
    main()