"""
Seed initial testimonials so the /testimonials page is not empty on first deploy.
Run after migrations: python -m scripts.seed_testimonials
Idempotent: inserts missing rows only (no duplicates).
"""
import sys
from pathlib import Path

# Ensure app is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from app.core.database import engine


SEED = [
    {"title": "Smooth process", "quote": "They found exactly the car I wanted and made the paperwork easy.", "author": "Maria L.", "sort_order": 10},
    {"title": "Best price", "quote": "Compared several brokers. NewCarSuperstore had the best lease deal by far.", "author": "James K.", "sort_order": 20},
    {"title": "No pressure", "quote": "Professional and straightforward. No pushy sales tactics.", "author": "David R.", "sort_order": 30},
    {"title": "Fast approval", "quote": "Credit and payment options were clear and quick to approve.", "author": "Nicole T.", "sort_order": 40},
    {"title": "Great communication", "quote": "I always got updates and never had to chase anyone.", "author": "Samir P.", "sort_order": 50},
    {"title": "Delivered as promised", "quote": "Everything matched the quote and timeline exactly.", "author": "Angela W.", "sort_order": 60},
    {"title": "Easy trade-in", "quote": "They handled my trade-in smoothly and fairly.", "author": "Chris D.", "sort_order": 70},
    {"title": "Transparent numbers", "quote": "No hidden fees, just clear numbers from start to finish.", "author": "Olivia H.", "sort_order": 80},
    {"title": "Excellent support", "quote": "Their team answered every question with patience.", "author": "Brian C.", "sort_order": 90},
    {"title": "Perfect SUV", "quote": "They matched me with the exact SUV my family needed.", "author": "Erica N.", "sort_order": 100},
    {"title": "First-time buyer friendly", "quote": "As a first-time buyer, I felt guided the whole way.", "author": "Kevin M.", "sort_order": 110},
    {"title": "Worth the referral", "quote": "A friend recommended them and they exceeded expectations.", "author": "Patricia S.", "sort_order": 120},
    {"title": "Simple paperwork", "quote": "The paperwork process was organized and surprisingly quick.", "author": "Andre B.", "sort_order": 130},
    {"title": "Lease expert", "quote": "They explained lease terms clearly and found a better offer.", "author": "Lena G.", "sort_order": 140},
    {"title": "No dealership stress", "quote": "No haggling stress, just practical options and results.", "author": "Rafael V.", "sort_order": 150},
    {"title": "Great value", "quote": "I saved money compared to every other quote I had.", "author": "Monica A.", "sort_order": 160},
    {"title": "Quick turnaround", "quote": "From inquiry to keys took less time than expected.", "author": "Tyler F.", "sort_order": 170},
    {"title": "Professional team", "quote": "Professional, responsive, and respectful throughout.", "author": "Jasmine R.", "sort_order": 180},
    {"title": "Best monthly payment", "quote": "They got my monthly payment where I needed it.", "author": "Noah E.", "sort_order": 190},
    {"title": "Reliable guidance", "quote": "Advice was practical and tailored to my budget.", "author": "Heather L.", "sort_order": 200},
    {"title": "Great selection", "quote": "They found options I could not find on my own.", "author": "Victor Y.", "sort_order": 210},
    {"title": "Efficient process", "quote": "Everything moved quickly without feeling rushed.", "author": "Sophie K.", "sort_order": 220},
    {"title": "Honest and clear", "quote": "They were honest about availability and pricing.", "author": "Derek J.", "sort_order": 230},
    {"title": "Strong follow-through", "quote": "They followed through on every detail and promise.", "author": "Alyssa Q.", "sort_order": 240},
    {"title": "Helpful after delivery", "quote": "Support continued even after I took delivery.", "author": "George I.", "sort_order": 250},
    {"title": "Family car win", "quote": "We found a safe family vehicle at the right price.", "author": "Nina Z.", "sort_order": 260},
    {"title": "Clear timelines", "quote": "I knew exactly what to expect at every step.", "author": "Carlos U.", "sort_order": 270},
    {"title": "Top-notch service", "quote": "Friendly and efficient service from beginning to end.", "author": "Megan O.", "sort_order": 280},
    {"title": "Highly recommend", "quote": "I would absolutely recommend them to friends and family.", "author": "Ethan P.", "sort_order": 290},
    {"title": "Stress-free deal", "quote": "The whole deal felt smooth, fair, and stress-free.", "author": "Grace X.", "sort_order": 300},
]


def main():
    with engine.connect() as conn:
        existing = conn.execute(text("SELECT quote, author FROM testimonials")).fetchall()
        existing_keys = {(str(row.quote), str(row.author)) for row in existing}
        inserted = 0
        for row in SEED:
            key = (row["quote"], row["author"])
            if key in existing_keys:
                continue
            conn.execute(
                text("""
                    INSERT INTO testimonials (title, quote, author, sort_order)
                    VALUES (:title, :quote, :author, :sort_order)
                """),
                row
            )
            inserted += 1
        conn.commit()
    print(f"Inserted {inserted} testimonials. Target seed size: {len(SEED)}.")


if __name__ == "__main__":
    main()
