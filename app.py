import os
import re
import json
from flask import Flask, request, jsonify, render_template
from werkzeug.utils import secure_filename

try:
    import fitz
except Exception:
    fitz = None

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

app = Flask(__name__)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY) if OpenAI and OPENAI_API_KEY else None

MEAT_STATIONS = ["grill", "chef special", "sandwich", "soup", "sushi", "meat station", "chicken station"]
DAIRY_STATIONS = ["fish special", "pizza", "bakery", "veg", "vegan", "vegetarian", "fish station", "pizza station"]

ALLERGEN_PATTERNS = {
    r"\bgluten\b": ("Gluten", "גלוטן"),
    r"\bwheat\b": ("Wheat", "חיטה"),
    r"\begg\b|\beggs\b": ("Eggs", "ביצים"),
    r"\bmilk\b|\bdairy\b": ("Milk", "חלב"),
    r"\bsoy\b|\bsoya\b|\bsoybeans\b": ("Soy", "סויה"),
    r"\bsesame\b": ("Sesame", "שומשום"),
    r"\bmustard\b": ("Mustard", "חרדל"),
    r"\blupin\b": ("Lupin", "לופין"),
    r"\bfish\b": ("Fish", "דגים"),
    r"\bnut\b|\bnuts\b|\btree nuts\b|\bcashew\b|\balmond\b|\bpistachio\b": ("Nuts", "אגוזים"),
    r"\bpeanut\b|\bpeanuts\b": ("Peanuts", "בוטנים"),
    r"\bcelery\b": ("Celery", "סלרי"),
    r"\bsulfites\b|\bsulphites\b": ("Sulfites", "סולפיטים"),
}

CULINARY_HE_REPLACEMENTS = {
    "lemon grass": "למון גראס",
    "lemongrass": "למון גראס",
    "lemon-grass": "למון גראס",
    "stracciatella": "סטרצ׳יאטלה",
    "yuzu": "יוזו",
    "miso": "מיסו",
    "panko": "פנקו",
    "aioli": "איולי",
    "brioche": "בריוש",
    "kimchi": "קימצ׳י",
    "shatta": "שאטה",
}


def clean_text(text):
    if not text:
        return ""
    text = text.replace("\r", "\n")
    text = text.replace("", "")
    text = text.replace("￾", "")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = text.replace("and and", "and")
    text = text.replace("beaf", "beef")
    text = text.replace("tomatoes salad", "tomato salad")
    text = text.replace("Ram#", "Ramen")
    return text.strip()


def clean_ingredients_for_display(ingredients):
    if not ingredients:
        return ""
    ingredients = re.sub(r"\([^)]*\)", "", ingredients)
    ingredients = re.sub(r"\s+,", ",", ingredients)
    ingredients = re.sub(r",\s*,", ",", ingredients)
    ingredients = re.sub(r"\s{2,}", " ", ingredients)
    return clean_text(ingredients).strip(" ,.")


def post_process_hebrew(text):
    if not text:
        return ""

    result = text

    for eng, heb in CULINARY_HE_REPLACEMENTS.items():
        result = re.sub(eng, heb, result, flags=re.IGNORECASE)

    result = result.replace("שatta", "שאטה")
    result = result.replace("למון גראס,", "למון גראס,")
    result = result.replace("חמוץ מתוק", "חמוץ-מתוק")

    return result.strip()


def split_category(raw):
    raw = clean_text(raw)
    match = re.search(r"^(.*?)\s*\((.*?)\)", raw)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return raw.strip(), ""


def map_kosher(category, raw_kosher=""):
    c = (category or "").lower()
    raw = (raw_kosher or "").lower()

    if "salad bar" in c:
        return ""

    for station in MEAT_STATIONS:
        if station in c:
            return "בשרי"

    for station in DAIRY_STATIONS:
        if station in c:
            return "חלבי"

    if raw == "meat":
        return "בשרי"
    if raw == "dairy":
        return "חלבי"

    return ""


def extract_allergens(text):
    text_l = (text or "").lower()
    found_en = []
    found_he = []

    order_he = [
        "גלוטן", "חיטה", "ביצים", "חלב", "דגים", "סויה",
        "שומשום", "חרדל", "לופין", "אגוזים", "בוטנים",
        "סלרי", "סולפיטים"
    ]

    for pattern, (en, he) in ALLERGEN_PATTERNS.items():
        if re.search(pattern, text_l):
            if en not in found_en:
                found_en.append(en)
            if he not in found_he:
                found_he.append(he)

    combined = list(zip(found_en, found_he))
    combined.sort(key=lambda pair: order_he.index(pair[1]) if pair[1] in order_he else 999)

    return {
        "allergens_en": ", ".join([x[0] for x in combined]),
        "allergens_he": ", ".join([x[1] for x in combined]),
        "allergens": ", ".join([x[1] for x in combined])
    }


