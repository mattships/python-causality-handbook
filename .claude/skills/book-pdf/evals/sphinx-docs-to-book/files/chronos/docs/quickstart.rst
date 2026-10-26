Quickstart
==========

Install Chronos from PyPI:

.. code-block:: console

   $ pip install chronos-schedules

A schedule describes when something happens. Ask it for the next few
occurrences after a given moment:

.. code-block:: python

   from datetime import datetime
   from chronos import Schedule

   standup = Schedule.parse("every weekday at 09:30")
   for when in standup.upcoming(datetime(2024, 3, 1), count=3):
       print(when)

.. note::

   Times are naive unless you attach a time zone; see :doc:`timezones`.

The result of the loop above is::

   2024-03-01 09:30:00
   2024-03-04 09:30:00
   2024-03-05 09:30:00

.. versionadded:: 2.0
   ``Schedule.parse`` accepts English phrases.

Next, read :ref:`schedule-kinds` for everything a schedule can express.
