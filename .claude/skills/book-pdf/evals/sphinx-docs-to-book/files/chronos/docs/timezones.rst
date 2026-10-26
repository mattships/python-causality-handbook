Time zones
==========

Attach a time zone with ``tz=`` and Chronos keeps wall-clock times across
daylight-saving changes:

.. code-block:: python

   from zoneinfo import ZoneInfo
   standup = Schedule.parse("every weekday at 09:30", tz=ZoneInfo("Europe/Lisbon"))

.. tip::

   Store schedules in UTC only if the event really happens at a fixed
   instant (a satellite pass); meetings follow local time.
