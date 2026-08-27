"""PRAHARI Celery worker: 6-hourly catalogue refresh + screening run.

Owns the schedule only. All domain logic (fetch, propagate, filter, screen,
score) lives in prahari_orbital and is called from here, never reimplemented.
"""
