<<<<<<< HEAD
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
=======
British Horseracing Authority - scraper and analyzer

This here small application is used to scan a specified date range in order to collect data about races that took place during the selected time period.

The results can then be sorted in one of several predefined ways for analysis and drawing your own conclusions, whatever they may be.

The data collected is rather raw, and the ready-made sorters may not necessarily be sufficient for your analysis, so you may want to create your own statistics system.


Go ahead.
And if you come up with something interesting, please share your idea with me.
>>>>>>> c6e4313cf24375f3b73ed5fc1a1da5439c5d9597
