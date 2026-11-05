"""Curated answers: approved texts that reach the user word for word.

The model only picks a topic. It never sees the text before the user does, so it has nothing to
reword. A topic costs one line in a tool description and no call, so questions that do not need
a curated answer are not slowed down. The texts are read at run time: changing one needs no new
agent version, while adding a topic does, because prompt agents hold the tool definition.
"""

from dataclasses import dataclass


class FinalAnswer(str):
    """A tool output that is the whole answer. The loop sends it as it is and skips the model
    call that would otherwise write the answer, unless the model asked for other tools too."""


@dataclass(frozen=True)
class CuratedAnswer:
    covers: str  # what the model matches on
    text: str  # what the user gets


# The contact details are invented, like the rest of Voltrieve.
CURATED_ANSWERS = {
    "contact": CuratedAnswer(
        "phone number, e-mail address, how to get in touch with Voltrieve",
        "You can call Voltrieve customer care on 020-000 000 or write to help@voltrieve.example. "
        "We answer within one working day.",
    ),
    "opening_hours": CuratedAnswer(
        "opening hours of Voltrieve",
        "Voltrieve customer care is open Monday to Friday 8 to 17 and Saturday 10 to 14. "
        "We are closed on Sundays and public holidays.",
    ),
    "roadside_assistance": CuratedAnswer(
        "breakdown, flat battery, towing or help on the road",
        "If your Voltrieve has broken down, call Voltrieve Roadside on 020-000 001, day and "
        "night. Keep your registration number at hand. If you are in danger, call 112 first.",
    ),
    "battery_emergency": CuratedAnswer(
        "smoke, fire, burning smell or other danger from the car or its battery",
        "Stop as soon as it is safe, leave the car and move well away from it. Call 112 and say "
        "that it is an electric car. Do not try to put out a battery fire yourself.",
    ),
    "cancel_test_drive": CuratedAnswer(
        "cancelling or moving a booked test drive",
        "To cancel or move a test drive, call 020-000 000 or write to help@voltrieve.example "
        "with your booking number, at the latest the day before.",
    ),
    "personal_data": CuratedAnswer(
        "seeing, correcting or deleting personal data, privacy, GDPR",
        "To see, correct or delete your personal data, write to privacy@voltrieve.example. We "
        "answer within 30 days.",
    ),
    "complaints": CuratedAnswer(
        "making a complaint about Voltrieve",
        "We are sorry to hear that. Send your complaint to complaints@voltrieve.example with "
        "your registration number or booking number. We answer within five working days.",
    ),
}


def curated_description() -> str:
    topics = "; ".join(f"{topic}: {answer.covers}" for topic, answer in CURATED_ANSWERS.items())
    return (
        "Get Voltrieve's approved answer, which reaches the user word for word. Topics: "
        f"{topics}. Only when the user's message itself asks for one of these. Not for questions "
        "about a car, a repair, a part, a price, stock or a specific dealer."
    )
