# GCSE/IGCSE/A-Level Past-Papers Downloader
Automatically scrapes and downloads past-papers from [Physics & Maths Tutor](https://www.physicsandmathstutor.com) and organises them into folders by subject, paper number, and spec.

## Requirements

[Python 3.7+](https://www.python.org/downloads/), no extra libraries needed.

## Usage

```bash
python main.py
```

## Features

- Choose specific subjects to download
- Auto-organises files into folders by subject, board, paper, and type
- Rate limited to avoid overloading the server
- Failed downloads are retried on re-run

## Notes

- Re-running the script is safe. Progress is saved to `.pmt_progress.json` in your output folder — files already downloaded are skipped, and any that failed are automatically retried.


---
[License](LICENSE)
Mu_rpy © 2026