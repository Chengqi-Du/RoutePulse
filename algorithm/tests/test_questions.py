import unittest

from algorithm import parse_question


class QuestionTests(unittest.TestCase):
    def setUp(self):
        self.locations = {"Base S": "S", "Incident T": "T", "S": "S", "T": "T"}

    def test_supported_questions_and_normalization(self):
        cases = [
            ("  HOW CAN I GET FROM base s TO INCIDENT T?!  ", "route", "S", "T"),
            ("Why did the route change.", "why_changed", None, None),
            ("WHICH ROADS NEED CHECKING!", "needs_check", None, None),
            ("How can I get from S to T?", "route", "S", "T"),
        ]
        for question, intent, start, end in cases:
            with self.subTest(question=question):
                self.assertEqual(
                    parse_question(question, self.locations),
                    {"intent": intent, "start_node_id": start, "end_node_id": end},
                )

    def test_unknown_questions_and_locations_are_unsupported(self):
        for question in (
            "How can I get from Base S to Unknown?",
            "What is the safest road?",
            "Why did the route change now?",
            "???",
        ):
            with self.subTest(question=question):
                self.assertEqual(parse_question(question, self.locations)["intent"], "unsupported")

    def test_invalid_question_and_ambiguous_mapping_raise(self):
        with self.assertRaises(ValueError):
            parse_question("  ", self.locations)
        with self.assertRaises(ValueError):
            parse_question("Which roads need checking?", {"Base S": "S", "base s": "other"})
        with self.assertRaises(ValueError):
            parse_question("Which roads need checking?", {"Base S": ""})


if __name__ == "__main__":
    unittest.main()
