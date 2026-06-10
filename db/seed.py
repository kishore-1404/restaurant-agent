# db/seed.py — full replacement
"""
Robust seed script for 3 restaurants with:
- Full ingredient & allergen data
- Nutritional information
- Allowed modifications
- Price rules (happy hour, weekly specials, seasonal)
- Order rules
- Time-based category availability
- Item translations (Spanish, Japanese)
- Sample customer profiles
- Historical orders (generates affinity data)
"""

import asyncio
from decimal import Decimal
from datetime import datetime, time, date
from sqlalchemy import select
from db.base import AsyncSessionFactory, engine, Base
from db.models import (
    Restaurant, MenuCategory, MenuItem,
    PriceRule, OrderRule, CustomerProfile,
    Order, OrderItem, ItemAffinity
)
import logging
import random

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# RESTAURANT DATA
# ─────────────────────────────────────────────────────────────────────────────

RESTAURANTS = [

  # ── 1. THE SMOKEHOUSE ──────────────────────────────────────────────────────
  {
    "name": "The Smokehouse",
    "cuisine_type": "american",
    "personality": "casual, fun, calls customers 'partner', uses American BBQ lingo",
    "special_instructions": "All burgers available with beef, chicken, or veggie patty. "
                            "Hickory smoke on all meats. Ask about our daily brisket.",
    "categories": [
      {
        "name": "Mains", "order": 1,
        "available_days": [0,1,2,3,4,5,6],
        "items": [
          {
            "name":        "Big Smoke Burger",
            "description": "Double beef patty, cheddar, house sauce, brioche bun",
            "price":       12.99,
            "tags":        ["bestseller"],
            "display_order": 1,
            "ingredients": ["beef patty", "cheddar cheese", "lettuce", "tomato", "pickles",
                            "onion", "house sauce", "mayonnaise", "ketchup", "brioche bun",
                            "mustard"],
            "allergens":   ["dairy", "gluten", "eggs"],
            "nutrition":   {"calories": 720, "protein_g": 42, "carbs_g": 52, "fat_g": 36,
                            "sodium_mg": 920, "fiber_g": 3},
            "modifications": {
              "remove":  ["pickles", "onions", "lettuce", "tomato", "house sauce"],
              "swap":    {"patty": ["beef", "chicken", "veggie"], "bun": ["brioche", "gluten-free bun"]},
              "add":     {"extra cheese": 0.50, "bacon": 1.00, "fried egg": 0.75, "avocado": 1.25,
                         "jalapeños": 0.50, "extra patty": 2.50}
            },
            "translations": {
              "es": {"name": "Big Smoke Burger",
                     "description": "Doble hamburguesa de res, cheddar, salsa de la casa, brioche"},
              "ja": {"name": "ビッグスモークバーガー",
                     "description": "ダブルビーフパティ、チェダー、ハウスソース、ブリオッシュバン"}
            },
          },
          {
            "name":        "BBQ Ribs Platter",
            "description": "Half rack, slow-smoked 12hr over hickory, coleslaw, cornbread",
            "price":       18.49,
            "tags":        ["gluten-free", "bestseller"],
            "display_order": 2,
            "ingredients": ["pork ribs", "BBQ sauce", "tomato", "apple cider vinegar",
                            "brown sugar", "worcestershire sauce", "smoked paprika",
                            "garlic", "coleslaw", "cabbage", "mayo", "cornbread",
                            "cornmeal", "buttermilk", "eggs"],
            "allergens":   ["gluten", "eggs", "dairy"],
            "nutrition":   {"calories": 890, "protein_g": 65, "carbs_g": 28, "fat_g": 52,
                            "sodium_mg": 1240, "fiber_g": 2},
            "modifications": {
              "remove":  ["coleslaw", "cornbread"],
              "add":     {"extra ribs (1/4 rack)": 6.00, "extra BBQ sauce": 0.75},
              "swap":    {"side": ["coleslaw", "loaded fries", "onion rings", "corn on the cob"]}
            },
            "translations": {
              "es": {"name": "Costillas BBQ",
                     "description": "Medio rack, ahumado 12h sobre nogal, coleslaw, pan de maíz"},
              "ja": {"name": "BBQリブプラッター",
                     "description": "ハーフラック、ヒッコリーで12時間スモーク、コールスロー、コーンブレッド"}
            },
          },
          {
            "name":        "Crispy Chicken Sando",
            "description": "Buttermilk fried thigh, pickles, sriracha mayo, potato bun",
            "price":       11.99,
            "tags":        ["spicy"],
            "display_order": 3,
            "ingredients": ["chicken thigh", "buttermilk", "flour", "breadcrumbs",
                            "sriracha", "mayonnaise", "pickles", "lettuce", "potato bun",
                            "eggs"],
            "allergens":   ["gluten", "dairy", "eggs"],
            "nutrition":   {"calories": 680, "protein_g": 38, "carbs_g": 58, "fat_g": 30,
                            "sodium_mg": 1100, "fiber_g": 2},
            "modifications": {
              "remove":  ["pickles", "sriracha mayo", "lettuce"],
              "add":     {"extra sriracha mayo": 0.50, "cheese": 0.75, "bacon": 1.00},
              "swap":    {"heat": ["mild", "medium", "hot", "fire"]}
            },
            "translations": {
              "es": {"name": "Sándwich de Pollo Crujiente",
                     "description": "Muslo frito en suero de leche, pepinillos, mayo sriracha"},
              "ja": {"name": "クリスピーチキンサンド",
                     "description": "バターミルクフライドチキン、ピクルス、スリラチャマヨ"}
            },
          },
          {
            "name":        "Smokehouse Melt",
            "description": "Pulled pork, gruyere, caramelised onions, sourdough",
            "price":       13.49,
            "tags":        [],
            "display_order": 4,
            "ingredients": ["pulled pork", "gruyere cheese", "caramelised onions",
                            "sourdough bread", "butter", "garlic"],
            "allergens":   ["gluten", "dairy"],
            "nutrition":   {"calories": 760, "protein_g": 44, "carbs_g": 48, "fat_g": 38,
                            "sodium_mg": 980, "fiber_g": 2},
            "modifications": {
              "remove":  ["caramelised onions"],
              "add":     {"extra pork": 2.00, "jalapeños": 0.50},
              "swap":    {"bread": ["sourdough", "gluten-free wrap"]}
            },
            "translations": {
              "es": {"name": "Smokehouse Melt", "description": "Cerdo desmenuzado, gruyère, cebolla caramelizada, masa madre"},
              "ja": {"name": "スモークハウスメルト", "description": "プルドポーク、グリュイエール、キャラメライズドオニオン、サワードウ"}
            },
          },
          {
            "name":        "Garden Stack Burger",
            "description": "Beetroot & black bean patty, avocado, sprouts, chipotle mayo",
            "price":       10.99,
            "tags":        ["vegetarian"],
            "display_order": 5,
            "ingredients": ["beetroot patty", "black beans", "avocado", "bean sprouts",
                            "chipotle mayo", "mayo", "chipotle", "brioche bun",
                            "lettuce", "tomato"],
            "allergens":   ["gluten", "eggs"],
            "nutrition":   {"calories": 540, "protein_g": 18, "carbs_g": 68, "fat_g": 22,
                            "sodium_mg": 780, "fiber_g": 9},
            "modifications": {
              "remove":  ["chipotle mayo", "sprouts"],
              "add":     {"cheese": 0.75, "extra avocado": 1.25},
              "swap":    {"bun": ["brioche", "gluten-free bun", "lettuce wrap"]}
            },
            "translations": {
              "es": {"name": "Burger Garden Stack", "description": "Hamburguesa de remolacha y frijoles negros, aguacate, brotes"},
              "ja": {"name": "ガーデンスタックバーガー", "description": "ビートルート＆黒豆パティ、アボカド、スプラウト"}
            },
          },
        ]
      },
      {
        "name": "Sides", "order": 2,
        "available_days": [0,1,2,3,4,5,6],
        "items": [
          {
            "name": "Loaded Fries",
            "description": "Shoestring fries, cheddar, smoked bacon, jalapeños, sour cream",
            "price": 5.99, "tags": ["spicy", "bestseller"], "display_order": 1,
            "ingredients": ["potatoes", "cheddar cheese", "smoked bacon", "jalapeños",
                            "sour cream", "chives", "vegetable oil"],
            "allergens":   ["dairy"],
            "nutrition":   {"calories": 480, "protein_g": 15, "carbs_g": 52, "fat_g": 24,
                            "sodium_mg": 820, "fiber_g": 4},
            "modifications": {
              "remove":  ["bacon", "jalapeños", "sour cream", "cheese"],
              "add":     {"extra cheese": 0.50, "extra bacon": 0.75, "BBQ sauce": 0.50},
            },
            "translations": {
              "es": {"name": "Papas Loaded", "description": "Papas fritas con cheddar, tocino, jalapeños, crema agria"},
              "ja": {"name": "ローデッドフライ", "description": "シューストリングフライ、チェダー、スモークベーコン、ハラペーニョ"}
            },
          },
          {
            "name": "Onion Rings",
            "description": "Beer-battered thick cut, chipotle dip",
            "price": 4.49, "tags": ["vegetarian"], "display_order": 2,
            "ingredients": ["onion", "beer batter", "flour", "beer", "chipotle dip",
                            "mayo", "chipotle", "vegetable oil"],
            "allergens":   ["gluten", "eggs"],
            "nutrition":   {"calories": 360, "protein_g": 5, "carbs_g": 42, "fat_g": 18,
                            "sodium_mg": 560, "fiber_g": 2},
            "modifications": {"remove": ["chipotle dip"], "add": {"extra dip": 0.50}},
            "translations": {
              "es": {"name": "Aros de Cebolla", "description": "Rebozados en cerveza, dip chipotle"},
              "ja": {"name": "オニオンリング", "description": "ビールバッター、チポトレディップ"}
            },
          },
          {
            "name": "Coleslaw",
            "description": "House recipe, creamy apple cider dressing",
            "price": 2.99, "tags": ["vegetarian", "gluten-free"], "display_order": 3,
            "ingredients": ["cabbage", "carrot", "mayonnaise", "apple cider vinegar",
                            "sugar", "celery seed", "dijon mustard"],
            "allergens":   ["eggs"],
            "nutrition":   {"calories": 180, "protein_g": 2, "carbs_g": 14, "fat_g": 13,
                            "sodium_mg": 320, "fiber_g": 2},
            "modifications": {},
            "translations": {
              "es": {"name": "Ensalada de Col", "description": "Receta de la casa, aderezo cremoso de sidra de manzana"},
              "ja": {"name": "コールスロー", "description": "ハウスレシピ、アップルサイダービネガードレッシング"}
            },
          },
          {
            "name": "Corn on the Cob",
            "description": "Grilled, smoked paprika butter",
            "price": 3.49, "tags": ["vegetarian", "gluten-free"], "display_order": 4,
            "ingredients": ["corn", "butter", "smoked paprika", "salt"],
            "allergens":   ["dairy"],
            "nutrition":   {"calories": 210, "protein_g": 4, "carbs_g": 32, "fat_g": 8,
                            "sodium_mg": 180, "fiber_g": 3},
            "modifications": {"swap": {"butter": ["regular butter", "no butter (vegan)"]}},
            "translations": {
              "es": {"name": "Mazorca de Maíz", "description": "A la parrilla, mantequilla de pimentón ahumado"},
              "ja": {"name": "コーンオンザコブ", "description": "グリル、スモークパプリカバター"}
            },
          },
        ]
      },
      {
        "name": "Drinks", "order": 3,
        "available_days": [0,1,2,3,4,5,6],
        "items": [
          {
            "name": "Classic Coke", "description": "330ml can, ice",
            "price": 2.49, "tags": [], "display_order": 1,
            "ingredients": ["carbonated water", "sugar", "caramel colour", "phosphoric acid",
                            "natural flavours", "caffeine"],
            "allergens":   [],
            "nutrition":   {"calories": 139, "protein_g": 0, "carbs_g": 35, "fat_g": 0,
                            "sodium_mg": 45, "fiber_g": 0},
            "modifications": {"swap": {"size": ["330ml", "500ml (+$0.80)"]}},
            "translations": {
              "es": {"name": "Coca-Cola Clásica"}, "ja": {"name": "コーラ"}
            },
          },
          {
            "name": "Lemonade", "description": "Fresh squeezed, still or sparkling",
            "price": 2.99, "tags": ["vegetarian"], "display_order": 2,
            "ingredients": ["lemons", "water", "cane sugar"],
            "allergens":   [],
            "nutrition":   {"calories": 120, "protein_g": 0, "carbs_g": 30, "fat_g": 0,
                            "sodium_mg": 10, "fiber_g": 0},
            "modifications": {"swap": {"style": ["still", "sparkling"]}},
            "translations": {
              "es": {"name": "Limonada", "description": "Recién exprimida, con gas o sin gas"},
              "ja": {"name": "レモネード"}
            },
          },
          {
            "name": "Chocolate Milkshake",
            "description": "Hand-spun, Valrhona chocolate, whipped cream",
            "price": 5.49, "tags": ["vegetarian"], "display_order": 3,
            "ingredients": ["whole milk", "chocolate ice cream", "Valrhona cocoa",
                            "heavy cream", "vanilla extract", "sugar"],
            "allergens":   ["dairy"],
            "nutrition":   {"calories": 580, "protein_g": 12, "carbs_g": 72, "fat_g": 24,
                            "sodium_mg": 320, "fiber_g": 2},
            "modifications": {
              "swap": {"milk": ["whole milk", "oat milk (+$0.50)", "almond milk (+$0.50)"]},
              "add":  {"extra whipped cream": 0.00, "extra shot espresso": 0.75}
            },
            "translations": {
              "es": {"name": "Batido de Chocolate", "description": "Batido a mano, chocolate Valrhona, crema"},
              "ja": {"name": "チョコレートミルクシェイク", "description": "手作り、ヴァローナチョコレート、ホイップクリーム"}
            },
          },
          {
            "name": "Iced Tea", "description": "Sweet or unsweetened, lemon wedge",
            "price": 2.99, "tags": [], "display_order": 4,
            "ingredients": ["black tea", "water", "sugar", "lemon"],
            "allergens":   [],
            "nutrition":   {"calories": 90, "protein_g": 0, "carbs_g": 23, "fat_g": 0,
                            "sodium_mg": 15, "fiber_g": 0},
            "modifications": {"swap": {"sugar": ["sweet", "unsweetened", "half sweet"]}},
            "translations": {
              "es": {"name": "Té Helado"}, "ja": {"name": "アイスティー"}
            },
          },
        ]
      },
    ],
    "price_rules": [
      {
        "name": "Weekday Happy Hour",
        "label": "Happy Hour",
        "description": "20% off all drinks, Mon–Fri 3pm–6pm",
        "rule_type": "percentage_off",
        "value": 20,
        "applies_to": "category",
        "applies_to_name": "Drinks",
        "valid_days": [1, 2, 3, 4, 5],  # Mon=1 ... Fri=5
        "valid_from": time(15, 0),
        "valid_until": time(18, 0),
        "priority": 10,
      },
      {
        "name": "Monday Burger Deal",
        "label": "Monday Madness",
        "description": "$2 off all burgers every Monday",
        "rule_type": "fixed_off",
        "value": 2.00,
        "applies_to": "item",
        "applies_to_names": ["Big Smoke Burger", "Crispy Chicken Sando", "Garden Stack Burger", "Smokehouse Melt"],
        "valid_days": [1],  # Monday
        "valid_from": None,
        "valid_until": None,
        "priority": 5,
      },
    ],
    "order_rules": [
      {
        "rule_type": "max_discounted_items",
        "value": 2,
        "description": "Maximum 2 items discounted per session under any promo",
        "error_message": "You've reached the promo limit for today — the remaining items are at regular price.",
      },
    ],
  },

  # ── 2. BELLA NAPOLI ────────────────────────────────────────────────────────
  {
    "name": "Bella Napoli",
    "cuisine_type": "italian",
    "personality": "warm, romantic, occasionally uses Italian phrases, very welcoming",
    "special_instructions": "All pizzas available gluten-free base (+$2). Fresh pasta made daily. Vegan options on request.",
    "categories": [
      {
        "name": "Pizzas", "order": 1,
        "available_days": [0,1,2,3,4,5,6],
        "items": [
          {
            "name": "Margherita Classica",
            "description": "San Marzano tomato, fior di latte, fresh basil, EVOO",
            "price": 13.99, "tags": ["vegetarian", "bestseller"], "display_order": 1,
            "ingredients": ["pizza dough", "San Marzano tomatoes", "fior di latte mozzarella",
                            "fresh basil", "extra virgin olive oil", "sea salt"],
            "allergens":   ["gluten", "dairy"],
            "nutrition":   {"calories": 680, "protein_g": 28, "carbs_g": 88, "fat_g": 22,
                            "sodium_mg": 860, "fiber_g": 4},
            "modifications": {
              "add":     {"extra mozzarella": 1.50, "prosciutto": 2.50, "mushrooms": 1.00,
                           "truffle oil": 1.50, "anchovies": 1.00},
              "swap":    {"base": ["regular", "gluten-free (+$2)"],
                          "sauce": ["tomato", "white (no tomato)"]},
              "remove":  ["basil"]
            },
            "translations": {
              "es": {"name": "Margherita Clásica",
                     "description": "Tomate San Marzano, fior di latte, albahaca fresca, AOVE"},
              "ja": {"name": "マルゲリータ クラシカ",
                     "description": "サンマルツァーノトマト、フィオルディラッテ、バジル"}
            },
          },
          {
            "name": "Diavola",
            "description": "San Marzano tomato, spicy 'nduja, fior di latte, chilli oil",
            "price": 15.99, "tags": ["spicy"], "display_order": 2,
            "ingredients": ["pizza dough", "San Marzano tomatoes", "nduja sausage",
                            "fior di latte mozzarella", "chilli oil", "fresh chilli",
                            "garlic"],
            "allergens":   ["gluten", "dairy"],
            "nutrition":   {"calories": 780, "protein_g": 34, "carbs_g": 86, "fat_g": 30,
                            "sodium_mg": 1080, "fiber_g": 4},
            "modifications": {
              "add":     {"extra nduja": 1.50, "olives": 0.75},
              "swap":    {"heat": ["medium", "extra hot"], "base": ["regular", "gluten-free (+$2)"]},
              "remove":  ["chilli oil"]
            },
            "translations": {
              "es": {"name": "Diavola", "description": "Tomate, nduja picante, fior di latte, aceite de guindilla"},
              "ja": {"name": "ディアボラ", "description": "サンマルツァーノ、ンドゥイヤ、モッツァレラ、チリオイル"}
            },
          },
          {
            "name": "Quattro Formaggi",
            "description": "Mozzarella, gorgonzola, parmesan, ricotta, honey drizzle",
            "price": 16.49, "tags": ["vegetarian"], "display_order": 3,
            "ingredients": ["pizza dough", "mozzarella", "gorgonzola", "parmesan",
                            "ricotta", "honey", "black pepper"],
            "allergens":   ["gluten", "dairy"],
            "nutrition":   {"calories": 840, "protein_g": 36, "carbs_g": 84, "fat_g": 38,
                            "sodium_mg": 1160, "fiber_g": 3},
            "modifications": {
              "remove": ["gorgonzola", "honey"],
              "swap":   {"base": ["regular", "gluten-free (+$2)"]}
            },
            "translations": {
              "es": {"name": "Cuatro Quesos", "description": "Mozzarella, gorgonzola, parmesano, ricotta, miel"},
              "ja": {"name": "クアトロフォルマッジ", "description": "モッツァレラ、ゴルゴンゾーラ、パルメザン、リコッタ、蜂蜜"}
            },
          },
          {
            "name": "Prosciutto e Funghi",
            "description": "Prosciutto di Parma, porcini mushrooms, mozzarella, truffle oil",
            "price": 16.99, "tags": [], "display_order": 4,
            "ingredients": ["pizza dough", "prosciutto di Parma", "porcini mushrooms",
                            "mozzarella", "truffle oil", "thyme", "garlic"],
            "allergens":   ["gluten", "dairy"],
            "nutrition":   {"calories": 760, "protein_g": 38, "carbs_g": 82, "fat_g": 28,
                            "sodium_mg": 1020, "fiber_g": 4},
            "modifications": {
              "remove": ["truffle oil", "mushrooms"],
              "swap":   {"base": ["regular", "gluten-free (+$2)"]}
            },
            "translations": {
              "es": {"name": "Prosciutto y Champiñones",
                     "description": "Prosciutto di Parma, champiñones porcini, mozzarella"},
              "ja": {"name": "プロシュートエフンギ",
                     "description": "プロシュートディパルマ、ポルチーニ茸、モッツァレラ"}
            },
          },
          {
            "name": "Napoletana",
            "description": "Anchovies, capers, Taggiasca olives, San Marzano, oregano",
            "price": 14.49, "tags": [], "display_order": 5,
            "ingredients": ["pizza dough", "San Marzano tomatoes", "anchovies",
                            "capers", "Taggiasca olives", "oregano", "garlic", "EVOO"],
            "allergens":   ["gluten", "fish"],
            "nutrition":   {"calories": 660, "protein_g": 26, "carbs_g": 84, "fat_g": 20,
                            "sodium_mg": 1280, "fiber_g": 5},
            "modifications": {
              "remove": ["anchovies", "capers"],
              "swap":   {"base": ["regular", "gluten-free (+$2)"]}
            },
            "translations": {
              "es": {"name": "Napolitana", "description": "Anchoas, alcaparras, aceitunas Taggiasca, San Marzano"},
              "ja": {"name": "ナポレターナ", "description": "アンチョビ、ケッパー、タジャスカオリーブ"}
            },
          },
        ]
      },
      {
        "name": "Pasta", "order": 2,
        "available_days": [0,1,2,3,4,5,6],
        "items": [
          {
            "name": "Spaghetti Carbonara",
            "description": "Guanciale, egg yolk, Pecorino Romano, black pepper — no cream",
            "price": 14.50, "tags": ["bestseller"], "display_order": 1,
            "ingredients": ["spaghetti", "guanciale", "egg yolks", "pecorino romano",
                            "black pepper", "pasta water"],
            "allergens":   ["gluten", "eggs", "dairy"],
            "nutrition":   {"calories": 680, "protein_g": 32, "carbs_g": 76, "fat_g": 26,
                            "sodium_mg": 880, "fiber_g": 3},
            "modifications": {
              "swap":   {"pasta": ["spaghetti", "rigatoni", "gluten-free penne (+$2)"]},
              "add":    {"extra guanciale": 2.00, "extra pecorino": 0.75}
            },
            "translations": {
              "es": {"name": "Spaghetti Carbonara",
                     "description": "Guanciale, yema de huevo, Pecorino Romano, pimienta negra"},
              "ja": {"name": "スパゲッティ カルボナーラ",
                     "description": "グアンチャーレ、卵黄、ペコリーノロマーノ、黒胡椒"}
            },
          },
          {
            "name": "Penne Arrabbiata",
            "description": "San Marzano, garlic, fresh chilli, pecorino, fresh parsley",
            "price": 12.99, "tags": ["vegetarian", "spicy"], "display_order": 2,
            "ingredients": ["penne", "San Marzano tomatoes", "garlic", "fresh chilli",
                            "pecorino romano", "fresh parsley", "EVOO"],
            "allergens":   ["gluten", "dairy"],
            "nutrition":   {"calories": 540, "protein_g": 18, "carbs_g": 88, "fat_g": 12,
                            "sodium_mg": 640, "fiber_g": 5},
            "modifications": {
              "swap":   {"pasta": ["penne", "rigatoni", "gluten-free penne (+$2)"],
                         "heat":  ["medium", "hot", "very hot"]},
              "add":    {"burrata": 3.00, "prawns": 4.00}
            },
            "translations": {
              "es": {"name": "Penne Arrabbiata",
                     "description": "San Marzano, ajo, guindilla fresca, pecorino, perejil"},
              "ja": {"name": "ペンネアラビアータ",
                     "description": "サンマルツァーノ、ニンニク、フレッシュチリ、ペコリーノ"}
            },
          },
          {
            "name": "Tagliatelle al Ragù",
            "description": "Slow-cooked beef & pork ragù, 6 hours, Parmigiano Reggiano",
            "price": 15.99, "tags": [], "display_order": 3,
            "ingredients": ["tagliatelle", "beef mince", "pork mince", "San Marzano tomatoes",
                            "red wine", "onion", "celery", "carrot", "garlic",
                            "bay leaf", "parmigiano reggiano"],
            "allergens":   ["gluten", "dairy"],
            "nutrition":   {"calories": 720, "protein_g": 42, "carbs_g": 72, "fat_g": 24,
                            "sodium_mg": 860, "fiber_g": 4},
            "modifications": {
              "swap":   {"pasta": ["tagliatelle", "pappardelle", "rigatoni"]},
              "add":    {"extra parmesan": 0.75}
            },
            "translations": {
              "es": {"name": "Tagliatelle al Ragù",
                     "description": "Ragù de res y cerdo cocinado 6 horas, Parmigiano Reggiano"},
              "ja": {"name": "タリアテッレ アル ラグー",
                     "description": "6時間煮込んだビーフ＆ポークラグー、パルミジャーノレッジャーノ"}
            },
          },
          {
            "name": "Risotto ai Funghi",
            "description": "Wild mushroom, white wine, truffle oil, Parmigiano, chives",
            "price": 14.99, "tags": ["vegetarian", "gluten-free"], "display_order": 4,
            "ingredients": ["arborio rice", "wild mushrooms", "porcini", "white wine",
                            "parmigiano reggiano", "truffle oil", "vegetable stock",
                            "shallots", "butter", "chives"],
            "allergens":   ["dairy"],
            "nutrition":   {"calories": 580, "protein_g": 14, "carbs_g": 72, "fat_g": 20,
                            "sodium_mg": 640, "fiber_g": 3},
            "modifications": {
              "remove": ["truffle oil"],
              "add":    {"extra parmesan": 0.75, "burrata": 3.00}
            },
            "translations": {
              "es": {"name": "Risotto ai Funghi",
                     "description": "Champiñones silvestres, vino blanco, aceite de trufa, Parmigiano"},
              "ja": {"name": "リゾット アイ フンギ",
                     "description": "野生キノコ、白ワイン、トリュフオイル、パルミジャーノ"}
            },
          },
        ]
      },
      {
        "name": "Desserts", "order": 3,
        "available_days": [0,1,2,3,4,5,6],
        "items": [
          {
            "name": "Tiramisu",
            "description": "Mascarpone, savoiardi, espresso, Marsala, cocoa — our 30yr recipe",
            "price": 7.50, "tags": ["vegetarian"], "display_order": 1,
            "ingredients": ["mascarpone", "savoiardi biscuits", "espresso", "Marsala wine",
                            "egg yolks", "sugar", "cocoa powder"],
            "allergens":   ["dairy", "eggs", "gluten"],
            "nutrition":   {"calories": 420, "protein_g": 8, "carbs_g": 42, "fat_g": 22,
                            "sodium_mg": 180, "fiber_g": 1},
            "modifications": {"remove": ["Marsala wine (alcohol-free version)"]},
            "translations": {
              "es": {"name": "Tiramisú", "description": "Mascarpone, savoiardi, espresso, Marsala, cacao — receta de 30 años"},
              "ja": {"name": "ティラミス", "description": "マスカルポーネ、サヴォイアルディ、エスプレッソ、30年のレシピ"}
            },
          },
          {
            "name": "Panna Cotta",
            "description": "Vanilla bean, raspberry coulis, toasted almond",
            "price": 6.99, "tags": ["vegetarian", "gluten-free"], "display_order": 2,
            "ingredients": ["cream", "whole milk", "vanilla bean", "gelatin", "sugar",
                            "raspberries", "toasted almonds"],
            "allergens":   ["dairy", "tree_nuts"],
            "nutrition":   {"calories": 340, "protein_g": 6, "carbs_g": 28, "fat_g": 22,
                            "sodium_mg": 80, "fiber_g": 2},
            "modifications": {"remove": ["almonds"]},
            "translations": {
              "es": {"name": "Panna Cotta", "description": "Vainilla, coulis de frambuesa, almendra tostada"},
              "ja": {"name": "パンナコッタ", "description": "バニラビーン、ラズベリーソース、トーストアーモンド"}
            },
          },
          {
            "name": "Gelato (3 scoops)",
            "description": "Ask for today's flavours — made fresh each morning",
            "price": 5.99, "tags": ["vegetarian", "gluten-free"], "display_order": 3,
            "ingredients": ["whole milk", "cream", "sugar", "egg yolks"],
            "allergens":   ["dairy", "eggs"],
            "nutrition":   {"calories": 380, "protein_g": 8, "carbs_g": 48, "fat_g": 16,
                            "sodium_mg": 120, "fiber_g": 0},
            "modifications": {"swap": {"scoops": ["2 scoops (-$1.50)", "3 scoops", "4 scoops (+$1.50)"]}},
            "translations": {
              "es": {"name": "Gelato (3 bolas)", "description": "Pregunte por los sabores de hoy"},
              "ja": {"name": "ジェラート（3スクープ）", "description": "本日のフレーバーをお尋ねください"}
            },
          },
        ]
      },
      {
        "name": "Drinks", "order": 4,
        "available_days": [0,1,2,3,4,5,6],
        "items": [
          {
            "name": "San Pellegrino",
            "description": "500ml sparkling mineral water",
            "price": 3.49, "tags": [], "display_order": 1,
            "ingredients": ["sparkling mineral water"],
            "allergens": [],
            "nutrition": {"calories": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0, "sodium_mg": 8},
            "modifications": {},
            "translations": {"es": {"name": "San Pellegrino"}, "ja": {"name": "サンペレグリノ"}},
          },
          {
            "name": "Espresso",
            "description": "Double ristretto, single origin Ethiopian",
            "price": 2.99, "tags": [], "display_order": 2,
            "ingredients": ["espresso coffee"],
            "allergens": [],
            "nutrition": {"calories": 5, "protein_g": 0, "carbs_g": 1, "fat_g": 0, "sodium_mg": 5},
            "modifications": {"swap": {"strength": ["ristretto", "espresso", "lungo"]}},
            "translations": {"es": {"name": "Espresso"}, "ja": {"name": "エスプレッソ"}},
          },
          {
            "name": "Limoncello",
            "description": "House-made Amalfi lemon digestif, 30ml",
            "price": 5.99, "tags": [], "display_order": 3,
            "ingredients": ["Amalfi lemons", "grain alcohol", "sugar", "water"],
            "allergens": [],
            "nutrition": {"calories": 120, "protein_g": 0, "carbs_g": 14, "fat_g": 0, "sodium_mg": 2},
            "modifications": {},
            "translations": {"es": {"name": "Limoncello"}, "ja": {"name": "リモンチェッロ"}},
          },
        ]
      },
    ],
    "price_rules": [
      {
        "name": "Pizza Tuesday",
        "label": "Pizza Tuesday",
        "description": "15% off all pizzas every Tuesday",
        "rule_type": "percentage_off",
        "value": 15,
        "applies_to": "category",
        "applies_to_name": "Pizzas",
        "valid_days": [2],  # Tuesday
        "valid_from": None, "valid_until": None,
        "priority": 5,
      },
      {
        "name": "Aperitivo Hour",
        "label": "Aperitivo Hour",
        "description": "Limoncello complimentary with any pasta dish, Fri–Sat 5–7pm",
        "rule_type": "fixed_price",
        "value": 0,
        "applies_to": "item",
        "applies_to_names": ["Limoncello"],
        "valid_days": [5, 6],  # Fri, Sat
        "valid_from": time(17, 0), "valid_until": time(19, 0),
        "priority": 8,
      },
    ],
    "order_rules": [
      {
        "rule_type": "min_total",
        "value": 15.00,
        "description": "Minimum order $15 for dine-in",
        "error_message": "We have a $15 minimum — how about adding a dessert or drink?",
      },
    ],
  },

  # ── 3. TOKYO BITES ─────────────────────────────────────────────────────────
  {
    "name": "Tokyo Bites",
    "cuisine_type": "japanese",
    "personality": "minimal, precise, respectful, greets with 'Irasshaimase', very attentive",
    "special_instructions": "Fish market-fresh daily. Ramen broth 18hr. Gluten-free: tamari substitution available.",
    "categories": [
      {
        "name": "Sushi & Sashimi", "order": 1,
        "available_days": [0,1,2,3,4,5,6],
        "items": [
          {
            "name": "Salmon Sashimi (8pc)",
            "description": "Atlantic salmon, wasabi, pickled ginger, soy",
            "price": 16.00, "tags": ["gluten-free", "bestseller"], "display_order": 1,
            "ingredients": ["Atlantic salmon", "wasabi", "pickled ginger", "soy sauce"],
            "allergens":   ["fish", "soy"],
            "nutrition":   {"calories": 240, "protein_g": 34, "carbs_g": 4, "fat_g": 10,
                            "sodium_mg": 680, "fiber_g": 0},
            "modifications": {
              "add":     {"extra wasabi": 0.00, "extra ginger": 0.00},
              "swap":    {"soy": ["regular soy", "tamari (gluten-free)"]}
            },
            "translations": {
              "es": {"name": "Sashimi de Salmón (8 piezas)",
                     "description": "Salmón atlántico, wasabi, jengibre encurtido, soja"},
              "ja": {"name": "サーモン刺身（8枚）",
                     "description": "大西洋サーモン、わさび、ガリ、醤油"}
            },
          },
          {
            "name": "Tuna Nigiri (6pc)",
            "description": "Bluefin tuna, seasoned sushi rice, wasabi",
            "price": 14.50, "tags": ["gluten-free"], "display_order": 2,
            "ingredients": ["bluefin tuna", "sushi rice", "rice vinegar", "sugar",
                            "salt", "wasabi", "nori"],
            "allergens":   ["fish", "soy"],
            "nutrition":   {"calories": 260, "protein_g": 30, "carbs_g": 24, "fat_g": 4,
                            "sodium_mg": 460, "fiber_g": 0},
            "modifications": {
              "add":    {"extra wasabi": 0.00},
              "swap":   {"soy": ["regular soy", "tamari (gluten-free)"]}
            },
            "translations": {
              "es": {"name": "Nigiri de Atún (6 piezas)",
                     "description": "Atún de aleta azul, arroz de sushi, wasabi"},
              "ja": {"name": "マグロ握り（6個）",
                     "description": "本マグロ、酢飯、わさび"}
            },
          },
          {
            "name": "Dragon Roll (8pc)",
            "description": "Prawn tempura, avocado, tobiko, spicy mayo",
            "price": 17.99, "tags": ["bestseller"], "display_order": 3,
            "ingredients": ["prawn", "tempura batter", "flour", "avocado", "tobiko",
                            "cucumber", "nori", "sushi rice", "spicy mayo",
                            "mayo", "sriracha"],
            "allergens":   ["shellfish", "gluten", "eggs"],
            "nutrition":   {"calories": 380, "protein_g": 18, "carbs_g": 48, "fat_g": 14,
                            "sodium_mg": 720, "fiber_g": 3},
            "modifications": {
              "remove":  ["spicy mayo", "tobiko"],
              "add":     {"extra avocado": 1.00, "extra spicy mayo": 0.50},
              "swap":    {"heat": ["mild", "medium", "spicy"]}
            },
            "translations": {
              "es": {"name": "Dragon Roll (8 piezas)",
                     "description": "Tempura de gambas, aguacate, tobiko, mayonesa picante"},
              "ja": {"name": "ドラゴンロール（8個）",
                     "description": "海老天ぷら、アボカド、とびこ、スパイシーマヨ"}
            },
          },
          {
            "name": "Vegetable Maki (6pc)",
            "description": "Cucumber, avocado, pickled daikon, sesame, nori",
            "price": 9.99, "tags": ["vegetarian", "vegan"], "display_order": 4,
            "ingredients": ["cucumber", "avocado", "pickled daikon", "sesame seeds",
                            "nori", "sushi rice", "rice vinegar"],
            "allergens":   ["sesame", "soy"],
            "nutrition":   {"calories": 180, "protein_g": 4, "carbs_g": 34, "fat_g": 4,
                            "sodium_mg": 320, "fiber_g": 4},
            "modifications": {
              "add":    {"extra sesame": 0.00, "avocado": 1.00},
              "swap":   {"soy": ["regular soy", "tamari (gluten-free)"]}
            },
            "translations": {
              "es": {"name": "Maki Vegetal (6 piezas)",
                     "description": "Pepino, aguacate, daikon encurtido, sésamo"},
              "ja": {"name": "野菜巻き（6個）",
                     "description": "キュウリ、アボカド、大根の漬け物、ゴマ"}
            },
          },
          {
            "name": "Spicy Tuna Roll (8pc)",
            "description": "Tuna, sriracha mayo, cucumber, sesame, tobiko",
            "price": 15.99, "tags": ["spicy"], "display_order": 5,
            "ingredients": ["tuna", "sriracha", "mayo", "cucumber", "sesame seeds",
                            "tobiko", "nori", "sushi rice"],
            "allergens":   ["fish", "eggs", "sesame"],
            "nutrition":   {"calories": 340, "protein_g": 22, "carbs_g": 40, "fat_g": 10,
                            "sodium_mg": 640, "fiber_g": 2},
            "modifications": {
              "remove":  ["tobiko"],
              "swap":    {"heat": ["medium spicy", "very spicy"]}
            },
            "translations": {
              "es": {"name": "Spicy Tuna Roll (8 piezas)", "description": "Atún, mayonesa sriracha, pepino, sésamo, tobiko"},
              "ja": {"name": "スパイシーツナロール（8個）", "description": "マグロ、スリラチャマヨ、キュウリ、ゴマ、とびこ"}
            },
          },
        ]
      },
      {
        "name": "Ramen", "order": 2,
        "available_days": [0,1,2,3,4,5,6],
        "items": [
          {
            "name": "Tonkotsu Ramen",
            "description": "18hr pork bone broth, chashu, soft egg, nori, bamboo",
            "price": 16.99, "tags": ["bestseller"], "display_order": 1,
            "ingredients": ["ramen noodles", "pork bone broth", "chashu pork belly",
                            "soft-boiled egg", "nori", "bamboo shoots", "green onion",
                            "ginger", "garlic", "soy sauce", "sesame oil", "mayu"],
            "allergens":   ["gluten", "eggs", "soy", "sesame"],
            "nutrition":   {"calories": 720, "protein_g": 42, "carbs_g": 68, "fat_g": 28,
                            "sodium_mg": 1480, "fiber_g": 3},
            "modifications": {
              "add":     {"extra chashu": 3.00, "extra egg": 1.50, "corn": 0.50,
                          "extra nori": 0.50, "butter": 0.50},
              "remove":  ["bamboo shoots", "nori"],
              "swap":    {"noodles": ["thin straight", "wavy", "gluten-free rice noodles (+$2)"],
                          "richness": ["regular", "light (less fat)", "rich (extra fat)"]}
            },
            "translations": {
              "es": {"name": "Tonkotsu Ramen",
                     "description": "Caldo de hueso de cerdo 18h, chashu, huevo suave, nori"},
              "ja": {"name": "豚骨ラーメン",
                     "description": "18時間豚骨スープ、チャーシュー、半熟卵、海苔、メンマ"}
            },
          },
          {
            "name": "Shoyu Ramen",
            "description": "Soy-seasoned chicken broth, chicken chashu, bamboo, menma",
            "price": 15.49, "tags": [], "display_order": 2,
            "ingredients": ["ramen noodles", "chicken broth", "soy sauce", "mirin",
                            "chicken chashu", "bamboo shoots", "menma", "green onion",
                            "nori", "sesame oil"],
            "allergens":   ["gluten", "soy", "sesame"],
            "nutrition":   {"calories": 580, "protein_g": 38, "carbs_g": 64, "fat_g": 16,
                            "sodium_mg": 1320, "fiber_g": 3},
            "modifications": {
              "add":    {"soft egg": 1.50, "extra chicken": 2.50, "corn": 0.50},
              "swap":   {"noodles": ["thin straight", "wavy", "gluten-free (+$2)"]}
            },
            "translations": {
              "es": {"name": "Shoyu Ramen", "description": "Caldo de pollo con soja, chashu de pollo, bambú"},
              "ja": {"name": "醤油ラーメン", "description": "鶏がら醤油スープ、鶏チャーシュー、メンマ"}
            },
          },
          {
            "name": "Miso Ramen",
            "description": "White miso broth, corn, butter, bean sprouts, nori",
            "price": 15.99, "tags": ["vegetarian"], "display_order": 3,
            "ingredients": ["ramen noodles", "white miso", "dashi", "corn",
                            "butter", "bean sprouts", "nori", "green onion",
                            "sesame oil", "toasted sesame seeds"],
            "allergens":   ["gluten", "dairy", "soy", "sesame"],
            "nutrition":   {"calories": 560, "protein_g": 18, "carbs_g": 72, "fat_g": 20,
                            "sodium_mg": 1180, "fiber_g": 4},
            "modifications": {
              "add":    {"soft egg": 1.50, "mushrooms": 1.00, "tofu": 1.50},
              "remove": ["butter (vegan option)"],
              "swap":   {"noodles": ["thin straight", "wavy", "gluten-free (+$2)"]}
            },
            "translations": {
              "es": {"name": "Miso Ramen", "description": "Caldo de miso blanco, maíz, mantequilla, brotes de soja"},
              "ja": {"name": "味噌ラーメン", "description": "白味噌スープ、コーン、バター、もやし"}
            },
          },
          {
            "name": "Spicy Tantanmen",
            "description": "Sesame broth, Sichuan peppercorn, minced pork, bok choy",
            "price": 16.49, "tags": ["spicy"], "display_order": 4,
            "ingredients": ["ramen noodles", "sesame broth", "Sichuan peppercorn",
                            "minced pork", "bok choy", "chilli oil", "sesame paste",
                            "soy sauce", "green onion", "sesame seeds"],
            "allergens":   ["gluten", "soy", "sesame", "peanuts"],
            "nutrition":   {"calories": 660, "protein_g": 36, "carbs_g": 62, "fat_g": 28,
                            "sodium_mg": 1380, "fiber_g": 4},
            "modifications": {
              "swap":   {"heat": ["medium", "hot", "extra hot"],
                          "noodles": ["thin straight", "wavy", "gluten-free (+$2)"]},
              "add":    {"extra chilli oil": 0.50, "soft egg": 1.50}
            },
            "translations": {
              "es": {"name": "Tantanmen Picante",
                     "description": "Caldo de sésamo, pimienta de Sichuan, cerdo picado, bok choy"},
              "ja": {"name": "辛い担担麺",
                     "description": "ゴマスープ、四川山椒、ひき肉、青梗菜、チリオイル"}
            },
          },
        ]
      },
      {
        "name": "Small Plates", "order": 3,
        "available_days": [0,1,2,3,4,5,6],
        "items": [
          {
            "name": "Edamame",
            "description": "Sea salt, or spicy sesame",
            "price": 4.99, "tags": ["vegetarian", "vegan", "gluten-free"], "display_order": 1,
            "ingredients": ["edamame", "sea salt", "sesame oil", "chilli flakes"],
            "allergens":   ["soy", "sesame"],
            "nutrition":   {"calories": 160, "protein_g": 14, "carbs_g": 12, "fat_g": 6,
                            "sodium_mg": 240, "fiber_g": 6},
            "modifications": {"swap": {"style": ["sea salt", "spicy sesame"]}},
            "translations": {
              "es": {"name": "Edamame", "description": "Sal marina, o sésamo picante"},
              "ja": {"name": "枝豆", "description": "塩、または辛いゴマ"}
            },
          },
          {
            "name": "Gyoza (6pc)",
            "description": "Pan-fried pork & cabbage, yuzu ponzu dip",
            "price": 8.99, "tags": [], "display_order": 2,
            "ingredients": ["gyoza wrapper", "pork mince", "cabbage", "ginger", "garlic",
                            "sesame oil", "soy sauce", "yuzu", "ponzu"],
            "allergens":   ["gluten", "soy", "sesame"],
            "nutrition":   {"calories": 320, "protein_g": 18, "carbs_g": 28, "fat_g": 14,
                            "sodium_mg": 760, "fiber_g": 2},
            "modifications": {
              "swap":   {"filling": ["pork", "chicken", "vegetable (vegan)"],
                         "cooking": ["pan-fried", "steamed"]}
            },
            "translations": {
              "es": {"name": "Gyoza (6 piezas)", "description": "Frito en sartén, cerdo y col, dip ponzu de yuzu"},
              "ja": {"name": "餃子（6個）", "description": "焼き餃子、豚肉とキャベツ、ゆずポン酢"}
            },
          },
          {
            "name": "Takoyaki (6pc)",
            "description": "Octopus balls, bonito flakes, mayo, okonomiyaki sauce",
            "price": 9.49, "tags": [], "display_order": 3,
            "ingredients": ["takoyaki batter", "flour", "eggs", "octopus", "pickled ginger",
                            "green onion", "mayonnaise", "okonomiyaki sauce",
                            "bonito flakes", "aonori"],
            "allergens":   ["gluten", "eggs", "shellfish", "fish"],
            "nutrition":   {"calories": 340, "protein_g": 16, "carbs_g": 32, "fat_g": 16,
                            "sodium_mg": 680, "fiber_g": 1},
            "modifications": {"add": {"extra sauce": 0.00, "extra mayo": 0.50}},
            "translations": {
              "es": {"name": "Takoyaki (6 piezas)", "description": "Bolas de pulpo, copos de bonito, mayonesa, salsa okonomiyaki"},
              "ja": {"name": "たこ焼き（6個）", "description": "タコ、かつお節、マヨネーズ、お好みソース"}
            },
          },
          {
            "name": "Agedashi Tofu",
            "description": "Crispy tofu, dashi broth, grated daikon, shiso, bonito",
            "price": 7.99, "tags": ["vegetarian"], "display_order": 4,
            "ingredients": ["tofu", "potato starch", "dashi", "mirin", "soy sauce",
                            "daikon", "shiso leaves", "bonito flakes", "ginger"],
            "allergens":   ["gluten", "soy", "fish"],
            "nutrition":   {"calories": 220, "protein_g": 12, "carbs_g": 20, "fat_g": 10,
                            "sodium_mg": 540, "fiber_g": 2},
            "modifications": {
              "swap":   {"broth": ["dashi (fish)", "kombu (vegan)"]},
              "remove": ["bonito flakes (vegan)"]
            },
            "translations": {
              "es": {"name": "Agedashi Tofu", "description": "Tofu crujiente, caldo dashi, daikon rallado, shiso"},
              "ja": {"name": "揚げ出し豆腐", "description": "サクサク豆腐、だし汁、大根おろし、しそ、かつお節"}
            },
          },
        ]
      },
      {
        "name": "Drinks", "order": 4,
        "available_days": [0,1,2,3,4,5,6],
        "items": [
          {
            "name": "Matcha Latte",
            "description": "Ceremonial grade Uji matcha, oat milk, lightly sweetened",
            "price": 4.99, "tags": ["vegetarian"], "display_order": 1,
            "ingredients": ["matcha powder", "oat milk", "hot water", "cane syrup"],
            "allergens":   ["oats"],
            "nutrition":   {"calories": 140, "protein_g": 4, "carbs_g": 22, "fat_g": 4,
                            "sodium_mg": 80, "fiber_g": 1},
            "modifications": {"swap": {"milk": ["oat milk", "whole milk", "almond milk", "soy milk"],
                                       "sugar": ["unsweetened", "lightly sweet", "sweet"]}},
            "translations": {
              "es": {"name": "Latte de Matcha", "description": "Matcha Uji de grado ceremonial, leche de avena"},
              "ja": {"name": "抹茶ラテ", "description": "宇治産抹茶、オーツミルク、ほんのり甘い"}
            },
          },
          {
            "name": "Ramune Soda",
            "description": "Original or melon, Japanese marble soda",
            "price": 3.49, "tags": ["vegetarian"], "display_order": 2,
            "ingredients": ["carbonated water", "cane sugar", "natural flavouring"],
            "allergens":   [],
            "nutrition":   {"calories": 90, "protein_g": 0, "carbs_g": 23, "fat_g": 0, "sodium_mg": 20},
            "modifications": {"swap": {"flavour": ["original", "melon", "lychee"]}},
            "translations": {
              "es": {"name": "Ramune Soda", "description": "Original o melón, soda japonesa con canica"},
              "ja": {"name": "ラムネ", "description": "オリジナルまたはメロン"}
            },
          },
          {
            "name": "Japanese Beer (Sapporo)",
            "description": "Sapporo 330ml, crisp lager",
            "price": 5.99, "tags": [], "display_order": 3,
            "ingredients": ["water", "malted barley", "hops", "corn starch"],
            "allergens":   ["gluten"],
            "nutrition":   {"calories": 140, "protein_g": 1, "carbs_g": 12, "fat_g": 0, "sodium_mg": 14},
            "modifications": {},
            "translations": {
              "es": {"name": "Cerveza Japonesa (Sapporo)", "description": "Sapporo 330ml, lager crujiente"},
              "ja": {"name": "サッポロビール", "description": "330ml、すっきりラガー"}
            },
          },
          {
            "name": "Hot Green Tea",
            "description": "Sencha, unlimited refills, served in cast iron",
            "price": 2.99, "tags": ["vegetarian", "vegan"], "display_order": 4,
            "ingredients": ["sencha green tea", "hot water"],
            "allergens":   [],
            "nutrition":   {"calories": 2, "protein_g": 0, "carbs_g": 0, "fat_g": 0, "sodium_mg": 2},
            "modifications": {"swap": {"style": ["sencha", "genmaicha", "hojicha"]}},
            "translations": {
              "es": {"name": "Té Verde Caliente", "description": "Sencha, refills ilimitados"},
              "ja": {"name": "緑茶（煎茶）", "description": "煎茶、おかわり自由、鉄瓶で提供"}
            },
          },
        ]
      },
    ],
    "price_rules": [
      {
        "name": "Sushi Happy Hour",
        "label": "Sushi Happy Hour",
        "description": "20% off sushi & sashimi, Tue–Thu 5pm–6:30pm",
        "rule_type": "percentage_off",
        "value": 20,
        "applies_to": "category",
        "applies_to_name": "Sushi & Sashimi",
        "valid_days": [2, 3, 4],  # Tue, Wed, Thu
        "valid_from": time(17, 0), "valid_until": time(18, 30),
        "priority": 10,
      },
      {
        "name": "Ramen Wednesday",
        "label": "Ramen Wednesday",
        "description": "$3 off all ramen bowls every Wednesday",
        "rule_type": "fixed_off",
        "value": 3.00,
        "applies_to": "category",
        "applies_to_name": "Ramen",
        "valid_days": [3],  # Wednesday
        "valid_from": None, "valid_until": None,
        "priority": 5,
      },
    ],
    "order_rules": [
      {
        "rule_type": "max_total",
        "value": 120.00,
        "description": "Maximum order value $120 for delivery orders",
        "error_message": "Delivery orders are capped at $120 — for larger orders, please call us.",
      },
    ],
  },
]


