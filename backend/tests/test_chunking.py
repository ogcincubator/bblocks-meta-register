"""Unit tests for app/search/chunking.py's pure functions that don't need network fixtures.
See docs/06-semantic-binding-lookup-plan.md for _resolved_property_bindings()'s design, its
"Example-derived bindings" addendum for _turtle_predicate_uris()/_example_bindings(), and its
"Ontology-derived bindings" addendum for _ontology_format()/_ontology_subject_uris()/
_ontology_bindings()."""

from app.search.chunking import (
    _example_bindings,
    _ontology_bindings,
    _ontology_format,
    _ontology_subject_uris,
    _resolved_property_bindings,
    _turtle_predicate_uris,
)


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


def test_ontology_format_from_extension():
    assert _ontology_format("https://example.org/x/ontology.ttl", None) == "turtle"
    assert _ontology_format("https://example.org/x/ontology.owl", None) == "xml"
    assert _ontology_format("https://example.org/x/ontology.rdf", "text/plain") == "xml"
    # Extension wins even when Content-Type would suggest otherwise.
    assert _ontology_format("https://example.org/x/ontology.ttl", "application/rdf+xml") == "turtle"


def test_ontology_format_falls_back_to_content_type_then_default():
    assert _ontology_format("https://example.org/x/ontology", "application/rdf+xml; charset=utf-8") == "xml"
    assert _ontology_format("https://example.org/x/ontology", "text/turtle") == "turtle"
    assert _ontology_format("https://example.org/x/ontology", None) == "turtle"


def test_ontology_subject_uris_collects_subjects_not_predicates():
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix ex: <https://vocab.acme.test/real#> .

    ex:MyClass a owl:Class ;
        rdfs:label "My Class" .

    ex:myProperty a owl:ObjectProperty ;
        rdfs:domain ex:MyClass .
    """

    # Subjects only -- owl:Class/owl:ObjectProperty (rdf:type objects) and rdfs:label/rdfs:domain
    # (predicates) are all borrowed vocabulary, not terms this ontology defines, so none of them
    # appear even though _turtle_predicate_uris() would collect exactly those instead.
    assert set(_ontology_subject_uris(ttl, "turtle")) == {
        "https://vocab.acme.test/real#MyClass",
        "https://vocab.acme.test/real#myProperty",
    }


def test_ontology_subject_uris_skips_blank_node_subjects():
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix ex: <https://vocab.acme.test/real#> .

    ex:MyClass a owl:Class ;
        owl:equivalentClass [ a owl:Restriction ] .
    """

    # The blank-node restriction is a real subject in the graph (of "a owl:Restriction"), but it
    # has no URI of its own, so only ex:MyClass should surface.
    assert _ontology_subject_uris(ttl, "turtle") == ["https://vocab.acme.test/real#MyClass"]


def test_ontology_subject_uris_skips_placeholder_namespace():
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix ex: <http://example.org/> .

    ex:PlaceholderClass a owl:Class .
    """

    assert _ontology_subject_uris(ttl, "turtle") == []


def test_ontology_subject_uris_parses_rdf_xml():
    rdf_xml = """<?xml version="1.0"?>
    <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
             xmlns:owl="http://www.w3.org/2002/07/owl#">
      <owl:Class rdf:about="https://vocab.acme.test/real#MyClass"/>
    </rdf:RDF>
    """

    assert _ontology_subject_uris(rdf_xml, "xml") == ["https://vocab.acme.test/real#MyClass"]


def test_ontology_subject_uris_malformed_document_returns_empty_not_raises():
    assert _ontology_subject_uris("this is not valid turtle {{{", "turtle") == []


def test_ontology_subject_uris_deduplicates_preserving_order():
    ttl = """
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix ex: <https://vocab.acme.test/real#> .

    ex:MyClass rdfs:label "First" ;
        rdfs:comment "Second triple, same subject" .
    """

    assert _ontology_subject_uris(ttl, "turtle") == ["https://vocab.acme.test/real#MyClass"]


def test_ontology_bindings_tags_path_as_constant_ontology_label():
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix ex: <https://vocab.acme.test/real#> .
    ex:MyClass a owl:Class .
    """

    assert _ontology_bindings(ttl, "turtle") == [("ontology", "https://vocab.acme.test/real#MyClass")]


def test_ontology_bindings_empty_input():
    assert _ontology_bindings("", "turtle") == []
