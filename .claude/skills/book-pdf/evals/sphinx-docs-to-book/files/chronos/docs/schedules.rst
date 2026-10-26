Schedules
=========

.. _schedule-kinds:

Kinds of schedules
------------------

Chronos knows four kinds of schedule. Each is a :class:`~chronos.Schedule`
built by :func:`chronos.every`:

==============  ===============================  ======================
Kind            Example phrase                   Builder call
==============  ===============================  ======================
Daily           ``every day at 07:00``           ``every(days=1)``
Weekly          ``every Monday``                 ``every(weekday=0)``
Monthly         ``the 15th of every month``      ``every(monthday=15)``
Nth weekday     ``the second Tuesday``           ``every(weekday=1, nth=2)``
==============  ===============================  ======================

.. warning::

   A monthly schedule on the 31st skips months that have fewer days.
   Use ``monthday=-1`` for "the last day of the month".

Combining schedules
-------------------

Schedules can be combined with ``|`` (either) and ``&`` (both):

.. code-block:: python

   from chronos import every

   payday = every(monthday=15) | every(monthday=-1)
   long_weekend = every(weekday=4) & every(nth=-1, weekday=4)

The *gap* between two occurrences is the time from one to the next. The
mean gap of a schedule over a window of :math:`n` occurrences is

.. math::

   \bar{g} = \frac{1}{n-1} \sum_{i=1}^{n-1} (t_{i+1} - t_i)

Exceptions
----------

Holidays and other exceptions are removed with :meth:`Schedule.excluding`.