# ─────────────────────────────────────────────────────────────────────────────
# CUSTOMER PROFILES
# ─────────────────────────────────────────────────────────────────────────────

CUSTOMER_PROFILES = [
  {
    "phone": "+1-555-0101",
    "name": "Alex Chen",
    "language_code": "en",
    "dietary_restrictions": [],
    "allergens": ["peanuts"],
    "strict_allergens": ["peanuts"],      # anaphylactic
    "preferences": {"spice_level": "medium", "portion": "large"},
  },
  {
    "phone": "+1-555-0102",
    "name": "Sofia Martinez",
    "language_code": "es",
    "dietary_restrictions": ["vegetarian"],
    "allergens": ["shellfish", "fish"],
    "strict_allergens": [],
    "preferences": {"spice_level": "low"},
  },
  {
    "phone": "+81-90-0001",
    "name": "Yuki Tanaka",
    "language_code": "ja",
    "dietary_restrictions": ["gluten-free"],
    "allergens": ["gluten"],
    "strict_allergens": ["gluten"],       # celiac
    "preferences": {},
  },
  {
    "phone": "+1-555-0104",
    "name": "Jordan Blake",
    "language_code": "en",
    "dietary_restrictions": ["vegan"],
    "allergens": ["dairy", "eggs"],
    "strict_allergens": [],
    "preferences": {"spice_level": "high"},
  },
  {
    "phone": "+1-555-0105",
    "name": "Priya Singh",
    "language_code": "en",
    "dietary_restrictions": [],
    "allergens": ["tree_nuts"],
    "strict_allergens": [],
    "preferences": {"spice_level": "high", "portion": "medium"},
  },
]


