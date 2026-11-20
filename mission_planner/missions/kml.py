"""
Plain KML (Google Earth, other planners, GIS tools): a shape read into a new route, and a route written out as KML.

Reading (read_kml) takes a .kml file, or a .kmz holding one (doc.kml, or the first .kml in it), and makes a route of
the first shape found, in this order: a polygon (its outer boundary) becomes an area route, a line a linear route,
two or more points a waypoint route (in the file's order). Heights in the file are ignored: the route takes the
planner's defaults, set in its editor. A DJI mission file (wpmz/template.kml) is not plain KML: kmz_import reads it.

Writing (write_kml) gives the route's shape (draped on the ground) and the path the aircraft flies, at the heights
the 3D view draws it at (air.py): above sea level where the route knows them ("absolute" in KML, which Google Earth
measures from EGM96, as the planner does), else above the ground under the path ("relativeToGround"). It is for
viewing and sharing, not a mission file.
"""
import io
import re
import zipfile
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

from .kmz_import import MAX_NAME, MAX_TEMPLATE_SIZE, MAX_VERTICES, KmzImportError
from .linear import MAX_POINTS

KML_NS = "http://www.opengis.net/kml/2.2"


def is_kml(data):
    """Whether the file is plain KML or a KMZ holding plain KML, not a DJI mission (wpmz/template.kml)"""
    if data[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                names = z.namelist()
        except (zipfile.BadZipFile, zipfile.LargeZipFile, EOFError):
            return False
        return "wpmz/template.kml" not in names and any(n.lower().endswith(".kml") for n in names)
    head = data[:2048].lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    return head.startswith((b"<?xml", b"<kml"))


def _document(data):
    if data[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                kmls = [n for n in z.namelist() if n.lower().endswith(".kml")]
                if not kmls:
                    raise KmzImportError("The .kmz file holds no .kml")
                name = "doc.kml" if "doc.kml" in kmls else kmls[0]
                if z.getinfo(name).file_size > MAX_TEMPLATE_SIZE:
                    raise KmzImportError("The KML file is too large")
                data = z.read(name)
        except (zipfile.BadZipFile, zipfile.LargeZipFile, EOFError):
            raise KmzImportError("This is not a .kmz file (not a zip archive)")
    elif len(data) > MAX_TEMPLATE_SIZE:
        raise KmzImportError("The KML file is too large")
    try:
        # ElementTree does not expand external entities; a DOCTYPE has no place in a KML file
        if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
            raise ET.ParseError("DOCTYPE")
        return ET.fromstring(data)
    except ET.ParseError:
        raise KmzImportError("The KML in the file cannot be read (it is not valid XML)")


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _all(element, name):
    """Every descendant of element named name, whatever its namespace (KML 2.0, 2.1, 2.2 or none)"""
    return [e for e in element.iter() if _local(e.tag) == name]


def _coordinates(element):
    """[[lon, lat], ...] of the first coordinates under element"""
    found = _all(element, "coordinates")
    if not found or not (found[0].text or "").strip():
        return []
    points = []
    for item in found[0].text.split():
        parts = item.split(",")
        try:
            lon, lat = float(parts[0]), float(parts[1])
        except (IndexError, ValueError):
            raise KmzImportError("The KML has a coordinate that is not a longitude and latitude: %r" % item[:40])
        if not (-180 <= lon <= 180 and -85 <= lat <= 85):
            raise KmzImportError("The KML has a coordinate outside the map: %r" % item[:40])
        points.append([round(lon, 9), round(lat, 9)])
    return points


def _name(placemark, root, fallback):
    for element in ([placemark] if placemark is not None else []) + _all(root, "Document"):
        for child in element:
            if _local(child.tag) == "name" and (child.text or "").strip():
                return child.text.strip()[:MAX_NAME]
    return fallback


def read_kml(data, name):
    """
    (route_type, settings) of a plain KML or KMZ file: the first polygon, line or set of points as a route's shape.

    :param name: the route's name when the file names none (the file's name without its extension)
    :raises KmzImportError: why the file cannot be imported
    """
    root = _document(data)
    placemarks = _all(root, "Placemark")
    for placemark in placemarks:
        for polygon in _all(placemark, "Polygon"):
            outer = _all(polygon, "outerBoundaryIs") or [polygon]
            ring = _coordinates(outer[0])
            if len(ring) > 3 and ring[0] == ring[-1]:
                ring = ring[:-1]
            if len(ring) < 3:
                raise KmzImportError("The KML's polygon has fewer than 3 corners")
            if len(ring) > MAX_VERTICES:
                raise KmzImportError("The KML's polygon has too many corners (at most %d)" % MAX_VERTICES)
            return "area", {"name": _name(placemark, root, name), "polygon": ring, "takeoff": None, "route_start": None}
    for placemark in placemarks:
        for line in _all(placemark, "LineString"):
            points = _coordinates(line)
            if len(points) < 2:
                raise KmzImportError("The KML's line has fewer than 2 points")
            if len(points) > MAX_POINTS:
                raise KmzImportError("The KML's line has too many points (at most %d)" % MAX_POINTS)
            return "linear", {"name": _name(placemark, root, name), "line": points, "takeoff": None}
    points = []
    for placemark in placemarks:
        for point in _all(placemark, "Point"):
            points += _coordinates(point)[:1]
    if len(points) >= 2:
        if len(points) > MAX_POINTS:
            raise KmzImportError("The KML has too many points (at most %d)" % MAX_POINTS)
        return "waypoint", {
            "name": _name(None, root, name), "takeoff": None, "poi": None,
            "points": [{"lat": lat, "lon": lon, "height": None, "heading": None, "pitch": None, "photo": False,
                        "hover": 0, "ground": None} for lon, lat in points]}
    raise KmzImportError("The KML has no polygon, line or two or more points to make a route of")


def _coordinates_text(points):
    return " ".join(",".join(_number(v) for v in p) for p in points)


def _number(v):
    return ("%.9f" % v).rstrip("0").rstrip(".") if isinstance(v, float) else str(v)


def _placemark(name, geometry):
    return "<Placemark><name>%s</name>%s</Placemark>" % (escape(name), geometry)


def write_kml(name, shape, air):
    """
    The route as KML text.

    :param name: the route's name
    :param shape: ("polygon", [(lon, lat), ...]), ("line", [...]) or ("points", [...]): what the route was drawn as
    :param air: air.py's result: {"reference": "sea" | "surface" | "takeoff", "paths": [[[lon, lat, h], ...], ...]}
    """
    kind, points = shape
    points = [tuple(float(v) for v in p[:2]) for p in points]
    if kind == "polygon":
        ring = points + points[:1]
        drawn = [_placemark("Area", "<Polygon><outerBoundaryIs><LinearRing><coordinates>%s</coordinates></LinearRing>"
                                    "</outerBoundaryIs></Polygon>" % _coordinates_text(ring))]
    elif kind == "line":
        drawn = [_placemark("Center line", "<LineString><tessellate>1</tessellate><coordinates>%s</coordinates>"
                                           "</LineString>" % _coordinates_text(points))]
    else:
        drawn = [_placemark("Point %d" % (i + 1), "<Point><coordinates>%s</coordinates></Point>" % _coordinates_text([p]))
                 for i, p in enumerate(points)]
    sea = air.get("reference") == "sea"
    mode = "absolute" if sea else "relativeToGround"
    note = ("Heights above sea level." if sea else
            "Heights above the ground under the path." if air.get("reference") == "surface" else
            "Heights above the takeoff point, drawn above the ground under the path (the takeoff point's height is not set).")
    paths = [_placemark("Flight path %d" % (i + 1) if len(air.get("paths", [])) > 1 else "Flight path",
                        "<LineString><altitudeMode>%s</altitudeMode><coordinates>%s</coordinates></LineString>"
                        % (mode, _coordinates_text([(float(p[0]), float(p[1]), float(p[2])) for p in path])))
             for i, path in enumerate(air.get("paths", [])) if len(path) >= 2]
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<kml xmlns="%s"><Document><name>%s</name>'
            '<description>%s Made by the DJI Mission Planner for viewing; not a mission file.</description>'
            '<Folder><name>Route</name>%s</Folder><Folder><name>Flight path</name>%s</Folder></Document></kml>\n'
            % (KML_NS, escape(name), escape(note), "".join(drawn), "".join(paths)))


def file_name(name):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(name or "route"))[:60].strip("._") or "route"
