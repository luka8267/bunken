import unittest

from auth_utils import MIN_PASSWORD_LENGTH, validate_password


class PasswordValidationTests(unittest.TestCase):
    def test_password_requires_twelve_characters(self):
        with self.assertRaises(ValueError):
            validate_password("short")

    def test_password_accepts_the_minimum_length(self):
        password = "a" * MIN_PASSWORD_LENGTH
        validate_password(password)


if __name__ == "__main__":
    unittest.main()
