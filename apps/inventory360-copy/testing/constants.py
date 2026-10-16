"""
testing/constants.py
======================
Values shared by the AI Accuracy page (human review) and the Ask Inventory360
page (thumbs feedback) so the two can never drift apart:

  APP_VERSION_DEFAULT : the version tag stamped on test runs AND user-feedback rows
  HUMAN_REASONS       : the "why was it wrong" options. First entry "" = no reason (Pass /
                        not yet reviewed). The chat page's "Not quite" menu offers HUMAN_REASONS[1:].
  RUN_TYPES           : the three kinds of rows in test_runs / test_results
"""

APP_VERSION_DEFAULT = "v1.0"

HUMAN_REASONS = [
    "", "Inaccurate number", "Error / no response", "Out of scope", "Took too long", "Unhappy with summary language",
]
FAIL_REASONS = HUMAN_REASONS[1:]

# benchmark : scored by the LLM judge against expected values (NOT part of human accuracy)
# bulk/repeat: "actual testing" — a person reviews the answers on the AI Accuracy page
# user      : thumbs up / "Not quite" given by end users on the Ask Inventory360 page
# Human accuracy = bulk + repeat + user.
HUMAN_ACCURACY_RUN_TYPES = ("bulk", "repeat", "user")
TESTED_RUN_TYPES = ("bulk", "repeat")
