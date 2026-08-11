"""Cross-cutting concerns shared by all domain modules.

Nothing in ``common`` may import a domain module; dependencies flow one way
(domains depend on common, never the reverse).
"""
