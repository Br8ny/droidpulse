# Contributing

## What this project is

A daily-refreshed leaderboard of open-source Android apps, built from the F-Droid index and GitHub metadata. It hosts no APKs — every entry links to the developer's official release page.

## Setup

```bash
python -m pip install pillow   # only needed to regenerate the launch image
python -m unittest discover -s tests -v
```

The generator itself uses only the standard library.

## Regenerating locally

```bash
GITHUB_TOKEN=<your token> python scripts/generate.py
python scripts/make_launch_image.py
```

`GITHUB_TOKEN` needs no special scopes for public repository search.

## Rules

- Keep the generator dependency-free.
- Never write APKs or other binaries into the repo (the launch PNG is the only asset).
- Anything that changes ranking logic needs a test in `tests/test_generate.py`.
- README and `docs/` are generated — edit `scripts/generate.py`, not the outputs.

## Adding a missing app

Add its `owner/repo` slug to `data/extra-apps.json`. It still needs an F-Droid source URL to get a name and category; apps outside F-Droid are intentionally excluded.
