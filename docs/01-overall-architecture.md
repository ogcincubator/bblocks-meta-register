# OGC Building Blocks Meta-Registry — Architecture Summary

## Problem

Building Blocks registers currently reference each other via raw URLs (e.g. in `imports` in `bblocks-config.yaml`).
These URLs are fragile: they break if a register moves host or repo, they're hard to remember and communicate, and they
expose implementation details (hosting infrastructure) in what should be a logical relationship.

## Concept

A central meta-registry — modelled after [w3id.org](https://w3id.org/) — that maps short, human-readable aliases to
register URLs. Instead of:

```yaml
imports:
  - https://raw.githubusercontent.com/acme-org/my-bblocks/main/build/register.json
```

you write:

```yaml
imports:
  - "@acme/my-bblocks"
```

## Structure

The meta-registry is a GitHub repository with a directory per org/user:

```
/
ogc/
  registers.yaml
acme/
  registers.yaml
...
index.json  ← compiled, published to GitHub Pages on every merge
```

Each `registers.yaml` declares the org and its registers:

```yaml
org:
  name: ACME Corp
  url: https://acme.example.com
  maintainers:
    - github: acmeuser
      email: user@acme.example.com

registers:
  my-bblocks: https://acme.example.com/my-bblocks/build/register.json
```

`index.json` (auto-generated) is a flat map for fast lookup:

```json
{
  "@ogc/main": "https://blocks.ogc.org/register.json",
  "@acme/my-bblocks": "https://acme.example.com/my-bblocks/build/register.json"
}
```

## Governance

- New orgs/users claim a namespace via Pull Request
- Each entry must declare org name, URL, and authorized maintainer GitHub usernames + emails
- Changes to an existing namespace require the PR author to be an authorized maintainer
- Manual review in the short term; process can evolve if adoption grows

## URL Stability

The meta-registry's own URL is routed through [w3id.org](https://w3id.org/) (e.g. `https://w3id.org/ogc/bblocks/`), so
if the underlying hosting ever changes, only a single [w3id.org](https://w3id.org/) redirect needs updating — all
consumers are unaffected.

**Availability note:** since every aliased import depends on `index.json` being reachable, the w3id redirect target
should point at a CDN-fronted copy rather than raw GitHub Pages — e.g. [jsdelivr](https://www.jsdelivr.com/)'s GitHub
mirror (`cdn.jsdelivr.net/gh/org/repo@branch/index.json`), which has its own edge caching and uptime independent of
GitHub. The tradeoff is cache staleness (jsdelivr caches GitHub content for about a week by default), so the publish
workflow should call jsdelivr's purge endpoint after every merge to keep newly-claimed namespaces resolvable promptly.

## Integration into Existing Tooling

`bblocks-config.yaml` gains a new optional key with a sensible default:

```yaml
meta-registry: https://w3id.org/ogc-bblocks/index.json  # can be overridden or nulled to disable
```

The postprocessor (`models.py` / `ImportedBuildingBlocks`) resolves `@`-prefixed import entries to URLs at startup by
fetching `index.json`. The compiled index is cacheable (ETag), so repeat runs in CI are cheap. Existing raw-URL imports
continue to work unchanged.

`bblocks-config-override.yml` composes naturally — a fork can point at a private meta-registry during development
without touching the committed config.

Backward compatibility — the existing default placeholder (resolves to the main OGC register) is kept as-is. The bblocks
repository template is updated to use `@ogc/main` instead, so new registers get the aliased form by default.

## Future: Implicit References via `bblocks://` URIs

Item-level `bblocks://` identifiers already exist independently of this meta-registry. Once `@org/register` aliases are
in place, the same scheme could embed a register alias directly in an item reference, e.g.:

```
bblocks://@acme/my-bblocks/some.bblock.identifier
```

This would let `bblock.json` dependencies and JSON Schema `$ref`s point at a specific bblock in another org's register
without the author ever writing out a raw URL. More importantly, it would make `imports` in `bblocks-config.yaml` *
*inferable rather than declared**: today an author must explicitly list every external register they depend on; if every
cross-register reference is already self-describing (`@org/register` embedded in the `bblocks://` URI itself), the
postprocessor can scan all `bblock.json` dependency lists and `$ref`s, collect the distinct `@org/register` aliases
actually referenced, and resolve/import them automatically — no manual `imports` upkeep, and no risk of a stale or
missing entry.

The bblocks-postprocessing tooling would need to:

- Parse the `@org/register` segment out of every `bblocks://` reference encountered (dependencies, `$ref`s) during a
  scan pass, before/instead of relying on a fixed `imports` list
- Resolve each distinct alias via the meta-registry's `index.json` (same resolution path already used for explicit
  `imports` entries)
- Fall back to the existing behavior when no `@org/register` segment is present (i.e. treat it as a same-register
  reference, as today)
- Keep explicit `imports` as an override/escape hatch (e.g. pinning a specific URL, or importing a register that isn't
  referenced by any single identifier yet)

This is a potential follow-on, not yet implemented — noted here so the URI design and the alias-resolution code path are
built with this extension in mind.

## What This Enables

- **Refactor-safe references** — registers can move hosts without breaking any downstream consumer
- **Discoverability** — the meta-registry doubles as a browsable directory of known OGC Building Block registers
- **Private registries** — teams can run their own meta-registry instance and point their `bblocks-config.yaml` at it
- **Consistency with `bblocks://`** — item-level references already use logical identifiers; this extends the same
  principle to register-level references