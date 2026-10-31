"""Generate the fictitious sample documents and their ground truth.

Writes to samples/documents/:
- quarterly-sales-report.pdf     digital, 2 pages: a simple table, a table with multi-line
                                 cells and a two-level header with merged cells
- purchase-order-48213.pdf       digital, 2 pages: one table of order lines that continues
                                 on the second page, with subtotal, VAT and total rows
- borderless-cost-statement.pdf  digital, 1 page: columns aligned with spaces, no ruling
                                 lines, indented items and subtotals
- scanned-delivery-schedule.pdf  image only: a printed table, rasterised with the
                                 Nutrient Python SDK, rotated slightly and given scan noise
- scanned-stock-count.pdf        image only: a denser table with small print, scanned at a
                                 low resolution with a stronger skew

and samples/ground-truth.json with every table as rows of cells. A merged cell keeps its
text in its first (top-left) cell; the cells it covers are empty strings. A cell printed on
several lines is one string with single spaces.

Every company, person and figure is invented.
"""

from __future__ import annotations

import json
import random
import tempfile
from pathlib import Path

from PIL import Image, ImageFilter
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

HERE = Path(__file__).resolve().parent
OUT = HERE / "documents"
COMPANY = "Ashgrove Office Supplies Ltd"
TMP = Path(".")  # working folder for intermediate files, set in main()

styles = getSampleStyleSheet()
BODY = ParagraphStyle("body", parent=styles["Normal"], fontName="Helvetica", fontSize=9.5, leading=12.5)
CELL = ParagraphStyle("cell", parent=BODY, fontSize=8.5, leading=10.5)
CELL_R = ParagraphStyle("cellr", parent=CELL, alignment=TA_RIGHT)
H1 = ParagraphStyle("h1", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=16, spaceAfter=4)
H2 = ParagraphStyle("h2", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=11.5, spaceBefore=10, spaceAfter=5)

GRID = [
    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#8a8f98")),
    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e6e8ec")),
    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
    ("FONTSIZE", (0, 0), (-1, -1), 8.5),
    ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ("TOPPADDING", (0, 0), (-1, -1), 3),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
]


def money(value: float) -> str:
    return f"{value:,.2f}"


def footer(c: canvas.Canvas, doc) -> None:
    c.saveState()
    c.setFont("Helvetica", 7.5)
    c.setFillColor(colors.HexColor("#555555"))
    c.drawString(20 * mm, 12 * mm, f"{COMPANY} - fictitious sample document")
    c.drawRightString(190 * mm, 12 * mm, f"Page {doc.page}")
    c.restoreState()


def numeric_style(table_rows: int, first_numeric_col: int) -> list:
    return [("ALIGN", (first_numeric_col, 1), (-1, table_rows - 1), "RIGHT")]