def extract_text_from_pdf(path):
    if fitz is None:
        return ""

    doc = fitz.open(path)
    pages = []

    for page in doc:
        page_text = page.get_text()
        if page_text.strip():
            pages.append(page_text)

    doc.close()

    return "\n\n__PAGE_BREAK__\n\n".join(pages)


def extract_raw_text_from_request():
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
        data = request.json or {}
        raw_text = data.get("text", "")

    return raw_text


def is_category_line(line):
    l = line.lower()
    return "(" in line and ")" in line and ("meat" in l or "dairy" in l or "parve" in l)


def is_price_line(line):
    return bool(re.search(r"₪\s*\d+", line) or re.fullmatch(r"\d+(\.\d+)?", line))


def clean_price(line):
    price = re.sub(r"[^\d.]", "", line or "")
    return price.replace(".00", "").strip() or "55"


def is_bad_generic_description(description, name, category):
    if not description:
        return True

    d = description.lower().strip()
    n = (name or "").lower().strip()
    c = (category or "").lower().strip()

    bad_phrases = [
        "pizza of the day",
        "soup of the day",
        "dish of the day",
        "special of the day"
    ]

    if d in bad_phrases:
        return True

    if any(phrase in d for phrase in bad_phrases):
        cleaned = d
        for phrase in bad_phrases:
            cleaned = cleaned.replace(phrase, "")
        cleaned = cleaned.replace(n, "").replace("pizza", "").replace("soup", "").strip()
        if len(cleaned) < 8:
            return True

    if n and d == n:
        return True

    if c and d == c:
        return True

    return False


def is_sushi_station_line(line):
    l = (line or "").strip().lower()
    return l in ["sushi", "sushi station"]


def is_known_station_line(line):
    l = (line or "").strip().lower()

    if is_category_line(line):
        return True

    stations = [
        "meat station",
        "chicken station",
        "fish station",
        "pizza station",
        "sushi station",
        "salad bar station",
        "grill",
        "chef special",
        "sandwich",
        "soup",
        "fish special",
        "veg/vegan",
        "pizza",
        "salad bar",
        "sushi"
    ]

    return l in stations


def is_price_near(lines, start, max_lookahead=3):
    end = min(len(lines), start + max_lookahead + 1)
    for i in range(start, end):
        if is_price_line(lines[i]):
            return i
    return None


def is_probable_title_line(line):
    if not line:
        return False

    l = line.strip().lower()

    if l.startswith("ingredients"):
        return False
    if l.startswith("contains"):
        return False
    if "," in line:
        return False
    if line.endswith("."):
        return False
    if line.endswith(","):
        return False
    if len(line) > 65:
        return False

    return True


def find_dish_starts(lines):
    starts = []

    for i in range(len(lines)):
        if not is_probable_title_line(lines[i]):
            continue

        price_idx = is_price_near(lines, i, 3)

        if price_idx is not None and price_idx > i:
            starts.append((i, price_idx))

    cleaned = []
    used = set()

    for start, price_idx in starts:
        if price_idx in used:
            continue
        cleaned.append((start, price_idx))
        used.add(price_idx)

    return cleaned


def parse_sushi_page(station, lines):
    dishes = []
    starts = find_dish_starts(lines)

    for idx, (start, price_idx) in enumerate(starts):
        next_start = starts[idx + 1][0] if idx + 1 < len(starts) else len(lines)

        name = clean_text(" ".join(lines[start:price_idx]))
        price = clean_price(lines[price_idx])
        body = lines[price_idx + 1:next_start]

        description_lines = []
        ingredient_lines = []
        i = 0

        while i < len(body):
            line = body[i]
            next_line = body[i + 1] if i + 1 < len(body) else ""

            if is_probable_title_line(line) and next_line.lower().startswith("ingredients"):
                section_title = line
                ing = next_line.split(":", 1)[-1].strip() if ":" in next_line else ""
                section_parts = [ing] if ing else []
                i += 2

                while i < len(body):
                    current = body[i]
                    following = body[i + 1] if i + 1 < len(body) else ""

                    if is_probable_title_line(current) and following.lower().startswith("ingredients"):
                        break

                    section_parts.append(current)
                    i += 1

                ingredient_lines.append(f"{section_title}: {clean_text(' '.join(section_parts))}")
                continue

            if line.lower().startswith("ingredients"):
                ing = line.split(":", 1)[-1].strip() if ":" in line else ""
                ingredient_lines.append(ing)
                i += 1
                continue

            if not ingredient_lines:
                description_lines.append(line)

            i += 1

        dishes.append({
            "category_raw": station,
            "name": name,
            "description": clean_text(" ".join(description_lines)),
            "ingredients": clean_text("\n".join(ingredient_lines)),
            "price": price
        })

    return dishes


