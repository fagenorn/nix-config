import unittest

from fixture.greet import greet


class GreetCheck(unittest.TestCase):
    def test_greet_names_the_person(self):
        self.assertEqual(greet("Ada"), "Hello, Ada.")


if __name__ == "__main__":
    unittest.main()
