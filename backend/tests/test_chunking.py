"""Unit tests for app/search/chunking.py's pure functions that don't need network fixtures.
See docs/06-semantic-binding-lookup-plan.md for _resolved_property_bindings()'s design."""

from app.search.chunking import _resolved_property_bindings


def test_resolved_property_bindings_properties_only():
    resolved_properties_json = {
        "properties": [
            {"path": ["myProp"], "id": "http://example.org/myModel/myProp", "effectiveId": "http://example.org/myModel/myProp"},
            {"path": ["otherProp"], "effectiveId": "http://example.org/myModel/otherProp"},
        ],
    }

    bindings = _resolved_property_bindings(resolved_properties_json)

    assert bindings == [
        ("myProp", "http://example.org/myModel/myProp"),
        ("otherProp", "http://example.org/myModel/otherProp"),
    ]


def test_resolved_property_bindings_includes_defs_derived_entries():
    resolved_properties_json = {
        "defs": {
            "3": [
                {"path": ["lat"], "effectiveId": "http://www.w3.org/2003/01/geo/wgs84_pos#lat"},
                {"path": ["long"], "effectiveId": "http://www.w3.org/2003/01/geo/wgs84_pos#long"},
            ],
        },
        "properties": [
            {"path": ["location"], "ref": "3", "schema_type": "object"},
        ],
    }

    bindings = _resolved_property_bindings(resolved_properties_json)

    # The "properties" entry itself has no effectiveId (it's a ref, not a binding) -- only the
    # defs-derived entries it points at contribute rows, per the plan's "union of every
    # effectiveId found anywhere" algorithm; ref/defs pointers aren't walked or resolved.
    assert bindings == [
        ("lat", "http://www.w3.org/2003/01/geo/wgs84_pos#lat"),
        ("long", "http://www.w3.org/2003/01/geo/wgs84_pos#long"),
    ]


def test_resolved_property_bindings_skips_missing_or_null_effective_id():
    resolved_properties_json = {
        "properties": [
            {"path": ["hasBinding"], "effectiveId": "http://example.org/hasBinding"},
            {"path": ["noEffectiveId"]},  # key absent entirely
            {"path": ["nullEffectiveId"], "effectiveId": None},  # explicit null
        ],
    }

    bindings = _resolved_property_bindings(resolved_properties_json)

    assert bindings == [("hasBinding", "http://example.org/hasBinding")]


def test_resolved_property_bindings_deduplicates_identical_pairs():
    resolved_properties_json = {
        "properties": [
            {"path": ["a", "b"], "effectiveId": "http://example.org/x"},
        ],
        "defs": {
            "1": [
                # Same (path, uri) pair as above, reachable via a different def -- should collapse
                # to a single entry, preserving first-seen order.
                {"path": ["a", "b"], "effectiveId": "http://example.org/x"},
                {"path": ["c"], "effectiveId": "http://example.org/y"},
            ],
        },
    }

    bindings = _resolved_property_bindings(resolved_properties_json)

    assert bindings == [
        ("a.b", "http://example.org/x"),
        ("c", "http://example.org/y"),
    ]


def test_resolved_property_bindings_empty_input():
    assert _resolved_property_bindings({}) == []
    assert _resolved_property_bindings({"properties": [], "defs": {}}) == []