# ─────────────────────────────────────────────────────────────────────────────
# HISTORICAL ORDER DATA (seeds item_affinity + order history)
# ─────────────────────────────────────────────────────────────────────────────

HISTORICAL_ORDERS = {
  "smokehouse": [
    (["Big Smoke Burger", "Loaded Fries", "Classic Coke"], "+1-555-0101"),
    (["BBQ Ribs Platter", "Loaded Fries", "Chocolate Milkshake"], "+1-555-0101"),
    (["BBQ Ribs Platter", "Coleslaw", "Chocolate Milkshake"], None),
    (["Big Smoke Burger", "Onion Rings", "Classic Coke"], None),
    (["BBQ Ribs Platter", "Loaded Fries", "Iced Tea"], None),
    (["Crispy Chicken Sando", "Loaded Fries", "Lemonade"], None),
    (["BBQ Ribs Platter", "Corn on the Cob", "Chocolate Milkshake"], None),
    (["Big Smoke Burger", "Loaded Fries", "Chocolate Milkshake"], None),
    (["Garden Stack Burger", "Coleslaw", "Lemonade"], "+1-555-0104"),
    (["Smokehouse Melt", "Loaded Fries", "Iced Tea"], None),
    (["BBQ Ribs Platter", "Loaded Fries", "Classic Coke"], None),
    (["Big Smoke Burger", "Onion Rings", "Chocolate Milkshake"], None),
    (["BBQ Ribs Platter", "Coleslaw", "Iced Tea"], None),
    (["Crispy Chicken Sando", "Onion Rings", "Classic Coke"], None),
    (["BBQ Ribs Platter", "Loaded Fries", "Lemonade"], None),
  ],
  "bella": [
    (["Margherita Classica", "Tiramisu", "San Pellegrino"], "+1-555-0102"),
    (["Spaghetti Carbonara", "Tiramisu", "Espresso"], None),
    (["Margherita Classica", "Panna Cotta", "Limoncello"], None),
    (["Tagliatelle al Ragù", "Tiramisu", "Espresso"], None),
    (["Quattro Formaggi", "Gelato (3 scoops)", "San Pellegrino"], "+1-555-0105"),
    (["Spaghetti Carbonara", "Panna Cotta", "Limoncello"], None),
    (["Diavola", "Tiramisu", "Espresso"], None),
    (["Margherita Classica", "Spaghetti Carbonara", "San Pellegrino"], None),
    (["Prosciutto e Funghi", "Tiramisu", "Espresso"], None),
    (["Penne Arrabbiata", "Gelato (3 scoops)", "Limoncello"], None),
    (["Margherita Classica", "Tiramisu", "Espresso"], None),
    (["Napoletana", "Panna Cotta", "San Pellegrino"], None),
    (["Risotto ai Funghi", "Tiramisu", "Espresso"], "+1-555-0102"),
  ],
  "tokyo": [
    (["Tonkotsu Ramen", "Gyoza (6pc)", "Hot Green Tea"], None),
    (["Salmon Sashimi (8pc)", "Dragon Roll (8pc)", "Matcha Latte"], None),
    (["Tonkotsu Ramen", "Edamame", "Japanese Beer (Sapporo)"], None),
    (["Dragon Roll (8pc)", "Edamame", "Ramune Soda"], None),
    (["Shoyu Ramen", "Gyoza (6pc)", "Hot Green Tea"], "+1-555-0101"),
    (["Salmon Sashimi (8pc)", "Tuna Nigiri (6pc)", "Hot Green Tea"], None),
    (["Tonkotsu Ramen", "Takoyaki (6pc)", "Japanese Beer (Sapporo)"], None),
    (["Miso Ramen", "Edamame", "Matcha Latte"], None),
    (["Vegetable Maki (6pc)", "Agedashi Tofu", "Hot Green Tea"], "+1-555-0104"),
    (["Spicy Tantanmen", "Gyoza (6pc)", "Japanese Beer (Sapporo)"], "+1-555-0105"),
    (["Dragon Roll (8pc)", "Salmon Sashimi (8pc)", "Matcha Latte"], None),
    (["Tonkotsu Ramen", "Gyoza (6pc)", "Ramune Soda"], None),
    (["Shoyu Ramen", "Takoyaki (6pc)", "Hot Green Tea"], None),
    (["Salmon Sashimi (8pc)", "Edamame", "Matcha Latte"], None),
    (["Spicy Tuna Roll (8pc)", "Gyoza (6pc)", "Japanese Beer (Sapporo)"], None),
  ],
}


