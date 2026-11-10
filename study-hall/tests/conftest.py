"""Keep the background crawl off during tests. The real app leaves it on."""
import os

os.environ["STUDYHALL_AUTOMATE"] = "0"
