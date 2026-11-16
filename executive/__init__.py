"""Business Overview: the MSP owner's dashboard.

A thin adapter layer over data the rest of the platform already keeps. Each
metric is a provider (executive.providers) that reads one source and returns a
MetricResult; it never invents a number. See docs/plans/EXECUTIVE_METRICS.md.
"""
