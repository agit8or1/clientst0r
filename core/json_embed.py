"""Safe JSON for templates.

Data for page scripts goes into the page through Django's ``json_script``
filter, which escapes ``<``, ``>`` and ``&`` so no value can end the
``<script>`` element or open a new one. Never ``json.dumps(...)`` into a
template with ``|safe`` — replacing ``</`` is not enough (``<!--`` and
``<script`` still change how the browser parses a script element).

``jsonable`` normalises a payload the way the old ``json.dumps(default=str)``
calls did (dates, Decimals, UUIDs become strings), so ``json_script`` can
encode it.
"""
import json


def jsonable(value):
    return json.loads(json.dumps(value, default=str))