def picture_of_table(rows: list[list[str]], width_mm: float):
    """Draw a table, rasterise it with the Nutrient Python SDK and return it as a picture."""
    import nutrient_sdk as ns
    from reportlab.platypus import Image as RLImage

    t = Table(rows, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"), ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#3b4a5c")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#f0f3f7")]),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#c8cdd4")),
        ("ALIGN", (1, 1), (2, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    w, h = t.wrap(0, 0)
    pdf, png = TMP / "table.pdf", TMP / "table.png"
    c = canvas.Canvas(str(pdf), pagesize=(w + 8, h + 8))
    t.drawOn(c, 4, 4)
    c.showPage()
    c.save()
    with ns.Document.open(str(pdf)) as doc:
        doc.settings.image_settings.rasterization_dpi = 144
        doc.export_as_image(str(png))
    width = width_mm * mm
    return RLImage(str(png), width=width, height=width * (h + 8) / (w + 8), hAlign="LEFT")


# ---------------------------------------------------------------------------
# 1. Quarterly sales report: simple table, multi-line cells, two-level header
# ---------------------------------------------------------------------------

def sales_report(truth: dict) -> None:
    path = OUT / "quarterly-sales-report.pdf"
    story = [
        Paragraph("Quarterly sales report - Q3 2026", H1),
        Paragraph(f"{COMPANY}, sales and operations. Figures in euros unless stated otherwise.", BODY),
        Paragraph("1. Sales by region", H2),
        Paragraph("Orders, units and revenue invoiced between 1 July and 30 September 2026.", BODY),
        Spacer(1, 5),
    ]

    regions = [
        ("North", 412, 9_870, 186_420.50, "18.2%"),
        ("South", 377, 8_105, 152_310.00, "17.5%"),
        ("East", 298, 6_942, 131_877.25, "19.1%"),
        ("West", 351, 7_730, 144_905.75, "16.8%"),
        ("Central", 264, 5_418, 101_236.00, "20.3%"),
    ]
    rows = [["Region", "Orders", "Units", "Revenue (EUR)", "Margin"]]
    for name, orders, units, revenue, margin in regions:
        rows.append([name, f"{orders:,}", f"{units:,}", money(revenue), margin])
    rows.append(["Total", f"{sum(r[1] for r in regions):,}", f"{sum(r[2] for r in regions):,}",
                 money(sum(r[3] for r in regions)), "18.3%"])
    t = Table(rows, colWidths=[38 * mm, 24 * mm, 24 * mm, 34 * mm, 22 * mm], hAlign="LEFT")
    t.setStyle(TableStyle(GRID + numeric_style(len(rows), 1) + [("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold")]))
    story += [t]
    truth["quarterly-sales-report.pdf"] = [{"title": "Sales by region", "pages": [1], "rows": rows}]

    story += [
        Paragraph("2. Top product lines", H2),
        Paragraph("The five product lines with the highest revenue. Descriptions are those of the catalogue.", BODY),
        Spacer(1, 5),
    ]
    products = [
        ("PL-110", "Ergonomic task chairs", "Mesh back, adjustable lumbar support and 4D armrests; five-year warranty on the frame", 1_284, 98_412.00),
        ("PL-204", "Sit-stand desks", "Dual motor frame, 1600 x 800 mm laminate top, memory keypad with four heights", 642, 87_195.50),
        ("PL-031", "Printer paper A4", "80 g/m2, 500 sheets per ream, FSC certified, sold in boxes of five reams", 9_820, 41_244.00),
        ("PL-377", "Monitor arms", "Single and dual arms, gas spring, VESA 75 and 100, cable management clips included", 1_105, 38_675.00),
        ("PL-058", "Storage cabinets", "Steel, lockable, four adjustable shelves; delivered assembled to the ground floor", 213, 34_080.00),
    ]
    rows = [["Code", "Product line", "Description", "Units", "Revenue (EUR)"]]
    cells = [[Paragraph(h, ParagraphStyle("hdr", parent=CELL, fontName="Helvetica-Bold")) for h in rows[0]]]
    for code, line, desc, units, revenue in products:
        rows.append([code, line, desc, f"{units:,}", money(revenue)])
        cells.append([code, Paragraph(line, CELL), Paragraph(desc, CELL), f"{units:,}", money(revenue)])
    total = ["Total", "", "", f"{sum(p[3] for p in products):,}", money(sum(p[4] for p in products))]
    rows.append(total)
    cells.append(total)
    t = Table(cells, colWidths=[16 * mm, 30 * mm, 70 * mm, 18 * mm, 28 * mm], hAlign="LEFT")
    t.setStyle(TableStyle(GRID + numeric_style(len(rows), 3) + [("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold")]))
    story += [t]
    truth["quarterly-sales-report.pdf"].append({"title": "Top product lines", "pages": [1], "rows": rows})

    story += [
        Spacer(1, 6),
        Paragraph("Revenue of the five lines is 54% of the quarter. Paper volumes are down 6% on Q2 "
                  "as two framework customers moved to a digital-first policy.", BODY),
    ]

    # Page 2: two-level header with merged cells.
    from reportlab.platypus import PageBreak

    story += [
        PageBreak(),
        Paragraph("3. Headcount and staff cost by department", H2),
        Paragraph("Full-time equivalents at the end of the period, and staff cost in thousands of euros.", BODY),
        Spacer(1, 5),
    ]
    depts = [
        ("Sales", 42, 46, 2_310, 2_588),
        ("Warehouse and logistics", 57, 61, 2_052, 2_257),
        ("Customer service", 18, 17, 774, 748),
        ("Finance and administration", 11, 12, 682, 761),
        ("IT", 7, 9, 539, 702),
        ("Management", 5, 5, 610, 625),
    ]
    rows = [
        ["Department", "Headcount (FTE)", "", "Staff cost (EUR k)", ""],
        ["", "2025", "2026", "2025", "2026"],
    ]
    for d in depts:
        rows.append([d[0]] + [f"{v:,}" for v in d[1:]])
    rows.append(["Total"] + [f"{sum(d[i] for d in depts):,}" for i in range(1, 5)])
    t = Table(rows, colWidths=[52 * mm, 26 * mm, 26 * mm, 26 * mm, 26 * mm], hAlign="LEFT")
    t.setStyle(TableStyle(GRID + [
        ("SPAN", (0, 0), (0, 1)), ("SPAN", (1, 0), (2, 0)), ("SPAN", (3, 0), (4, 0)),
        ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#e6e8ec")),
        ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
        ("ALIGN", (1, 0), (-1, 1), "CENTER"), ("VALIGN", (0, 0), (0, 1), "MIDDLE"),
        ("ALIGN", (1, 2), (-1, -1), "RIGHT"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
    ]))
    story += [t, Spacer(1, 8), Paragraph("IT headcount includes two apprentices from September 2026.", BODY)]
    truth["quarterly-sales-report.pdf"].append({"title": "Headcount and staff cost by department", "pages": [2], "header_rows": 2, "rows": rows})

    # A table pasted as a picture (a screenshot of the order system): no text layer.
    story += [
        Paragraph("4. Open orders by status", H2),
        Paragraph("Screenshot of the order system dashboard, taken on 30 September 2026.", BODY),
        Spacer(1, 5),
    ]
    rows = [
        ["Status", "Orders", "Value (EUR)", "Oldest order"],
        ["Awaiting stock", "23", "41,870.00", "02/09/2026"],
        ["Ready to pick", "57", "68,215.40", "26/09/2026"],
        ["Picked, not shipped", "14", "19,032.75", "28/09/2026"],
        ["On hold (credit)", "6", "12,480.00", "15/08/2026"],
        ["Total", "100", "141,598.15", ""],
    ]
    story += [picture_of_table(rows, width_mm=120), Spacer(1, 6),
              Paragraph("Orders on credit hold are reviewed every Monday by the finance team.", BODY)]
    truth["quarterly-sales-report.pdf"].append({"title": "Open orders by status", "pages": [2], "rows": rows})

    SimpleDocTemplate(str(path), pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm,
                      bottomMargin=20 * mm, title="Quarterly sales report Q3 2026").build(
        story, onFirstPage=footer, onLaterPages=footer)


# ---------------------------------------------------------------------------
# 2. Purchase order: one table across two pages, subtotal, VAT and total rows
# ---------------------------------------------------------------------------

ITEMS = [
    ("A4-80-500", "Printer paper A4 80 g/m2, ream of 500", 40, 4.20),
    ("A3-80-500", "Printer paper A3 80 g/m2, ream of 500", 10, 8.95),
    ("ENV-DL-100", "Envelopes DL, window, box of 100", 25, 6.40),
    ("ENV-C4-250", "Envelopes C4, self-seal, box of 250", 6, 24.80),
    ("PEN-BLK-50", "Ballpoint pens black, box of 50", 12, 9.75),
    ("PEN-BLU-50", "Ballpoint pens blue, box of 50", 8, 9.75),
    ("HL-ASST-4", "Highlighters, assorted colours, pack of 4", 30, 3.10),
    ("NB-A5-RUL", "Notebook A5 ruled, 80 sheets", 60, 2.35),
    ("NB-A4-SQ", "Notebook A4 squared, 96 sheets", 40, 3.60),
    ("PI-POST-12", "Sticky notes 76 x 76 mm, pack of 12", 20, 7.90),
    ("STP-26-6", "Staples 26/6, box of 5000", 15, 1.85),
    ("STPL-DSK", "Desk stapler, 25 sheets", 10, 6.50),
    ("PNCH-2H", "Two-hole punch, 30 sheets", 6, 11.20),
    ("FLD-SUS-50", "Suspension files A4, box of 50", 8, 28.40),
    ("FLD-LVR-80", "Lever arch files A4, 80 mm, black", 48, 2.95),
    ("DIV-A4-10", "Dividers A4, 10 tabs, coloured", 50, 1.40),
    ("PKT-A4-100", "Punched pockets A4, box of 100", 20, 3.75),
    ("TAPE-19-33", "Clear tape 19 mm x 33 m, pack of 8", 15, 4.60),
    ("GLUE-40", "Glue stick 40 g", 36, 1.25),
    ("SCIS-210", "Scissors 210 mm, soft grip", 12, 3.80),
    ("RLR-30", "Ruler 30 cm, transparent", 24, 0.90),
    ("CALC-12D", "Desk calculator, 12 digits", 5, 14.90),
    ("WB-MRK-4", "Whiteboard markers, pack of 4", 18, 5.20),
    ("WB-ERS", "Whiteboard eraser, magnetic", 6, 3.45),
    ("BAT-AA-24", "Batteries AA alkaline, pack of 24", 10, 12.60),
    ("BAT-AAA-24", "Batteries AAA alkaline, pack of 24", 6, 12.60),
    ("LBL-A4-21", "Labels 70 x 42.3 mm, 21 per sheet, 100 sheets", 8, 15.30),
    ("TNR-K-201", "Toner cartridge black, 3,000 pages", 9, 68.00),
    ("TNR-C-201", "Toner cartridge cyan, 2,300 pages", 4, 74.50),
    ("TNR-M-201", "Toner cartridge magenta, 2,300 pages", 4, 74.50),
    ("TNR-Y-201", "Toner cartridge yellow, 2,300 pages", 4, 74.50),
    ("CLN-WIPE", "Screen cleaning wipes, tub of 100", 12, 4.15),
    ("MUG-ASH", "Mug with logo print, 300 ml", 50, 3.20),
    ("BIN-RCY-3", "Recycling bin, three compartments", 3, 46.00),
    ("CHR-MAT-1", "Chair mat for carpet, 120 x 90 cm", 4, 39.90),
    ("LMP-LED", "LED desk lamp, dimmable", 6, 27.50),
    ("FAN-DSK", "Desk fan, 30 cm, three speeds", 4, 22.80),
    ("HDS-USB", "USB headset with microphone", 10, 18.40),
    ("KBD-USB", "Keyboard, wired, UK layout", 8, 12.95),
    ("MSE-WL", "Wireless mouse with receiver", 12, 9.60),
    ("CBL-HDMI-2", "HDMI cable, 2 m", 15, 4.30),
    ("EXT-4W", "Extension lead, 4 sockets, 2 m", 10, 8.75),
    ("WTR-CUP-1K", "Paper water cups, box of 1000", 3, 19.90),
    ("TEA-BAG-6", "Tea bags, catering pack of 600", 4, 11.25),
]


def purchase_order(truth: dict) -> None:
    path = OUT / "purchase-order-48213.pdf"
    story = [
        Paragraph("Purchase order 48213", H1),
        Paragraph("Buyer: Kestrel Lane Dental Group, 14 Mill Street, Harwick HW3 2PL. "
                  f"Supplier: {COMPANY}, Unit 6, Fenton Trading Estate, Dunmere DM7 4QS.", BODY),
        Paragraph("Order date: 14 October 2026. Requested delivery: 21 October 2026. Payment terms: 30 days.", BODY),
        Spacer(1, 8),
    ]
    header = ["Line", "Item code", "Description", "Qty", "Unit price", "Amount"]
    rows = [header]
    subtotal = 0.0
    for i, (code, desc, qty, price) in enumerate(ITEMS, start=1):
        amount = qty * price
        subtotal += amount
        rows.append([str(i), code, desc, str(qty), money(price), money(amount)])
    vat = round(subtotal * 0.2, 2)
    rows.append(["", "", "Subtotal", "", "", money(subtotal)])
    rows.append(["", "", "VAT 20%", "", "", money(vat)])
    rows.append(["", "", "Total (EUR)", "", "", money(subtotal + vat)])
    t = Table(rows, colWidths=[11 * mm, 25 * mm, 72 * mm, 12 * mm, 20 * mm, 24 * mm], repeatRows=1, hAlign="LEFT")
    n = len(rows)
    t.setStyle(TableStyle(GRID + [
        ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
        ("FONTNAME", (2, n - 3), (-1, n - 1), "Helvetica-Bold"),
        ("BACKGROUND", (0, n - 1), (-1, n - 1), colors.HexColor("#f2f3f5")),
    ]))
    story += [t, Spacer(1, 10), Paragraph("Deliver to goods-in, rear entrance. Quote the order number on the delivery note.", BODY)]
    truth["purchase-order-48213.pdf"] = [{"title": "Order lines", "pages": [1, 2], "rows": rows}]
    SimpleDocTemplate(str(path), pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm,
                      bottomMargin=20 * mm, title="Purchase order 48213").build(story, onFirstPage=footer, onLaterPages=footer)


# ---------------------------------------------------------------------------
# 3. Borderless statement: text aligned in columns, no table structure
# ---------------------------------------------------------------------------

def borderless_statement(truth: dict) -> None:
    path = OUT / "borderless-cost-statement.pdf"
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setTitle("Project cost statement")
    w, h = A4
    c.setFont("Helvetica-Bold", 15)
    c.drawString(20 * mm, h - 25 * mm, "Project cost statement - showroom refit, Dunmere")
    c.setFont("Helvetica", 9.5)
    c.drawString(20 * mm, h - 32 * mm, "Prepared by the finance team, 28 October 2026. Amounts in euros, excluding VAT.")

    lines = [
        ("head", "Cost item", "Budget", "Actual", "Variance"),
        ("section", "Labour", "", "", ""),
        ("item", "Joinery and fit-out", "48,500.00", "51,240.00", "-2,740.00"),
        ("item", "Electrical installation", "22,000.00", "20,875.50", "1,124.50"),
        ("item", "Decoration", "9,600.00", "10,110.00", "-510.00"),
        ("subtotal", "Labour subtotal", "80,100.00", "82,225.50", "-2,125.50"),
        ("section", "Materials", "", "", ""),
        ("item", "Flooring", "14,250.00", "13,980.00", "270.00"),
        ("item", "Lighting fixtures", "11,400.00", "12,655.75", "-1,255.75"),
        ("item", "Display units", "26,800.00", "25,940.00", "860.00"),
        ("subtotal", "Materials subtotal", "52,450.00", "52,575.75", "-125.75"),
        ("section", "Other costs", "", "", ""),
        ("item", "Design fees", "7,500.00", "7,500.00", "0.00"),
        ("item", "Skip hire and waste", "1,800.00", "2,145.00", "-345.00"),
        ("subtotal", "Other costs subtotal", "9,300.00", "9,645.00", "-345.00"),
        ("total", "Total project cost", "141,850.00", "144,446.25", "-2,596.25"),
    ]
    x_label, x_cols = 22 * mm, [118 * mm, 152 * mm, 186 * mm]
    y = h - 48 * mm
    rows = []
    for kind, label, *vals in lines:
        font = "Helvetica-Bold" if kind in ("head", "section", "total") else "Helvetica"
        c.setFont(font, 9.5)
        indent = 6 * mm if kind == "item" else 0
        if kind == "subtotal":
            c.setFont("Helvetica-Oblique", 9.5)
        c.drawString(x_label + indent, y, label)
        for x, v in zip(x_cols, vals):
            c.drawRightString(x, y, v)
        rows.append([label, *vals])
        y -= 6.2 * mm if kind in ("subtotal", "head") else 5.4 * mm
        if kind in ("subtotal", "head"):
            y -= 1.2 * mm
    c.setFont("Helvetica", 9)
    c.drawString(20 * mm, y - 6 * mm, "A negative variance means the actual cost is above budget.")
    c.setFont("Helvetica", 7.5)
    c.drawString(20 * mm, 12 * mm, f"{COMPANY} - fictitious sample document")
    c.showPage()
    c.save()
    truth["borderless-cost-statement.pdf"] = [{"title": "Project cost statement", "pages": [1], "rows": rows}]


# ---------------------------------------------------------------------------
# 4. Scanned delivery schedule: printed, rasterised, noisy, slightly rotated
# ---------------------------------------------------------------------------

def scan_pdf(printed: Path, target: Path, rng: random.Random, dpi: int, angle: float, noise: float, quality: int) -> None:
    """Rasterise a printed page with the Nutrient Python SDK, as a scanner would, then add
    rotation, noise and JPEG compression, and save it as an image-only PDF."""
    import nutrient_sdk as ns

    png = TMP / "page.png"
    with ns.Document.open(str(printed)) as doc:
        doc.settings.image_settings.rasterization_dpi = dpi
        doc.export_as_image(str(png))
    page = Image.open(png).convert("L")
    page = page.rotate(angle, resample=Image.BICUBIC, expand=False, fillcolor=255)
    grain = Image.frombytes("L", page.size, rng.randbytes(page.size[0] * page.size[1]))
    page = Image.blend(page, grain, noise).filter(ImageFilter.GaussianBlur(0.5))
    page = page.point(lambda v: 255 if v > 236 else max(0, v - 12))
    scan = TMP / "scan.jpg"
    page.save(scan, "JPEG", quality=quality)
    c = canvas.Canvas(str(target), pagesize=A4)
    c.setTitle(target.stem.replace("-", " ").capitalize())
    c.drawImage(str(scan), 0, 0, width=A4[0], height=A4[1])
    c.showPage()
    c.save()


def scanned_schedule(truth: dict, rng: random.Random) -> None:
    deliveries = [
        ("DN-70411", "26/10/2026", "Kestrel Lane Dental Group", 4, 612, "Delivered"),
        ("DN-70412", "26/10/2026", "Orchard Row Primary School", 2, 288, "Delivered"),
        ("DN-70418", "27/10/2026", "Pennywell Veterinary Practice", 1, 96, "Delivered"),
        ("DN-70423", "27/10/2026", "Brightmoor Housing Trust", 6, 1005, "Delivered"),
        ("DN-70427", "28/10/2026", "Calder Street Library", 3, 431, "Part delivered"),
        ("DN-70430", "28/10/2026", "Thornbury Accountants LLP", 1, 74, "Delivered"),
        ("DN-70436", "29/10/2026", "Westfold Community Centre", 2, 352, "Delivered"),
        ("DN-70441", "30/10/2026", "Redcliffe Physiotherapy", 1, 118, "Rescheduled"),
        ("DN-70445", "30/10/2026", "Lowmoor Business Park Ltd", 5, 870, "Delivered"),
        ("DN-70452", "31/10/2026", "St Aldric's Medical Centre", 2, 264, "Booked"),
    ]
    rows = [["Delivery note", "Date", "Customer", "Pallets", "Weight (kg)", "Status"]]
    for d in deliveries:
        rows.append([d[0], d[1], d[2], str(d[3]), f"{d[4]:,}", d[5]])
    rows.append(["Total", "", "", str(sum(d[3] for d in deliveries)), f"{sum(d[4] for d in deliveries):,}", ""])

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        printed = tmp / "printed.pdf"
        story = [
            Paragraph("Delivery schedule - week 44", H1),
            Paragraph(f"{COMPANY}, Dunmere depot. Printed 31/10/2026 for the goods-out board.", BODY),
            Spacer(1, 8),
        ]
        t = Table(rows, colWidths=[24 * mm, 22 * mm, 56 * mm, 16 * mm, 22 * mm, 26 * mm], hAlign="LEFT")
        t.setStyle(TableStyle(GRID + [
            ("FONTSIZE", (0, 0), (-1, -1), 9), ("ALIGN", (3, 1), (4, -1), "RIGHT"),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story += [t, Spacer(1, 10), Paragraph("Driver to sign each delivery note. Part deliveries to be reported to the office.", BODY)]
        SimpleDocTemplate(str(printed), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=20 * mm).build(story)

        scan_pdf(printed, OUT / "scanned-delivery-schedule.pdf", rng, dpi=200, angle=-0.7, noise=0.06, quality=70)
    truth["scanned-delivery-schedule.pdf"] = [{"title": "Delivery schedule - week 44", "pages": [1], "rows": rows}]


def scanned_stock_count(truth: dict, rng: random.Random) -> None:
    """A denser table, scanned at a low resolution with a stronger skew."""
    items = [
        ("C-01-1", "A4-80-500", "Printer paper A4 80 g/m2", "ream", 1240, 1236),
        ("C-01-2", "A3-80-500", "Printer paper A3 80 g/m2", "ream", 310, 310),
        ("C-01-3", "ENV-DL-100", "Envelopes DL, window", "box", 188, 191),
        ("C-02-1", "ENV-C4-250", "Envelopes C4, self-seal", "box", 64, 64),
        ("C-02-2", "PEN-BLK-50", "Ballpoint pens black", "box", 97, 95),
        ("C-02-3", "PEN-BLU-50", "Ballpoint pens blue", "box", 83, 83),
        ("C-03-1", "HL-ASST-4", "Highlighters, assorted", "pack", 226, 220),
        ("C-03-2", "NB-A5-RUL", "Notebook A5 ruled", "each", 540, 548),
        ("C-03-3", "NB-A4-SQ", "Notebook A4 squared", "each", 415, 415),
        ("C-04-1", "PI-POST-12", "Sticky notes 76 x 76 mm", "pack", 132, 129),
        ("C-04-2", "STP-26-6", "Staples 26/6", "box", 305, 305),
        ("C-04-3", "FLD-LVR-80", "Lever arch files A4", "each", 612, 600),
        ("C-05-1", "DIV-A4-10", "Dividers A4, 10 tabs", "pack", 280, 284),
        ("C-05-2", "PKT-A4-100", "Punched pockets A4", "box", 147, 147),
        ("C-05-3", "TAPE-19-33", "Clear tape 19 mm", "pack", 96, 91),
        ("C-06-1", "GLUE-40", "Glue stick 40 g", "each", 358, 358),
        ("C-06-2", "BAT-AA-24", "Batteries AA alkaline", "pack", 72, 70),
        ("C-06-3", "LBL-A4-21", "Labels 70 x 42.3 mm", "box", 41, 41),
    ]
    rows = [["Bin", "SKU", "Description", "Unit", "System qty", "Counted", "Difference", "Checked"]]
    for bin_, sku, desc, unit, system, counted in items:
        diff = counted - system
        rows.append([bin_, sku, desc, unit, f"{system:,}", f"{counted:,}", f"{diff:+d}" if diff else "0", "yes" if diff else ""])
    system_total = sum(i[4] for i in items)
    counted_total = sum(i[5] for i in items)
    rows.append(["Total", "", "", "", f"{system_total:,}", f"{counted_total:,}", f"{counted_total - system_total:+d}", ""])
    printed = TMP / "stock.pdf"
    story = [
        Paragraph("Stock count - aisle C", H1),
        Paragraph(f"{COMPANY}, Dunmere depot. Count of 29 October 2026, second shift. Differences above 2% are checked twice.", BODY),
        Spacer(1, 8),
    ]
    t = Table(rows, colWidths=[16 * mm, 24 * mm, 46 * mm, 12 * mm, 20 * mm, 18 * mm, 20 * mm, 16 * mm], hAlign="LEFT")
    t.setStyle(TableStyle(GRID + [
        ("FONTSIZE", (0, 0), (-1, -1), 8), ("ALIGN", (4, 1), (6, -1), "RIGHT"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
    ]))
    story += [t, Spacer(1, 10), Paragraph("Counted by the night team; checked by the depot supervisor.", BODY)]
    SimpleDocTemplate(str(printed), pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=20 * mm).build(story)
    scan_pdf(printed, OUT / "scanned-stock-count.pdf", rng, dpi=130, angle=1.2, noise=0.08, quality=55)
    truth["scanned-stock-count.pdf"] = [{"title": "Stock count - aisle C", "pages": [1], "rows": rows}]


def main() -> None:
    global TMP
    OUT.mkdir(parents=True, exist_ok=True)
    workdir = tempfile.TemporaryDirectory()
    TMP = Path(workdir.name)
    rng = random.Random(44)
    truth: dict = {}
    sales_report(truth)
    purchase_order(truth)
    borderless_statement(truth)
    scanned_schedule(truth, rng)
    scanned_stock_count(truth, rng)
    for doc in truth.values():
        for table in doc:
            table.setdefault("header_rows", 1)
    (HERE / "ground-truth.json").write_text(json.dumps(truth, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    for name, tables in truth.items():
        print(f"{name}: {len(tables)} table(s), {sum(len(t['rows']) for t in tables)} rows")
    workdir.cleanup()


if __name__ == "__main__":
    main()
