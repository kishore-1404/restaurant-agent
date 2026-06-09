import logging
from sqlalchemy import select
from db.base import AsyncSessionFactory
from db.models import Restaurant, MenuCategory, MenuItem

logger = logging.getLogger(__name__)

RESTAURANTS = [
    {
        "name": "The Smokehouse",
        "cuisine_type": "american",
        "personality": "casual, fun, uses American slang, calls customers 'partner'",
        "special_instructions": "All burgers can be made with beef, chicken, or veggie patty.",
        "categories": [
            {
                "name": "Mains", "order": 1,
                "items": [
                    {"name": "Big Smoke Burger",    "price": 12.99, "desc": "Double beef, cheddar, house sauce", "tags": ["bestseller"]},
                    {"name": "BBQ Ribs Platter",    "price": 18.49, "desc": "Half rack, slow-smoked, coleslaw", "tags": ["gluten-free"]},
                    {"name": "Crispy Chicken Sando","price": 11.99, "desc": "Buttermilk fried, pickles, sriracha mayo", "tags": ["spicy"]},
                    {"name": "Smokehouse Melt",     "price": 13.49, "desc": "Pulled pork, gruyere, brioche", "tags": []},
                    {"name": "Garden Stack Burger", "price": 10.99, "desc": "Veg patty, avocado, sprouts", "tags": ["vegetarian"]},
                ]
            },
            {
                "name": "Sides", "order": 2,
                "items": [
                    {"name": "Loaded Fries",   "price": 5.99, "desc": "Cheese, bacon, jalapeños", "tags": ["spicy"]},
                    {"name": "Onion Rings",    "price": 4.49, "desc": "Beer-battered, chipotle dip", "tags": ["vegetarian"]},
                    {"name": "Coleslaw",       "price": 2.99, "desc": "House recipe, creamy", "tags": ["vegetarian", "gluten-free"]},
                    {"name": "Corn on the Cob","price": 3.49, "desc": "Buttered, smoked paprika", "tags": ["vegetarian", "gluten-free"]},
                ]
            },
            {
                "name": "Drinks", "order": 3,
                "items": [
                    {"name": "Classic Coke",    "price": 2.49, "desc": "330ml can", "tags": []},
                    {"name": "Lemonade",        "price": 2.99, "desc": "Fresh squeezed", "tags": ["vegetarian"]},
                    {"name": "Chocolate Milkshake","price": 5.49, "desc": "Hand-spun, whipped cream", "tags": ["vegetarian"]},
                    {"name": "Iced Tea",        "price": 2.99, "desc": "Sweet or unsweetened", "tags": []},
                ]
            },
        ],
    },
    {
        "name": "Bella Napoli",
        "cuisine_type": "italian",
        "personality": "warm, romantic, uses occasional Italian phrases, very welcoming",
        "special_instructions": "All pizzas available gluten-free base (+$2). Pasta can be made vegan on request.",
        "categories": [
            {
                "name": "Pizzas", "order": 1,
                "items": [
                    {"name": "Margherita Classica",  "price": 13.99, "desc": "San Marzano tomato, fior di latte, basil", "tags": ["vegetarian", "bestseller"]},
                    {"name": "Diavola",              "price": 15.99, "desc": "Spicy salami, chilli, mozzarella", "tags": ["spicy"]},
                    {"name": "Quattro Formaggi",     "price": 16.49, "desc": "Mozzarella, gorgonzola, parmesan, ricotta", "tags": ["vegetarian"]},
                    {"name": "Prosciutto e Funghi",  "price": 16.99, "desc": "Parma ham, mushrooms, mozzarella", "tags": []},
                    {"name": "Napoletana",           "price": 14.49, "desc": "Anchovies, capers, olives, tomato", "tags": []},
                ]
            },
            {
                "name": "Pasta", "order": 2,
                "items": [
                    {"name": "Spaghetti Carbonara",  "price": 14.50, "desc": "Guanciale, egg yolk, pecorino, black pepper", "tags": ["bestseller"]},
                    {"name": "Penne Arrabbiata",     "price": 12.99, "desc": "Spicy tomato, garlic, fresh chilli", "tags": ["vegetarian", "spicy"]},
                    {"name": "Tagliatelle al Ragù",  "price": 15.99, "desc": "Slow-cooked beef & pork ragu, 6 hours", "tags": []},
                    {"name": "Risotto ai Funghi",    "price": 14.99, "desc": "Wild mushroom, truffle oil, parmesan", "tags": ["vegetarian", "gluten-free"]},
                ]
            },
            {
                "name": "Desserts", "order": 3,
                "items": [
                    {"name": "Tiramisu",       "price": 7.50, "desc": "Classic, mascarpone, ladyfingers, espresso", "tags": ["vegetarian"]},
                    {"name": "Panna Cotta",    "price": 6.99, "desc": "Vanilla, berry coulis", "tags": ["vegetarian", "gluten-free"]},
                    {"name": "Gelato (3 scoops)", "price": 5.99, "desc": "Ask for today's flavours", "tags": ["vegetarian"]},
                ]
            },
            {
                "name": "Drinks", "order": 4,
                "items": [
                    {"name": "San Pellegrino",  "price": 3.49, "desc": "500ml sparkling water", "tags": []},
                    {"name": "Espresso",        "price": 2.99, "desc": "Double shot", "tags": []},
                    {"name": "Limoncello",      "price": 5.99, "desc": "House-made, digestif", "tags": []},
                ]
            },
        ],
    },
    {
        "name": "Tokyo Bites",
        "cuisine_type": "japanese",
        "personality": "minimal, precise, respectful, uses 'Irasshaimase' as greeting, very attentive",
        "special_instructions": "Sashimi is market-fresh daily. Ramen broth takes 18 hours. All dishes gluten-free available with tamari.",
        "categories": [
            {
                "name": "Sushi & Sashimi", "order": 1,
                "items": [
                    {"name": "Salmon Sashimi (8pc)",   "price": 16.00, "desc": "Atlantic salmon, wasabi, pickled ginger", "tags": ["gluten-free", "bestseller"]},
                    {"name": "Tuna Nigiri (6pc)",      "price": 14.50, "desc": "Bluefin tuna over seasoned rice", "tags": ["gluten-free"]},
                    {"name": "Dragon Roll (8pc)",      "price": 17.99, "desc": "Prawn tempura, avocado, tobiko", "tags": ["bestseller"]},
                    {"name": "Vegetable Maki (6pc)",   "price": 9.99,  "desc": "Cucumber, avocado, pickled daikon", "tags": ["vegetarian", "vegan"]},
                    {"name": "Spicy Tuna Roll (8pc)",  "price": 15.99, "desc": "Tuna, sriracha mayo, sesame", "tags": ["spicy"]},
                ]
            },
            {
                "name": "Ramen", "order": 2,
                "items": [
                    {"name": "Tonkotsu Ramen",   "price": 16.99, "desc": "18hr pork bone broth, chashu, soft egg, nori", "tags": ["bestseller"]},
                    {"name": "Shoyu Ramen",      "price": 15.49, "desc": "Soy-seasoned chicken broth, bamboo, menma", "tags": []},
                    {"name": "Miso Ramen",       "price": 15.99, "desc": "White miso, corn, butter, bean sprouts", "tags": ["vegetarian"]},
                    {"name": "Spicy Tantanmen",  "price": 16.49, "desc": "Sesame broth, minced pork, chilli oil", "tags": ["spicy"]},
                ]
            },
            {
                "name": "Small Plates", "order": 3,
                "items": [
                    {"name": "Edamame",          "price": 4.99, "desc": "Salted or spicy", "tags": ["vegetarian", "vegan", "gluten-free"]},
                    {"name": "Gyoza (6pc)",      "price": 8.99, "desc": "Pan-fried pork & cabbage, ponzu dip", "tags": []},
                    {"name": "Takoyaki (6pc)",   "price": 9.49, "desc": "Octopus balls, mayo, bonito flakes", "tags": []},
                    {"name": "Agedashi Tofu",    "price": 7.99, "desc": "Crispy tofu, dashi broth, scallion", "tags": ["vegetarian"]},
                ]
            },
            {
                "name": "Drinks", "order": 4,
                "items": [
                    {"name": "Matcha Latte",     "price": 4.99, "desc": "Ceremonial grade, oat milk", "tags": ["vegetarian"]},
                    {"name": "Ramune Soda",      "price": 3.49, "desc": "Original or melon", "tags": ["vegetarian"]},
                    {"name": "Japanese Beer",    "price": 5.99, "desc": "Sapporo 330ml", "tags": []},
                    {"name": "Hot Green Tea",    "price": 2.99, "desc": "Sencha, unlimited refills", "tags": ["vegetarian", "vegan"]},
                ]
            },
        ],
    },
]


async def run_seed():
    """Idempotent seed — only inserts if the table is empty."""
    async with AsyncSessionFactory() as db:
        existing = await db.execute(select(Restaurant))
        if existing.scalars().first():
            logger.info("Database already seeded — skipping.")
            return

        logger.info("Seeding database with 3 restaurants...")
        for r_data in RESTAURANTS:
            restaurant = Restaurant(
                name=r_data["name"],
                cuisine_type=r_data["cuisine_type"],
                personality=r_data["personality"],
                special_instructions=r_data["special_instructions"],
            )
            db.add(restaurant)
            await db.flush()

            for cat_data in r_data["categories"]:
                category = MenuCategory(
                    restaurant_id=restaurant.id,
                    name=cat_data["name"],
                    display_order=cat_data["order"],
                )
                db.add(category)
                await db.flush()

                for item_data in cat_data["items"]:
                    item = MenuItem(
                        restaurant_id=restaurant.id,
                        category_id=category.id,
                        name=item_data["name"],
                        description=item_data["desc"],
                        price=item_data["price"],
                        tags=item_data["tags"],
                        is_available=True,
                    )
                    db.add(item)

        await db.commit()
        logger.info("Seed complete: 3 restaurants, 39 menu items.")
