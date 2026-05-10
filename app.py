import os
import re
import json
from flask import Flask, request, jsonify, send_file, render_template
from werkzeug.utils import secure_filename

try:
    import fitz  # PyMuPDF
except Exception:
    fitz = None

app = Flask(__name__)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# -----------------------------
# APPLE HERZLIYA - LOCKED LOGIC
# -----------------------------

MEAT_STATIONS = [
    "grill",
    "chef special",
    "sandwich",
    "soup",
]

DAIRY_STATIONS = [
    "fish special",
    "pizza",
    "bakery",
    "veg/vegan",
    "vegetarian",
    "vegan",
]

ALLERGEN_MAP = {
    "gluten": "גלוטן",
    "wheat": "חיטה",
    "egg": "ביצים",
    "eggs": "ביצים",
    "mustard": "חרדל",
    "lupin": "לופין",
    "soy": "סויה",
    "soya": "סויה",
    "sesame": "שומשום",
    "milk": "חלב",
    "dairy": "חלב",
    "fish": "דגים",
    "nuts": "אגוזים",
    "peanut": "בוטנים",
    "peanuts": "בוטנים",
    "celery": "סלרי",
    "sulfites": "סולפיטים",
    "sulphites": "סולפיטים",
}


INGREDIENT_TRANSLATIONS = {
    "chicken breast": "חזה עוף",
    "bread crumbs": "פירורי לחם",
    "wheat flour": "קמח חיטה",
    "egg": "ביצים",
    "potato": "תפוח אדמה",
    "potatoes": "תפוחי אדמה",
    "tomatoes": "עגבניות",
    "tomato": "עגבנייה",
    "onion": "בצל",
    "garlic": "שום",
    "coriander": "כוסברה",
    "cilantro": "כוסברה",
    "chili": "צ׳ילי",
    "lemon": "לימון",
    "oregano": "אורגנו",
    "dijon mustard": "חרדל דיז׳ון",
    "extra-virgin olive oil": "שמן זית",
    "olive oil": "שמן זית",
    "canola oil": "שמן קנולה",
    "salt": "מלח",
    "black pepper": "פלפל שחור",
    "beef": "בקר",
    "lamb": "טלה",
    "salmon": "סלמון",
    "rice": "אורז",
    "tofu": "טופו",
    "tahini": "טחינה",
    "harissa": "אריסה",
    "matbucha": "מטבוחה",
    "ptitim": "פתיתים",
    "kubbeh": "קובה",
    "siniya": "סינייה",
}


