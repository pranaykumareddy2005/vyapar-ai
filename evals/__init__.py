"""AI evaluation harness for the conversational layer.

Separates *model accuracy* (does the provider return the right structured intent?)
from *business-operation correctness* (does the domain service return the right
number?). The two are measured independently, per the engineering brief.
"""
