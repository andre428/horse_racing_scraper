## Horse racer scraper + Django

....
....


## Install from scratch

# basic install:
pip install -e .
playwright install firefox

# dev install
pip install -e ".[dev,html]"
playwright install firefox

pip install -e ".[dev,celery]"
pip install ".[prod]"

'''
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.firefox.launch(headless=True)
'''