def clean_text(text):
    if not text:
        return ""

    text = text.replace("\r", "\n")
    text = re.sub(r"\n{2,}", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = text.replace("and and", "and")
    text = text.replace("beaf", "beef")
    text = text.replace("tomatoes salad", "tomato salad")
    return text.strip()


def split_category_and_raw_kosher(raw_category):
    raw_category = clean_text(raw_category)

    if not raw_category:
        return "", ""

    match = re.search(r"^(.*?)\s*\((.*?)\)", raw_category)
    if match:
        category = match.group(1).strip()
        raw_kosher = match.group(2).strip()
        return category, raw_kosher

    return raw_category.strip(), ""


def kosher_by_station(category, raw_kosher=""):
    category_l = (category or "").lower().strip()

    # Salad Bar is manual / exception
    if "salad bar" in category_l:
        return ""

    for station in MEAT_STATIONS:
        if station in category_l:
            return "בשרי"

    for station in DAIRY_STATIONS:
        if station in category_l:
            return "חלבי"

    raw_l = (raw_kosher or "").lower()
    if raw_l == "meat":
        return "בשרי"
    if raw_l == "dairy":
        return "חלבי"

    return ""


def improve_dish_name(name):
    name = clean_text(name)

    replacements = {
        "Schnitzel & French Fries": "שניצל עוף וצ׳יפס",
        "Schnitzel and French Fries": "שניצל עוף וצ׳יפס",
        "Chicken Schnitzel": "שניצל עוף",
        "Crispy Chicken Breast": "שניצל עוף פריך",
        "Sweet & Sour Tofu": "טופו ברוטב חמוץ-מתוק",
        "Sweet and Sour Tofu": "טופו ברוטב חמוץ-מתוק",
        "Cheese Stuffed Salmon": "סלמון ממולא גבינות",
        "Brisket & Potato": "בריסקט ותפוחי אדמה",
        "Brisket and Potato": "בריסקט ותפוחי אדמה",
        "Meat Kubdari": "קובדרי בשר",
    }

    for eng, heb in replacements.items():
        if eng.lower() == name.lower():
            return heb

    return name


def improve_description(description):
    description = clean_text(description)

    replacements = {
        "Crispy coated chicken breast with French fries and tomato salad":
            "שניצל עוף פריך עם צ׳יפס וסלט עגבניות",
        "Crispy coated chicken breast with French fries and tomatoes salad":
            "שניצל עוף פריך עם צ׳יפס וסלט עגבניות",
        "Crispy coated chicken breast with French fries":
            "שניצל עוף פריך עם צ׳יפס",
    }

    for eng, heb in replacements.items():
        if eng.lower() == description.lower():
            return heb

    return description


def translate_ingredients(ingredients):
    ingredients = clean_text(ingredients)
    if not ingredients:
        return ""

    parts = [p.strip() for p in ingredients.split(",") if p.strip()]
    translated = []

    for item in parts:
        item_clean = re.sub(r"\(.*?\)", "", item).strip()
        item_l = item_clean.lower()

        heb = INGREDIENT_TRANSLATIONS.get(item_l, item_clean)
        if heb not in translated:
            translated.append(heb)

    return ", ".join(translated)


def extract_allergens(text):
    text_l = (text or "").lower()
    found = []

    for key, heb in ALLERGEN_MAP.items():
        if key in text_l and heb not in found:
            found.append(heb)

    order = ["גלוטן", "חיטה", "ביצים", "חלב", "דגים", "סויה", "שומשום", "חרדל", "לופין", "אגוזים", "בוטנים", "סלרי", "סולפיטים"]
    found.sort(key=lambda x: order.index(x) if x in order else 999)
    return ", ".join(found)


def parse_text_to_dish(raw_text):
    text = clean_text(raw_text)
    lines = [line.strip() for line in text.split("\n") if line.strip()]

    category_raw = ""
    name = ""
    description = ""
    ingredients = ""
    allergens = ""
    price = "55"

    # Find category line like: Chef Special (Meat)
    for line in lines:
        if "(" in line and ")" in line and any(x in line.lower() for x in ["meat", "dairy"]):
            category_raw = line
            break

    category, raw_kosher = split_category_and_raw_kosher(category_raw)
    kosher = kosher_by_station(category, raw_kosher)

    # Find price
    for line in lines:
        if re.fullmatch(r"\d+(\.\d+)?", line):
            price = line
            break

    # Find ingredients
    for i, line in enumerate(lines):
        if line.lower().startswith("ingredients"):
            ingredients = line.split(":", 1)[-1].strip()
            if not ingredients and i + 1 < len(lines):
                ingredients = lines[i + 1]
            break

    # Basic name + description detection
    if category_raw and category_raw in lines:
        idx = lines.index(category_raw)
        possible = lines[idx + 1: idx + 6]

        clean_possible = [
            x for x in possible
            if not re.fullmatch(r"\d+(\.\d+)?", x)
            and not x.lower().startswith("ingredients")
        ]

        if len(clean_possible) > 0:
            name = clean_possible[0]
        if len(clean_possible) > 1:
            description = clean_possible[1]

    # Fallback
    if not name and len(lines) > 0:
        name = lines[0]
    if not description and len(lines) > 1:
        description = lines[1]

    allergens = extract_allergens(ingredients + " " + text)

    return {
        "category": category,
        "kosher": kosher,
        "name_en": name,
        "name_he": improve_dish_name(name),
        "description_en": description,
        "description_he": improve_description(description),
        "ingredients_en": ingredients,
        "ingredients_he": translate_ingredients(ingredients),
        "allergens": allergens,
        "price": price
    }


def extract_text_from_pdf(file_path):
    if fitz is None:
        return ""

    doc = fitz.open(file_path)
    all_text = []

    for page in doc:
        all_text.append(page.get_text())

    doc.close()
    return "\n".join(all_text)


@app.route("/")
def home():
    try:
        return render_template("index.html")
    except Exception:
        return send_file("index.html")


@app.route("/extract", methods=["POST"])
def extract():
    raw_text = ""

    if "file" in request.files:
        file = request.files["file"]
        filename = secure_filename(file.filename)
        path = os.path.join(UPLOAD_FOLDER, filename)
        file.save(path)

        if filename.lower().endswith(".pdf"):
            raw_text = extract_text_from_pdf(path)
        else:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                raw_text = f.read()

    else:
        data = request.get_json(silent=True) or {}
        raw_text = data.get("text", "")

    dish = parse_text_to_dish(raw_text)

    return jsonify({
        "success": True,
        "raw_text": raw_text,
        "dish": dish
    })


@app.route("/normalize", methods=["POST"])
def normalize():
    data = request.get_json(silent=True) or {}

    raw_category = data.get("category", "")
    category, raw_kosher = split_category_and_raw_kosher(raw_category)
    kosher = kosher_by_station(category, raw_kosher)

    ingredients_en = data.get("ingredients_en") or data.get("ingredients") or ""
    description_en = data.get("description_en") or data.get("description") or ""
    name_en = data.get("name_en") or data.get("name") or ""

    dish = {
        "category": category,
        "kosher": kosher,
        "name_en": name_en,
        "name_he": improve_dish_name(data.get("name_he") or name_en),
        "description_en": description_en,
        "description_he": improve_description(data.get("description_he") or description_en),
        "ingredients_en": ingredients_en,
        "ingredients_he": translate_ingredients(data.get("ingredients_he") or ingredients_en),
        "allergens": data.get("allergens") or extract_allergens(ingredients_en),
        "price": data.get("price", "55")
    }

    return jsonify({
        "success": True,
        "dish": dish
    })


@app.route("/create-display", methods=["POST"])
def create_display():
    data = request.get_json(silent=True) or {}

    category = data.get("category", "")
    kosher = data.get("kosher", "")

    if "(" in category:
        clean_category, raw_kosher = split_category_and_raw_kosher(category)
        category = clean_category
        kosher = kosher or kosher_by_station(category, raw_kosher)

    display = {
        "kosher": kosher,
        "category": category,
        "name_he": data.get("name_he", ""),
        "name_en": data.get("name_en", ""),
        "description_he": data.get("description_he", ""),
        "description_en": data.get("description_en", ""),
        "ingredients_he": data.get("ingredients_he", ""),
        "ingredients_en": data.get("ingredients_en", ""),
        "allergens": data.get("allergens", ""),
        "price": data.get("price", "55")
    }

    return jsonify({
        "success": True,
        "display": display
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