def parse_regular_page(station, lines):
    dishes = []
    starts = find_dish_starts(lines)

    for idx, (start, price_idx) in enumerate(starts):
        next_start = starts[idx + 1][0] if idx + 1 < len(starts) else len(lines)

        name = clean_text(" ".join(lines[start:price_idx]))
        price = clean_price(lines[price_idx])
        body = lines[price_idx + 1:next_start]

        description_lines = []
        ingredient_lines = []
        ingredient_mode = False

        i = 0
        while i < len(body):
            line = body[i]
            next_line = body[i + 1] if i + 1 < len(body) else ""

            if clean_text(line) == name:
                i += 1
                continue

            if is_probable_title_line(line) and next_line.lower().startswith("ingredients"):
                section_title = line
                section_ing = next_line.split(":", 1)[-1].strip() if ":" in next_line else ""
                ingredient_lines.append(f"{section_title}: {section_ing}")
                ingredient_mode = True
                i += 2
                continue

            if line.lower().startswith("ingredients"):
                ing = line.split(":", 1)[-1].strip() if ":" in line else ""
                ingredient_lines.append(ing)
                ingredient_mode = True
                i += 1
                continue

            if ingredient_mode:
                ingredient_lines.append(line)
            else:
                description_lines.append(line)

            i += 1

        dishes.append({
            "category_raw": station,
            "name": name,
            "description": clean_text(" ".join(description_lines)),
            "ingredients": clean_text("\n".join(ingredient_lines)),
            "price": price
        })

    return dishes


def parse_pages_from_pdf_text(text):
    pages = [p.strip() for p in text.split("__PAGE_BREAK__") if p.strip()]
    dishes = []

    for page in pages:
        page = clean_text(page)
        lines = [l.strip() for l in page.split("\n") if l.strip()]

        if not lines:
            continue

        station = lines[0]
        body_lines = lines[1:]

        if not is_known_station_line(station):
            continue

        if is_sushi_station_line(station):
            dishes.extend(parse_sushi_page(station, body_lines))
        else:
            dishes.extend(parse_regular_page(station, body_lines))

    return dishes


def parse_text(text):
    if "__PAGE_BREAK__" in text:
        page_dishes = parse_pages_from_pdf_text(text)
        if page_dishes:
            return page_dishes

    text = clean_text(text)
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    if any(is_known_station_line(l) for l in lines):
        dishes = []
        current_station = None
        current_lines = []

        for line in lines:
            if is_known_station_line(line):
                if current_station and current_lines:
                    if is_sushi_station_line(current_station):
                        dishes.extend(parse_sushi_page(current_station, current_lines))
                    else:
                        dishes.extend(parse_regular_page(current_station, current_lines))

                current_station = line
                current_lines = []
                continue

            if current_station:
                current_lines.append(line)

        if current_station and current_lines:
            if is_sushi_station_line(current_station):
                dishes.extend(parse_sushi_page(current_station, current_lines))
            else:
                dishes.extend(parse_regular_page(current_station, current_lines))

        if dishes:
            return dishes

    dishes = []
    current = None
    ingredient_mode = False
    description_mode = False

    for line in lines:
        if is_category_line(line):
            if current and current.get("name"):
                dishes.append(current)

            current = {
                "category_raw": line,
                "name": "",
                "description": "",
                "ingredients": "",
                "price": "55"
            }

            ingredient_mode = False
            description_mode = False
            continue

        if current is None:
            continue

        if is_price_line(line):
            current["price"] = clean_price(line)
            ingredient_mode = False
            description_mode = True
            continue

        if line.lower().startswith("ingredients"):
            ing = line.split(":", 1)[-1].strip() if ":" in line else ""
            current["ingredients"] = ing
            ingredient_mode = True
            description_mode = False
            continue

        if ingredient_mode:
            current["ingredients"] += " " + line
            continue

        if not current["name"]:
            current["name"] = line
            continue

        if line == current["name"]:
            description_mode = False
            continue

        if description_mode:
            current["description"] += (" " if current["description"] else "") + line
            continue

        if not current["description"]:
            current["description"] = line

    if current and current.get("name"):
        dishes.append(current)

    return dishes


