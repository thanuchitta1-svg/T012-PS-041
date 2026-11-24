
import unittest


def calculate_car_fee(hours):
    if hours <= 0:
        return 0
    if hours <= 2:
        return 40

    extra_hours = hours - 2
    fee = 40 + (extra_hours * 30)

    return min(fee, 300)


def calculate_bike_fee(hours):
    if hours <= 0:
        return 0
    if hours <= 2:
        return 15

    extra_hours = hours - 2
    fee = 15 + (extra_hours * 10)

    return min(fee, 80)


class TestParkingFees(unittest.TestCase):

    def test_car_first_two_hours(self):
        self.assertEqual(calculate_car_fee(2), 40)

    def test_car_extra_hour(self):
        self.assertEqual(calculate_car_fee(3), 70)

    def test_car_daily_cap(self):
        self.assertEqual(calculate_car_fee(24), 300)

    def test_bike_first_two_hours(self):
        self.assertEqual(calculate_bike_fee(2), 15)

    def test_bike_extra_hour(self):
        self.assertEqual(calculate_bike_fee(3), 25)

    def test_bike_daily_cap(self):
        self.assertEqual(calculate_bike_fee(24), 80)

    
    def test_car_zero_hours(self):
        self.assertEqual(calculate_car_fee(0), 0)

    def test_bike_zero_hours(self):
        self.assertEqual(calculate_bike_fee(0), 0)

    def test_car_daily_cap(self):
        self.assertEqual(calculate_car_fee(24), 300)

    def test_bike_daily_cap(self):
        self.assertEqual(calculate_bike_fee(24), 80)

    def test_car_long_duration(self):
        self.assertEqual(calculate_car_fee(30), 300)

    def test_bike_long_duration(self):
        self.assertEqual(calculate_bike_fee(30), 80)

if __name__ == "__main__":
    unittest.main()
