# Coding Standards

## Standards

- SHOULD prefer dataclasses over plain dicts for typed payloads.
- SHOULD raise typed `KeystoneError` subclasses at boundaries; do not return empty results.
- SHOULD keep adapters free of business logic — they fetch and classify only.
- MAY use `Protocol` for adapter interfaces; inheritance is not required.

## Rationale

The broker's value is making organizational constraints machine-readable. Typed
errors and typed payloads are how that contract survives across adapters. Adapter
modules stay small and replaceable when business logic lives in the resolver.