def enhance_with_ai(dish):
    fallback = {
        "name_he": dish.get("name_en", ""),
        "description_he": dish.get("description_en", ""),
        "ingredients_he": dish.get("ingredients_en", "")
    }

    if client is None:
        return fallback

    needs_description = not dish.get("description_en", "").strip()

    prompt = {
        "station": dish.get("category", ""),
        "kosher": dish.get("kosher", ""),
        "name_en": dish.get("name_en", ""),
        "description_en": dish.get("description_en", ""),
        "ingredients_en": dish.get("ingredients_en", ""),
        "needs_description_from_ingredients": needs_description
    }

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            temperature=0.1,
            messages=[
                {
                    "role": "system",
                    "content": """
You are a professional culinary Hebrew translator for Apple Herzliya Caffè Macs.
Return JSON only.

Rules:
- Translate only the Hebrew fields.
- Do not decide kosher.
- Do not decide station/category.
- Do not decide allergens.
- Do not invent ingredients.
- Do not add marketing language.
- Dish name should be a professional Hebrew menu name.
- If description_en exists, description_he must be an accurate translation.
- If description_en is empty or generic, create one neutral short description using only name_en and ingredients_en.
- Ingredients should be translated to Hebrew, comma separated.
- For sushi, keep section names clear.

Return exactly:
{
  "name_he": "...",
  "description_he": "...",
  "ingredients_he": "..."
}
"""
                },
                {
                    "role": "user",
                    "content": json.dumps(prompt, ensure_ascii=False)
                }
            ]
        )

        content = response.choices[0].message.content.strip()
        content = content.replace("```json", "").replace("```", "").strip()
        data = json.loads(content)

        return {
            "name_he": post_process_hebrew(data.get("name_he") or fallback["name_he"]),
            "description_he": post_process_hebrew(data.get("description_he") or fallback["description_he"]),
            "ingredients_he": post_process_hebrew(data.get("ingredients_he") or fallback["ingredients_he"])
        }

    except Exception:
        return fallback


def normalize_dish(raw):
    category, raw_kosher = split_category(raw.get("category_raw", ""))
    kosher = map_kosher(category, raw_kosher)

    raw_ingredients = clean_text(raw.get("ingredients", ""))
    name_en = clean_text(raw.get("name", ""))
    description_en = clean_text(raw.get("description", ""))

    if is_bad_generic_description(description_en, name_en, category):
        description_en = ""

    dish = {
        "category": category,
        "kosher": kosher,
        "name_en": name_en,
        "description_en": description_en,
        "ingredients_en": clean_ingredients_for_display(raw_ingredients),
        "price": raw.get("price", "55")
    }

    allergens = extract_allergens(raw_ingredients)
    dish.update(allergens)

    ai = enhance_with_ai(dish)

    dish["name_he"] = ai["name_he"]
    dish["description_he"] = ai["description_he"]
    dish["ingredients_he"] = ai["ingredients_he"]

    return dish


def add_batch_metadata(dishes):
    enriched = []

    for index, dish in enumerate(dishes):
        item = dict(dish)
        item["display_id"] = index
        item["display_number"] = index + 1
        item["display_title"] = f'{item.get("category", "")} - {item.get("name_en", "")}'
        enriched.append(item)

    return enriched


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/extract", methods=["POST"])
def extract():
    raw_text = extract_raw_text_from_request()
    raw_dishes = parse_text(raw_text)
    dishes = [normalize_dish(d) for d in raw_dishes]

    return jsonify({
        "success": True,
        "count": len(dishes),
        "dishes": dishes
    })


@app.route("/extract-full-day", methods=["POST"])
def extract_full_day():
    raw_text = extract_raw_text_from_request()
    raw_dishes = parse_text(raw_text)
    dishes = [normalize_dish(d) for d in raw_dishes]
    dishes = add_batch_metadata(dishes)

    return jsonify({
        "success": True,
        "count": len(dishes),
        "dishes": dishes
    })


@app.route("/enhance", methods=["POST"])
def enhance():
    data = request.json or {}

    fixed = {
        "category": data.get("category", ""),
        "kosher": data.get("kosher", ""),
        "name_en": data.get("name_en", ""),
        "description_en": data.get("description_en", ""),
        "ingredients_en": clean_ingredients_for_display(data.get("ingredients_en", "")),
        "price": data.get("price", "55")
    }

    ai = enhance_with_ai(fixed)

    fixed["name_he"] = ai["name_he"]
    fixed["description_he"] = ai["description_he"]
    fixed["ingredients_he"] = ai["ingredients_he"]

    return jsonify({
        "success": True,
        "dish": fixed
    })


@app.route("/create-display", methods=["POST"])
def create_display():
    data = request.json or {}

    display = {
        "kosher": data.get("kosher", ""),
        "category": data.get("category", ""),
        "name_he": data.get("name_he", ""),
        "name_en": data.get("name_en", ""),
        "description_he": data.get("description_he", ""),
        "description_en": data.get("description_en", ""),
        "ingredients_he": data.get("ingredients_he", ""),
        "ingredients_en": clean_ingredients_for_display(data.get("ingredients_en", "")),
        "allergens": data.get("allergens", ""),
        "allergens_en": data.get("allergens_en", ""),
        "allergens_he": data.get("allergens_he", ""),
        "price": data.get("price", "55")
    }

    return jsonify({
        "success": True,
        "display": display
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
