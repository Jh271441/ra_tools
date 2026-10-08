"""Prevent phone CSS from hiding a form with no reachable disclosure control."""
from html.parser import HTMLParser
from pathlib import Path
import unittest


class Controls(HTMLParser):
    def __init__(self, markup):
        super().__init__()
        self.forms = []
        self.toggles = []
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form" and set(attrs.get("class", "").split()) & {"review-filters", "analysis-filters"}:
            self.forms.append(attrs)
        if tag == "button" and "data-mobile-filter-toggle" in attrs:
            self.toggles.append(attrs)


class MobileFilterAccessTest(unittest.TestCase):
    def test_every_phone_collapsed_form_has_an_accessible_toggle(self):
        controls = Controls((Path(__file__).resolve().parents[1] / "static/index.html").read_text())
        self.assertTrue(controls.forms)
        for form in controls.forms:
            with self.subTest(form=form.get("id")):
                key = form.get("data-mobile-filter-panel")
                self.assertTrue(key, "Phone CSS hides this form; it needs a disclosure")
                matches = [toggle for toggle in controls.toggles if toggle["data-mobile-filter-toggle"] == key]
                self.assertEqual(len(matches), 1)
                self.assertEqual(matches[0].get("aria-controls"), form["id"])
                self.assertEqual(matches[0].get("aria-expanded"), "false")
