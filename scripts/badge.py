"""Write badges/coverage.svg from coverage.xml (no external service)."""
import xml.etree.ElementTree as ET
from pathlib import Path

rate = float(ET.parse("coverage.xml").getroot().attrib["line-rate"]) * 100
pct = f"{rate:.0f}%"
color = "#4c1" if rate >= 80 else "#dfb317" if rate >= 60 else "#fe7d37" if rate >= 40 else "#e05d44"
w1, w2 = 61, 14 + 7 * len(pct)
svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{w1 + w2}" height="20" role="img" aria-label="coverage: {pct}">
<linearGradient id="s" x2="0" y2="100%"><stop offset="0" stop-color="#bbb" stop-opacity=".1"/><stop offset="1" stop-opacity=".1"/></linearGradient>
<clipPath id="r"><rect width="{w1 + w2}" height="20" rx="3" fill="#fff"/></clipPath>
<g clip-path="url(#r)"><rect width="{w1}" height="20" fill="#555"/><rect x="{w1}" width="{w2}" height="20" fill="{color}"/><rect width="{w1 + w2}" height="20" fill="url(#s)"/></g>
<g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11">
<text x="{w1 / 2}" y="15" fill="#010101" fill-opacity=".3">coverage</text><text x="{w1 / 2}" y="14">coverage</text>
<text x="{w1 + w2 / 2}" y="15" fill="#010101" fill-opacity=".3">{pct}</text><text x="{w1 + w2 / 2}" y="14">{pct}</text></g></svg>"""
Path("badges").mkdir(exist_ok=True)
Path("badges/coverage.svg").write_text(svg)
print("coverage badge:", pct)
