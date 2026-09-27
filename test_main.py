"""Run: python test_main.py"""
from main import ready_to_speak

# speaks on a finished sentence
assert ready_to_speak("Hello there.")
assert ready_to_speak("Really?")
assert ready_to_speak("Wow!")

# waits for more tokens
assert not ready_to_speak("Hel")
assert not ready_to_speak("Hello there")
assert not ready_to_speak("  ")

# doesn't split mid-number or mid-abbreviation
assert not ready_to_speak("It costs 3.5")
assert not ready_to_speak("Ask Dr.")
assert not ready_to_speak("Coffee, tea, etc.")

# flushes long run-ons and newlines even without punctuation
assert ready_to_speak("word " * 40)
assert ready_to_speak("line one\n")

print("ok")
