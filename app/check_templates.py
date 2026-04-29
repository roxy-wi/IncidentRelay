import re
import sys
from html.parser import HTMLParser
from pathlib import Path


CHECKED_TAGS = {
    "div",
    "section",
    "main",
    "aside",
    "header",
    "nav",
    "table",
    "thead",
    "tbody",
    "tr",
    "td",
    "th",
}


class BalanceParser(HTMLParser):
    """
    Lightweight HTML balance checker for page partials.
    """

    def __init__(self):
        super().__init__()
        self.stack = []
        self.errors = []

    def handle_starttag(self, tag, attrs):
        if tag in CHECKED_TAGS:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag not in CHECKED_TAGS:
            return

        if not self.stack:
            self.errors.append(f"extra closing </{tag}>")
            return

        if self.stack[-1] == tag:
            self.stack.pop()
            return

        self.errors.append(f"mismatched closing </{tag}> while top is <{self.stack[-1]}>")

        while self.stack and self.stack[-1] != tag:
            self.stack.pop()

        if self.stack:
            self.stack.pop()


def check_file(path):
    """
    Check one template file.
    """

    text = path.read_text(encoding="utf-8")
    parser = BalanceParser()
    parser.feed(text)

    div_open = len(re.findall(r"<div\b", text))
    div_close = len(re.findall(r"</div>", text))

    errors = list(parser.errors)

    if div_open != div_close:
        errors.append(f"div open/close mismatch: {div_open}/{div_close}")

    if parser.stack:
        errors.append("unclosed tags: " + ", ".join(parser.stack))

    return errors


def main():
    """
    Check templates/pages/*.html for broken layout tags.
    """

    base = Path("app/templates/pages")
    failed = False

    for path in sorted(base.glob("*.html")):
        errors = check_file(path)

        if errors:
            failed = True
            print(f"{path}:")
            for error in errors:
                print(f"  - {error}")

    if not failed:
        print("Template check OK.")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
