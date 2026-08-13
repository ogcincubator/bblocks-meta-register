"""Unit tests for app/search/chunking.py's pure functions that don't need network fixtures.
See docs/06-semantic-binding-lookup-plan.md for _resolved_property_bindings()'s design, and its
"Example-derived bindings" addendum for _turtle_predicate_uris()/_example_bindings()."""

from app.search.chunking import _example_bindings, _resolved_property_bindings, _turtle_predicate_uris


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


def test_turtle_predicate_uris_collects_predicates_and_rdf_type():
    ttl = """
    @prefix sosa: <http://www.w3.org/ns/sosa/> .
    @prefix ex: <http://example.org/> .

    ex:obs1 a sosa:Observation ;
        sosa:observedProperty ex:temperature ;
        sosa:hasSimpleResult "21.5"^^<http://www.w3.org/2001/XMLSchema#double> .
    """

    # rdflib's default in-memory store doesn't preserve triple insertion order, so compare as a
    # set here -- de-duplication/order-preservation-among-duplicates is covered by the dedup test
    # below instead, where a real ordering guarantee (first-seen) is meaningful.
    assert set(_turtle_predicate_uris(ttl)) == {
        "http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
        "http://www.w3.org/ns/sosa/observedProperty",
        "http://www.w3.org/ns/sosa/hasSimpleResult",
        "http://www.w3.org/ns/sosa/Observation",
    }


def test_turtle_predicate_uris_skips_placeholder_namespaces():
    ttl = """
    @prefix ex: <http://example.org/> .
    ex:thing a ex:PlaceholderType ;
        ex:placeholderPredicate ex:other .
    """

    # rdf:type itself is a real, non-placeholder predicate -- only ex:PlaceholderType (the
    # rdf:type *object*, under example.org) and ex:placeholderPredicate (a predicate under
    # example.org) are filtered.
    assert _turtle_predicate_uris(ttl) == ["http://www.w3.org/1999/02/22-rdf-syntax-ns#type"]


def test_turtle_predicate_uris_deduplicates_preserving_order():
    ttl = """
    @prefix sosa: <http://www.w3.org/ns/sosa/> .
    @prefix ex: <http://example.org/real/> .
    ex:obs1 sosa:observedProperty ex:a .
    ex:obs2 sosa:observedProperty ex:b .
    """

    assert _turtle_predicate_uris(ttl) == ["http://www.w3.org/ns/sosa/observedProperty"]


def test_turtle_predicate_uris_malformed_snippet_returns_empty_not_raises():
    assert _turtle_predicate_uris("this is not valid turtle {{{") == []


def test_example_bindings_extracts_ttl_snippet_tagged_with_example_title():
    json_full_doc = {
        "examples": [
            {
                "title": "Sensor observation",
                "snippets": [
                    {"language": "json", "code": '{"foo": "bar"}'},
                    {
                        "language": "ttl",
                        "code": """
                        @prefix sosa: <http://www.w3.org/ns/sosa/> .
                        @prefix ex: <http://example.org/real/> .
                        ex:obs1 sosa:observedProperty ex:temperature .
                        """,
                    },
                ],
            }
        ]
    }

    bindings = _example_bindings(json_full_doc)

    assert bindings == [("example:Sensor observation", "http://www.w3.org/ns/sosa/observedProperty")]


def test_example_bindings_untitled_example_uses_index_as_label():
    json_full_doc = {
        "examples": [
            {"snippets": [{"language": "turtle", "code": "@prefix sosa: <http://www.w3.org/ns/sosa/> .\n"
                                                            "<http://example.org/real/x> sosa:observedProperty "
                                                            "<http://example.org/real/y> ."}]},
        ]
    }

    bindings = _example_bindings(json_full_doc)

    assert bindings == [("example:0", "http://www.w3.org/ns/sosa/observedProperty")]


def test_example_bindings_no_ttl_snippet_returns_empty():
    json_full_doc = {"examples": [{"title": "JSON only", "snippets": [{"language": "json", "code": "{}"}]}]}

    assert _example_bindings(json_full_doc) == []


def test_example_bindings_empty_input():
    assert _example_bindings({}) == []
    assert _example_bindings({"examples": []}) == []
