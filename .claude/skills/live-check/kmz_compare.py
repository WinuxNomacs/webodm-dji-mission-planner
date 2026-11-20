"""
python kmz_compare.py <a.kmz> <b.kmz> [...]: compares the first KMZ with each other one, entry by entry. Identical
entries are not shown; the create and update times are left out; numbers that differ are shown as the largest
difference per tag (floating-point noise between WebODM versions shows as ~1e-9 and less).
"""
import re
import sys
import zipfile
from collections import defaultdict

NUM = re.compile(r"-?\d+\.?\d*(?:[eE][-+]?\d+)?")


def entries(path):
    with zipfile.ZipFile(path) as z:
        return {n: z.read(n) for n in z.namelist()}


def compare(a, b):
    ea, eb = entries(a), entries(b)
    if sorted(ea) != sorted(eb):
        return ["entries differ: %s vs %s" % (sorted(ea), sorted(eb))]
    worst, other = defaultdict(float), []
    for name in ea:
        if ea[name] == eb[name]:
            continue
        if not name.endswith((".kml", ".wpml")):
            other.append("%s differs" % name)
            continue
        la, lb = ea[name].decode().splitlines(), eb[name].decode().splitlines()
        if len(la) != len(lb):
            other.append("%s: %d lines vs %d" % (name, len(la), len(lb)))
            continue
        for x, y in zip(la, lb):
            if x == y or re.search(r"<wpml:(create|update)Time>", x):
                continue
            if NUM.sub("#", x) != NUM.sub("#", y):
                other.append("%s: %s -> %s" % (name, x.strip()[:80], y.strip()[:80]))
                continue
            tag = re.search(r"<(?:wpml:)?(\w+)>", x)
            d = max(abs(float(p) - float(q)) for p, q in zip(NUM.findall(x), NUM.findall(y)))
            worst[tag.group(1) if tag else "coordinates"] = max(worst[tag.group(1) if tag else "coordinates"], d)
    return other + ["%s: largest difference %.2e" % (k, v) for k, v in worst.items()]


if __name__ == "__main__":
    for other in sys.argv[2:]:
        found = compare(sys.argv[1], other)
        print(other, "same" if not found else "; ".join(found))