# ─────────────────────────────────────────────────────────────────────────────
# SEED RUNNER
# ─────────────────────────────────────────────────────────────────────────────

async def run_seed():
    """Idempotent — only inserts if restaurants table is empty."""
    async with AsyncSessionFactory() as db:
        existing = await db.execute(select(Restaurant))
        if existing.scalars().first():
            logger.info("Database already seeded — skipping.")
            return

        logger.info("Seeding database...")

        restaurant_map: dict[str, Restaurant] = {}
        category_map:   dict[str, MenuCategory] = {}
        item_map:       dict[str, MenuItem] = {}    # "restaurant_name::item_name" → MenuItem

        # ── Restaurants + Categories + Items ─────────────────────────────
        for rdata in RESTAURANTS:
            r = Restaurant(
                name=rdata["name"],
                cuisine_type=rdata["cuisine_type"],
                personality=rdata["personality"],
                special_instructions=rdata["special_instructions"],
            )
            db.add(r)
            await db.flush()
            restaurant_map[rdata["name"]] = r

            for cdata in rdata["categories"]:
                cat = MenuCategory(
                    restaurant_id=r.id,
                    name=cdata["name"],
                    display_order=cdata["order"],
                )
                db.add(cat)
                await db.flush()
                category_map[f"{r.id}::{cdata['name']}"] = cat

                for idata in cdata["items"]:
                    item = MenuItem(
                        restaurant_id=r.id,
                        category_id=cat.id,
                        name=idata["name"],
                        description=idata.get("description", ""),
                        price=Decimal(str(idata["price"])),
                        is_available=True,
                        tags=idata.get("tags", []),
                        display_order=idata.get("display_order", 0),
                        ingredients=idata.get("ingredients", []),
                        allergens=idata.get("allergens", []),
                        nutrition_info=idata.get("nutrition", {}),
                        allowed_modifications=idata.get("modifications", {}),
                        translations=idata.get("translations", {}),
                        available_days=cdata.get("available_days", list(range(7))),
                    )
                    db.add(item)
                    await db.flush()
                    item_map[f"{r.name}::{idata['name']}"] = item

            # ── Price Rules ───────────────────────────────────────────────
            for prdata in rdata.get("price_rules", []):
                # Resolve category/item IDs
                applies_to_ids = []
                if prdata.get("applies_to_name"):
                    cat_key = f"{r.id}::{prdata['applies_to_name']}"
                    if cat_key in category_map:
                        applies_to_ids = [category_map[cat_key].id]
                elif prdata.get("applies_to_names"):
                    for iname in prdata["applies_to_names"]:
                        key = f"{r.name}::{iname}"
                        if key in item_map:
                            applies_to_ids.append(item_map[key].id)

                pr = PriceRule(
                    restaurant_id=r.id,
                    name=prdata["name"],
                    label=prdata["label"],
                    description=prdata.get("description"),
                    rule_type=prdata["rule_type"],
                    value=Decimal(str(prdata["value"])),
                    applies_to=prdata["applies_to"],
                    applies_to_ids=applies_to_ids,
                    valid_days=prdata.get("valid_days", list(range(7))),
                    valid_from=prdata.get("valid_from"),
                    valid_until=prdata.get("valid_until"),
                    priority=prdata.get("priority", 0),
                    is_active=True,
                )
                db.add(pr)

            # ── Order Rules ───────────────────────────────────────────────
            for ordata in rdata.get("order_rules", []):
                or_ = OrderRule(
                    restaurant_id=r.id,
                    rule_type=ordata["rule_type"],
                    value=Decimal(str(ordata["value"])) if ordata.get("value") else None,
                    description=ordata["description"],
                    error_message=ordata.get("error_message"),
                    is_active=True,
                )
                db.add(or_)

        # ── Customer Profiles ─────────────────────────────────────────────
        for pdata in CUSTOMER_PROFILES:
            profile = CustomerProfile(
                phone=pdata["phone"],
                name=pdata["name"],
                language_code=pdata["language_code"],
                dietary_restrictions=pdata["dietary_restrictions"],
                allergens=pdata["allergens"],
                strict_allergens=pdata["strict_allergens"],
                preferences=pdata["preferences"],
            )
            db.add(profile)

        await db.commit()

        # ── Historical Orders (for affinity data) ─────────────────────────
        logger.info("Seeding historical orders for affinity computation...")

        hist_map = {
            "smokehouse": restaurant_map["The Smokehouse"],
            "bella":      restaurant_map["Bella Napoli"],
            "tokyo":      restaurant_map["Tokyo Bites"],
        }

        for rest_key, orders in HISTORICAL_ORDERS.items():
            r = hist_map[rest_key]
            for item_names, phone in orders:
                order = Order(
                    restaurant_id=r.id,
                    session_id=f"seed-{random.randint(100000, 999999)}",
                    customer_phone=phone,
                    status="completed",
                    total=Decimal("0"),
                )
                db.add(order)
                await db.flush()

                total = Decimal("0")
                for iname in item_names:
                    key = f"{r.name}::{iname}"
                    item = item_map.get(key)
                    if not item:
                        continue
                    oi = OrderItem(
                        order_id=order.id,
                        menu_item_id=item.id,
                        name_snapshot=item.name,
                        price_snapshot=item.price,
                        original_price=item.price,
                        quantity=1,
                        subtotal=item.price,
                    )
                    db.add(oi)
                    total += item.price

                order.total = total
                await db.flush()

        await db.commit()

        # ── Compute initial affinity scores ───────────────────────────────
        logger.info("Computing initial item affinity scores...")
        from sqlalchemy import text
        async with AsyncSessionFactory() as db2:
            await db2.execute(text("""
                INSERT INTO item_affinity (item_a_id, item_b_id, restaurant_id, co_occurrence, lift_score)
                SELECT
                    a.menu_item_id,
                    b.menu_item_id,
                    o.restaurant_id,
                    count(*)::int,
                    (count(*)::float /
                        NULLIF((SELECT count(*) FROM order_items oi2 WHERE oi2.menu_item_id = a.menu_item_id), 0)
                    )::numeric(6,3)
                FROM   order_items a
                JOIN   order_items b ON a.order_id = b.order_id AND a.menu_item_id != b.menu_item_id
                JOIN   orders o      ON o.id = a.order_id AND o.status = 'completed'
                GROUP  BY a.menu_item_id, b.menu_item_id, o.restaurant_id
                ON CONFLICT (item_a_id, item_b_id) DO UPDATE
                    SET co_occurrence = EXCLUDED.co_occurrence,
                        lift_score    = EXCLUDED.lift_score,
                        last_computed = NOW()
            """))
            await db2.commit()

        logger.info(
            f"Seed complete: {len(RESTAURANTS)} restaurants, "
            f"{len(item_map)} items, "
            f"{len(CUSTOMER_PROFILES)} profiles, "
            f"historical orders seeded."
        )
