"""Generate the multi-page PDF in the seed corpus: the Front Desk Standard Operating Procedure.

The text is original, written for this project; Calderwick Health is a fictional organisation.
The PDF is committed to the repository, so this script only needs to be run to change it:

    python scripts/build_corpus_pdf.py

Requires reportlab (listed in requirements-dev.txt).
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer

OUTPUT = Path(__file__).resolve().parent.parent / "corpus" / "clinic-operations" / "front-desk-sop.pdf"
TITLE = "Front Desk Standard Operating Procedure"
REFERENCE = "SOP-OPS-014"

# (kind, content) - kind is one of: h2, h3, p, ul, ol
CONTENT: list[tuple[str, object]] = [
    ("h2", "1. Purpose and scope"),
    (
        "p",
        "This procedure describes how the front desk at every Calderwick Health clinic is run, from "
        "opening to closing. It applies to receptionists, to clinic managers covering the desk and to "
        "any member of staff who relieves the desk during breaks. Clinical decisions are outside its "
        "scope: the front desk never gives treatment advice.",
    ),
    ("h2", "2. Opening the clinic"),
    ("h3", "2.1 Before the doors open"),
    (
        "p",
        "The opening receptionist arrives by 07:30, thirty minutes before the first appointment at "
        "08:00, and works through the following steps in order.",
    ),
    (
        "ol",
        [
            "Disarm the alarm and switch on the lights in reception and the waiting area.",
            "Check the answerphone and the clinic inbox for cancellations received overnight, and "
            "update ClinicDesk.",
            "Count the cash float with a second member of staff and record it in the till log. The "
            "float is £100.",
            "Switch on the card terminal and print a test receipt.",
            "Print the day list for each clinician and place it in their treatment room.",
            "Check that the waiting area is clean, the water dispenser is full and the hand sanitiser "
            "is topped up.",
        ],
    ),
    ("p", "Unlock the front door at 07:50."),
    ("h3", "2.2 If the float is wrong"),
    (
        "p",
        "A difference of more than £5 between the float and the till log is reported to the clinic "
        "manager before the first payment is taken. The manager and the receptionist recount "
        "together and both sign the till log.",
    ),
    ("h2", "3. Checking patients in"),
    ("h3", "3.1 Greeting and identification"),
    (
        "p",
        "Greet each patient as they arrive and check them in on ClinicDesk within two minutes. Confirm "
        "identity by asking for three details: full name, date of birth and the first line of the "
        "address. Ask the patient to state them; do not read them out for the patient to agree.",
    ),
    ("h3", "3.2 New patients"),
    (
        "p",
        "A new patient completes the registration and consent form on the tablet before their first "
        "appointment. Ask new patients to arrive 10 minutes early for this. Check that an emergency "
        "contact and the name of the patient's GP practice have been entered.",
    ),
    ("h3", "3.3 Children and patients who need support"),
    (
        "p",
        "Patients under 16 must be accompanied by a parent or guardian, who stays in the building for "
        "the whole appointment. Offer a chaperone to any patient who asks for one; the duty clinician "
        "arranges it. An interpreter is booked through the clinic manager with at least 48 hours' "
        "notice, and relatives should not be used as interpreters for clinical conversations.",
    ),
    ("h3", "3.4 Keeping details current"),
    (
        "p",
        "At every visit, ask whether the patient's telephone number, email address or GP has changed, "
        "and update ClinicDesk straight away.",
    ),
    ("h2", "4. Late arrivals and missed appointments"),
    (
        "p",
        "If a patient has not arrived five minutes after the appointment time, telephone them once. "
        "What happens next depends on when, or whether, they arrive.",
    ),
    (
        "ul",
        [
            "Up to 10 minutes late: the patient is seen for the time remaining in the slot.",
            "More than 10 minutes late: the appointment is recorded as a late cancellation and the "
            "patient is offered the next available slot.",
            "Did not attend: record the appointment as missed at the end of the slot and send the "
            "missed appointment message from ClinicDesk the same day.",
        ],
    ),
    (
        "p",
        "Fees for late cancellations and missed appointments are set out in the Patient Cancellation "
        "and Refund Policy. Never argue about a fee at the desk; offer to refer it to the clinic "
        "manager.",
    ),
    ("h2", "5. Taking payments"),
    ("h3", "5.1 Payment methods"),
    (
        "p",
        "Take payment before the patient leaves. Card and contactless payments are preferred. Cash is "
        "accepted up to £200 per transaction. Cheques are not accepted. Email a receipt from "
        "ClinicDesk for every payment; print one only if the patient asks.",
    ),
    ("h3", "5.2 Insurance-funded patients"),
    (
        "p",
        "Before the first appointment, record the insurer's authorisation code and the number of "
        "sessions authorised. Without an authorisation code the patient pays in full and claims the "
        "cost back from their insurer. Collect any policy excess on the day of the first appointment.",
    ),
    ("h3", "5.3 Refunds at the desk"),
    (
        "p",
        "A receptionist may refund up to £60 without further approval. Larger refunds need the clinic "
        "manager. Refund to the card that was used; never refund a card payment in cash.",
    ),
    ("h2", "6. Telephone calls and messages"),
    (
        "p",
        "Answer calls within five rings, giving the clinic name and your first name. Messages left on "
        "the answerphone are returned within two working hours.",
    ),
    (
        "p",
        "The front desk does not give clinical advice by telephone. If a caller describes new or "
        "worsening symptoms, take their number and pass the message to the duty physiotherapist, who "
        "calls back the same working day. If a caller describes chest pain, difficulty breathing, "
        "loss of bladder or bowel control, or sudden weakness, tell them to call the emergency "
        "services immediately.",
    ),
    ("h2", "7. Confidentiality at the desk"),
    (
        "ul",
        [
            "Keep the privacy filter fitted to the reception screen and lock the screen when you step "
            "away.",
            "Never confirm to a caller or visitor whether someone is a patient or has an appointment, "
            "unless the patient has named that person in ClinicDesk as someone we may speak to.",
            "Do not use the speakerphone at the desk.",
            "Speak quietly when discussing personal details and offer the side room for anything "
            "sensitive.",
            "Paper containing patient details goes in the locked shredding bin at the end of each day.",
        ],
    ),
    ("h2", "8. Emergencies"),
    ("h3", "8.1 A patient or visitor is taken ill"),
    (
        "ol",
        [
            "Call for the duty clinician using the panic button under the desk.",
            "If the person has collapsed or is not breathing normally, call the emergency services and "
            "say that a defibrillator is on site.",
            "Fetch the defibrillator and the first-aid kit from the cabinet behind reception.",
            "Send a colleague to the front door to meet the ambulance crew.",
        ],
    ),
    ("p", "Afterwards, complete an incident form in the People Portal within 24 hours."),
    ("h3", "8.2 Fire alarm"),
    (
        "p",
        "When the alarm sounds, stop what you are doing. Take the visitor sign-in tablet, direct "
        "everyone in the waiting area to the nearest exit and go to the assembly point in the car "
        "park. Do not use the lift. The clinic manager, or the most senior person present, checks "
        "the day lists against the people at the assembly point. Nobody goes back inside until the "
        "fire service says it is safe.",
    ),
    ("h3", "8.3 Aggressive behaviour"),
    (
        "p",
        "Stay behind the desk, keep your voice level and do not argue. Press the panic button if you "
        "feel threatened. Staff are never expected to put themselves at risk, and the clinic manager "
        "may refuse further appointments to anyone who is abusive.",
    ),
    ("h2", "9. Closing the clinic"),
    (
        "p",
        "The last appointment on weekdays starts at 19:30 and the clinic closes at 20:00. The closing "
        "receptionist then works through the following steps.",
    ),
    (
        "ol",
        [
            "Check that every appointment of the day is marked as attended, cancelled or missed.",
            "Cash up: count the till, reconcile it with the ClinicDesk takings report and record both "
            "figures in the till log.",
            "Place takings above the £100 float in the safe. Cash is banked every Tuesday and Friday "
            "by the clinic manager.",
            "Switch off the card terminal, the screens and the water dispenser.",
            "Check that treatment rooms and toilets are empty, then lock the internal doors.",
            "Set the alarm and lock the front door. Nobody locks up alone: the last two members of "
            "staff leave together, no later than 20:15.",
        ],
    ),
    ("h2", "10. Document control"),
    (
        "p",
        "This procedure is owned by the Head of Operations and is reviewed every 12 months, or after "
        "any serious incident at a front desk. Suggestions for changes go to your clinic manager. The "
        "current version is always the one in the knowledge base; printed copies are for reference "
        "only.",
    ),
]


def build(output: Path = OUTPUT) -> Path:
    base = getSampleStyleSheet()
    ink = colors.HexColor("#0F172A")
    body = ParagraphStyle(
        "Body", parent=base["BodyText"], fontName="Helvetica", fontSize=10.5, leading=15.5,
        spaceAfter=7, textColor=ink,
    )
    title = ParagraphStyle(
        "DocTitle", parent=base["Title"], fontName="Helvetica-Bold", fontSize=22, leading=27,
        alignment=0, spaceAfter=4, textColor=ink,
    )
    meta = ParagraphStyle("Meta", parent=body, fontSize=9, leading=13, textColor=colors.HexColor("#475569"), spaceAfter=14)
    h2 = ParagraphStyle(
        "H2", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=14.5, leading=19,
        spaceBefore=16, spaceAfter=7, textColor=ink,
    )
    h3 = ParagraphStyle(
        "H3", parent=base["Heading3"], fontName="Helvetica-Bold", fontSize=11.8, leading=16,
        spaceBefore=10, spaceAfter=5, textColor=ink,
    )

    def decorate(canvas, document) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#64748B"))
        canvas.drawString(22 * mm, A4[1] - 14 * mm, f"Calderwick Health - {TITLE}")
        canvas.drawString(22 * mm, 12 * mm, f"{REFERENCE} - Version 6")
        canvas.drawRightString(A4[0] - 22 * mm, 12 * mm, f"Page {document.page}")
        canvas.restoreState()

    story: list = [
        Paragraph(TITLE, title),
        Paragraph(
            f"Calderwick Health - Operations - {REFERENCE} - Version 6 - Effective 1 March 2026 - "
            "Review due March 2027",
            meta,
        ),
    ]
    for kind, content in CONTENT:
        if kind == "h2":
            story.append(Paragraph(str(content), h2))
        elif kind == "h3":
            story.append(Paragraph(str(content), h3))
        elif kind == "p":
            story.append(Paragraph(str(content), body))
        elif kind in ("ul", "ol"):
            story.append(
                ListFlowable(
                    [ListItem(Paragraph(item, body), leftIndent=16) for item in content],  # type: ignore[union-attr]
                    bulletType="bullet" if kind == "ul" else "1",
                    bulletFontName="Helvetica",
                    bulletFontSize=10.5,
                    leftIndent=16,
                )
            )
            story.append(Spacer(1, 4))

    output.parent.mkdir(parents=True, exist_ok=True)
    document = SimpleDocTemplate(
        str(output), pagesize=A4, leftMargin=22 * mm, rightMargin=22 * mm, topMargin=24 * mm,
        bottomMargin=22 * mm, title=TITLE, author="Calderwick Health Operations (fictional)",
        subject="Synthetic sample document for the SourceWise demo", invariant=1,
    )
    document.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return output


if __name__ == "__main__":
    path = build()
    print(f"Wrote {path} ({path.stat().st_size:,} bytes)")
