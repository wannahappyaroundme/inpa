from datetime import date

from django.test import SimpleTestCase

from .calendar import add_calendar_months, new_anchor, period_for


class CalendarBillingTests(SimpleTestCase):
    def test_fifth_to_fifth(self):
        period = period_for(date(2027, 1, 5), 1, anchor_day=5)
        self.assertEqual(period.access_through, date(2027, 2, 4))
        self.assertEqual(period.next_charge_date, date(2027, 2, 5))

    def test_eighth_to_eighth(self):
        period = period_for(date(2027, 2, 8), 1, anchor_day=8)
        self.assertEqual(period.access_through, date(2027, 3, 7))
        self.assertEqual(period.next_charge_date, date(2027, 3, 8))

    def test_month_end_clamps_then_restores_original_anchor(self):
        february = add_calendar_months(
            date(2027, 1, 31), 1, anchor_day=31)
        march = add_calendar_months(february, 1, anchor_day=31)
        self.assertEqual(february, date(2027, 2, 28))
        self.assertEqual(march, date(2027, 3, 31))

    def test_leap_year(self):
        self.assertEqual(
            add_calendar_months(date(2028, 1, 31), 1, anchor_day=31),
            date(2028, 2, 29),
        )

    def test_rejects_invalid_period_inputs(self):
        for months, anchor_day in ((0, 1), (1, 0), (1, 32)):
            with self.subTest(months=months, anchor_day=anchor_day):
                with self.assertRaisesMessage(
                        ValueError, 'INVALID_CALENDAR_PERIOD'):
                    add_calendar_months(
                        date(2027, 1, 1), months,
                        anchor_day=anchor_day)

    def test_new_anchor_preserves_local_calendar_day(self):
        self.assertEqual(new_anchor(date(2027, 1, 31)), 31)
