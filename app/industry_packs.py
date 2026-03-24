"""
Industry starter packs.
Each pack pre-fills line items, notes, tax label, default template and accent color.
"""
from dataclasses import dataclass, field


@dataclass
class IndustryPack:
    id:            str
    label:         str
    icon:          str
    description:   str
    template:      str
    accent_color:  str
    tax_label:     str
    default_terms: str
    line_items:    list[dict]   # [{description, qty, unit_price}]
    notes:         str

ACCENT        = "#2563EB"

PACKS: list[IndustryPack] = [

    IndustryPack(
        id="freelancer",
        label="Freelancer",
        icon="app/assets/freelancer.png",
        description="Design, development, writing & digital services",
        template="Modern",
        accent_color=ACCENT,
        tax_label="Tax",
        default_terms="Net 30",
        line_items=[
            {"description": "Design / Development Work", "qty": 1,  "unit_price": 0.00},
            {"description": "Revisions",                 "qty": 2,  "unit_price": 0.00},
            {"description": "Project Management",        "qty": 1,  "unit_price": 0.00},
        ],
        notes=(
            "Payment due within 30 days of invoice date.\n"
            "Late payments subject to 1.5% monthly interest.\n"
            "Thank you for your business!"
        ),
    ),
    IndustryPack(
        id="creative",
        label="Creative",
        icon="app/assets/camera.png",
        description="Photography, videography, music & content creation",
        template="Minimalist",
        accent_color=ACCENT,
        tax_label="Tax",
        default_terms="Net 14",
        line_items=[
            {"description": "Session / Shoot Fee",  "qty": 1, "unit_price": 0.00},
            {"description": "Editing & Post",       "qty": 1, "unit_price": 0.00},
            {"description": "Licensing Fee",        "qty": 1, "unit_price": 0.00},
            {"description": "Travel & Expenses",    "qty": 1, "unit_price": 0.00},
        ],
        notes=(
            "50% deposit required to secure booking.\n"
            "Final payment due before delivery of files.\n"
            "All images remain copyright of the photographer until paid in full."
        ),
    ),
    IndustryPack(
        id="consultant",
        label="Consultant",
        icon="app/assets/consultant.png",
        description="IT, marketing, HR, coaching & business consulting",
        template="Consultant",
        accent_color=ACCENT,
        tax_label="Tax",
        default_terms="Net 30",
        line_items=[
            {"description": "Consulting / Strategy",  "qty": 1,  "unit_price": 0.00},
            {"description": "Hourly Advisory",        "qty": 5,  "unit_price": 0.00},
            {"description": "Report / Deliverable",   "qty": 1,  "unit_price": 0.00},
            {"description": "Expenses",               "qty": 1,  "unit_price": 0.00},
        ],
        notes=(
            "Payment due within 30 days.\n"
            "Retainer fees are non-refundable.\n"
            "Expenses billed at cost with receipts available on request."
        ),
    ),
    IndustryPack(
        id="trades",
        label="Trades",
        icon="app/assets/trade.png",
        description="Electrical, plumbing, HVAC & general contracting",
        template="Professional",
        accent_color=ACCENT,
        tax_label="GST/HST",
        default_terms="Due on receipt",
        line_items=[
            {"description": "Labor",            "qty": 1, "unit_price": 0.00},
            {"description": "Materials",        "qty": 1, "unit_price": 0.00},
            {"description": "Call-out Fee",     "qty": 1, "unit_price": 0.00},
            {"description": "Disposal / Waste", "qty": 1, "unit_price": 0.00},
        ],
        notes=(
            "Payment due upon receipt.\n"
            "A 50% deposit may be required for large jobs.\n"
            "All materials remain property of contractor until paid in full."
        ),
    ),
    IndustryPack(
        id="home_services",
        label="Home Services",
        icon="app/assets/home.png",
        description="Cleaning, landscaping, handyman, painting, HVAC",
        template="Professional",
        accent_color=ACCENT,       # matches Trades orange family
        tax_label="GST/HST",
        default_terms="Due on completion",
        line_items=[
            {"description": "Labor / Service Time",     "qty": 4, "unit_price": 0.00},
            {"description": "Materials & Supplies",     "qty": 1, "unit_price": 0.00},
            {"description": "Travel / Call-out Fee",    "qty": 1, "unit_price": 0.00},
            {"description": "Disposal / Cleanup",       "qty": 1, "unit_price": 0.00},
        ],
        notes=(
            "Payment due upon completion of work.\n"
            "Materials remain property of contractor until paid in full.\n"
            "Satisfaction guaranteed — let us know if anything needs adjustment."
        ),
    ),
    IndustryPack(
        id="wellness",
        label="Health & Wellness",
        icon="app/assets/wellness.png",
        description="Personal trainers, massage, yoga, nutrition coaching",
        template="Consultant",
        accent_color=ACCENT,       # fresh blue-green — wellness vibe
        tax_label="Tax",
        default_terms="Net 15",
        line_items=[
            {"description": "Session / Class Package",   "qty": 1,  "unit_price": 0.00},
            {"description": "Private Coaching (hours)",  "qty": 4,  "unit_price": 0.00},
            {"description": "Custom Plan / Program",     "qty": 1,  "unit_price": 0.00},
            {"description": "Supplements / Products",    "qty": 1,  "unit_price": 0.00},
        ],
        notes=(
            "Payment due within 15 days.\n"
            "Packages are non-refundable once sessions begin.\n"
            "Cancellations with <24h notice are charged in full.\n"
            "Thank you for investing in your health!"
        ),
    ),
    IndustryPack(
        id="events",
        label="Events & Weddings",
        icon="app/assets/party.png",
        description="Planners, photographers, venues, DJs, caterers",
        template="Minimalist",
        accent_color=ACCENT,       # vibrant purple — celebratory
        tax_label="Tax",
        default_terms="50% Deposit, Balance Due 7 days before event",
        line_items=[
            {"description": "Booking / Reservation Deposit", "qty": 1, "unit_price": 0.00},
            {"description": "Full Service Package",          "qty": 1, "unit_price": 0.00},
            {"description": "Travel / Setup Fee",            "qty": 1, "unit_price": 0.00},
            {"description": "Additional Hours / Add-ons",    "qty": 1, "unit_price": 0.00},
        ],
        notes=(
            "50% non-refundable deposit secures your date.\n"
            "Balance due 7 days prior to event.\n"
            "Cancellations within 30 days are non-refundable.\n"
            "Looking forward to making your day unforgettable!"
        ),
    ),
    IndustryPack(
        id="retail",
        label="Retail / E-commerce",
        icon="app/assets/retail.png",
        description="Product sales, online store, shipping & taxes",
        template="Professional",
        accent_color=ACCENT,       # warm red — retail energy
        tax_label="Sales Tax",
        default_terms="Due on receipt",
        line_items=[
            {"description": "Product / Item Sales",     "qty": 1, "unit_price": 0.00},
            {"description": "Shipping & Handling",      "qty": 1, "unit_price": 0.00},
        ],
        notes=(
            "Thank you for your order!\n"
            "Items remain property of seller until payment is received in full.\n"
            "Returns accepted within 14 days with original packaging."
        ),
    ),
    IndustryPack(
        id="real_estate",
        label="Real Estate",
        icon="app/assets/real-estate.png",
        description="Agents, property managers, rentals, maintenance",
        template="Modern",
        accent_color=ACCENT,       # professional indigo
        tax_label="Tax",
        default_terms="Due on receipt",
        line_items=[
            {"description": "Commission / Service Fee",     "qty": 1, "unit_price": 0.00},
            {"description": "Rental Management Fee",        "qty": 1, "unit_price": 0.00},
            {"description": "Maintenance / Repair Work",    "qty": 1, "unit_price": 0.00},
            {"description": "Security Deposit Return Adj.", "qty": 1, "unit_price": 0.00},
        ],
        notes=(
            "Payment due upon receipt or as per agreement.\n"
            "All fees are non-refundable unless otherwise stated.\n"
            "Thank you for your trust in our services."
        ),
    ),
]

PACKS_BY_ID: dict[str, IndustryPack] = {p.id: p for p in PACKS}