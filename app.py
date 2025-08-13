from flask import Flask, request, jsonify, send_from_directory
import sqlite3
import os
import random
from datetime import datetime, timedelta
import re

app = Flask(__name__)
DB = 'meal_planner.db'

# Initialiseer database
def init_db():
    with sqlite3.connect(DB) as conn:
        c = conn.cursor()
        # Recepten tabel
        c.execute('''CREATE TABLE IF NOT EXISTS recipes (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    category TEXT)''')
        
        # Ingrediënten tabel (gekoppeld aan recepten)
        c.execute('''CREATE TABLE IF NOT EXISTS ingredients (
                    id INTEGER PRIMARY KEY,
                    recipe_id INTEGER,
                    name TEXT NOT NULL,
                    quantity TEXT NOT NULL,
                    supermarket TEXT NOT NULL,
                    FOREIGN KEY(recipe_id) REFERENCES recipes(id))''')
        
        # Maaltijdenplan tabel
        c.execute('''CREATE TABLE IF NOT EXISTS meal_plan (
                    date TEXT PRIMARY KEY,
                    recipe_id INTEGER,
                    FOREIGN KEY(recipe_id) REFERENCES recipes(id))''')
        conn.commit()

# Hulpfunctie om hoeveelheden te parsen
def parse_quantity(qty_str):
    """
    Parse hoeveelheid string naar numerieke waarde en eenheid
    Retourneert (waarde, eenheid) of (None, None) als parsen mislukt
    """
    # Verwerk gevallen zoals "200g", "200 g", "1.5kg", "1,5kg"
    qty_str = qty_str.replace(',', '.').strip()
    
    # Probeer nummer en eenheid te extraheren
    match = re.match(r'^([\d.]+)\s*(\D*)$', qty_str)
    if match:
        num_str, unit = match.groups()
        try:
            value = float(num_str)
            return value, unit.strip()
        except ValueError:
            pass
    
    # Probeer breuken te verwerken (bijv. "1/2")
    match = re.match(r'^(\d+)\s*/\s*(\d+)\s*(\D*)$', qty_str)
    if match:
        numerator, denominator, unit = match.groups()
        try:
            value = float(numerator) / float(denominator)
            return value, unit.strip()
        except ValueError:
            pass
    
    return None, None

# API Endpoints
@app.route('/')
def index():
    return send_from_directory(os.getcwd(), 'index.html')

# ========= RECEPTEN =========
@app.route('/recipes', methods=['GET'])
def get_recipes():
    with sqlite3.connect(DB) as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM recipes')
        recipes = [{'id': r[0], 'name': r[1], 'category': r[2], 'ingredients': []} for r in c.fetchall()]
        
        for recipe in recipes:
            c.execute('SELECT * FROM ingredients WHERE recipe_id = ?', (recipe['id'],))
            recipe['ingredients'] = [
                {'name': i[2], 'quantity': i[3], 'supermarket': i[4]} 
                for i in c.fetchall()
            ]
    return jsonify(recipes)

@app.route('/recipes/<int:id>', methods=['GET'])
def get_recipe(id):
    with sqlite3.connect(DB) as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM recipes WHERE id = ?', (id,))
        recipe = c.fetchone()
        if not recipe:
            return jsonify({"error": "Recept niet gevonden"}), 404
        
        c.execute('SELECT * FROM ingredients WHERE recipe_id = ?', (id,))
        ingredients = [
            {'name': i[2], 'quantity': i[3], 'supermarket': i[4]} 
            for i in c.fetchall()
        ]
        
        return jsonify({
            'id': recipe[0],
            'name': recipe[1],
            'category': recipe[2],
            'ingredients': ingredients
        })

@app.route('/recipes', methods=['POST'])
def add_recipe():
    data = request.json
    with sqlite3.connect(DB) as conn:
        c = conn.cursor()
        c.execute('INSERT INTO recipes (name, category) VALUES (?, ?)', 
                 (data['name'], data['category']))
        recipe_id = c.lastrowid
        
        for ing in data['ingredients']:
            c.execute('''INSERT INTO ingredients 
                        (recipe_id, name, quantity, supermarket) 
                        VALUES (?, ?, ?, ?)''',
                     (recipe_id, ing['name'], ing['quantity'], ing['supermarket']))
        conn.commit()
    return jsonify({"status": "success"}), 201

@app.route('/recipes/<int:id>', methods=['PUT'])
def update_recipe(id):
    data = request.json
    with sqlite3.connect(DB) as conn:
        c = conn.cursor()
        
        # Update recept
        c.execute('UPDATE recipes SET name = ?, category = ? WHERE id = ?', 
                 (data['name'], data['category'], id))
        
        # Verwijder bestaande ingrediënten
        c.execute('DELETE FROM ingredients WHERE recipe_id = ?', (id,))
        
        # Voeg nieuwe ingrediënten toe
        for ing in data['ingredients']:
            c.execute('''INSERT INTO ingredients 
                        (recipe_id, name, quantity, supermarket) 
                        VALUES (?, ?, ?, ?)''',
                     (id, ing['name'], ing['quantity'], ing['supermarket']))
        
        conn.commit()
    return jsonify({"status": "success"})

@app.route('/recipes/<int:id>', methods=['DELETE'])
def delete_recipe(id):
    with sqlite3.connect(DB) as conn:
        c = conn.cursor()
        c.execute('DELETE FROM ingredients WHERE recipe_id = ?', (id,))
        c.execute('DELETE FROM recipes WHERE id = ?', (id,))
        conn.commit()
    return jsonify({"status": "success"})

# ========= MAALTIJDEN PLAN =========
@app.route('/meal_plan', methods=['GET'])
def get_meal_plan():
    with sqlite3.connect(DB) as conn:
        c = conn.cursor()
        c.execute('''SELECT mp.date, r.id, r.name 
                    FROM meal_plan mp
                    JOIN recipes r ON mp.recipe_id = r.id
                    ORDER BY mp.date''')
        return jsonify([{'date': row[0], 'recipe_id': row[1], 'recipe_name': row[2]} 
                        for row in c.fetchall()])

@app.route('/assign_recipe', methods=['POST'])
def assign_recipe():
    data = request.json
    date = data['date']
    recipe_id = data['recipe_id']
    
    with sqlite3.connect(DB) as conn:
        c = conn.cursor()
        if recipe_id:
            # Wijs recept toe aan dag
            c.execute('INSERT OR REPLACE INTO meal_plan (date, recipe_id) VALUES (?, ?)', 
                     (date, recipe_id))
        else:
            # Verwijder recept van dag
            c.execute('DELETE FROM meal_plan WHERE date = ?', (date,))
        conn.commit()
    return jsonify({"status": "success"})

@app.route('/generate_plan', methods=['POST'])
def generate_plan():
    days = int(request.args.get('days', 7))
    with sqlite3.connect(DB) as conn:
        c = conn.cursor()
        
        # Wis bestaand plan
        c.execute('DELETE FROM meal_plan')
        
        # Haal alle recept ID's op
        c.execute('SELECT id FROM recipes')
        recipe_ids = [r[0] for r in c.fetchall()]
        
        if not recipe_ids:
            return jsonify({"status": "geen recepten"}), 400
            
        # Genereer plan
        start_date = datetime.now()
        for i in range(days):
            date = (start_date + timedelta(days=i)).strftime('%Y-%m-%d')
            recipe_id = random.choice(recipe_ids)
            c.execute('INSERT OR REPLACE INTO meal_plan (date, recipe_id) VALUES (?, ?)', 
                     (date, recipe_id))
        
        conn.commit()
    return jsonify({"status": "success"})

@app.route('/clear_plan', methods=['POST'])
def clear_plan():
    with sqlite3.connect(DB) as conn:
        c = conn.cursor()
        c.execute('DELETE FROM meal_plan')
        conn.commit()
    return jsonify({"status": "success"})

@app.route('/meal_plan/<date>', methods=['DELETE'])
def remove_from_plan(date):
    with sqlite3.connect(DB) as conn:
        c = conn.cursor()
        c.execute('DELETE FROM meal_plan WHERE date = ?', (date,))
        conn.commit()
    return jsonify({"status": "success"})

# ========= BOODSCHAPPENLIJST =========
@app.route('/shopping_list', methods=['GET'])
def get_shopping_list():
    with sqlite3.connect(DB) as conn:
        c = conn.cursor()
        # Haal alle ingrediënten op voor geplande maaltijden
        c.execute('''SELECT i.name, i.quantity, i.supermarket
                    FROM meal_plan mp
                    JOIN ingredients i ON mp.recipe_id = i.recipe_id
                    ORDER BY i.supermarket, i.name''')
        
        all_ingredients = c.fetchall()
        
        # Groepeer per supermarket en ingrediënt
        groups = {}
        for name, qty, supermarket in all_ingredients:
            if supermarket not in groups:
                groups[supermarket] = {}
            if name not in groups[supermarket]:
                groups[supermarket][name] = []
            groups[supermarket][name].append(qty)
        
        # Verwerk groepen om hoeveelheden op te tellen
        result = {"groups": []}
        for supermarket, ingredients in groups.items():
            supermarket_group = {
                "supermarket": supermarket,
                "items": []
            }
            
            for ingredient, quantities in ingredients.items():
                # Probeer hoeveelheden op te tellen
                total_value = 0
                unit = None
                valid_aggregation = True
                parsed_quantities = []
                
                for qty in quantities:
                    value, unit_part = parse_quantity(qty)
                    if value is None:
                        valid_aggregation = False
                        break
                    
                    # Controleer of eenheden consistent zijn
                    if unit is None:
                        unit = unit_part
                    elif unit != unit_part:
                        valid_aggregation = False
                        break
                    
                    total_value += value
                    parsed_quantities.append(qty)
                
                # Formatteer weergave hoeveelheid
                if valid_aggregation and unit is not None:
                    # Formatteer totaal om nullen achter de komma te verwijderen
                    total_str = f"{total_value:g}"
                    if unit:
                        total_str += f" {unit}"
                    display_quantity = f"{', '.join(parsed_quantities)} (totaal {total_str})"
                else:
                    display_quantity = ', '.join(quantities)
                
                supermarket_group["items"].append({
                    "ingredient": ingredient,
                    "display_quantity": display_quantity
                })
            
            # Sorteer items op naam
            supermarket_group["items"].sort(key=lambda x: x["ingredient"].lower())
            result["groups"].append(supermarket_group)
        
        # Sorteer groepen op supermarket naam
        result["groups"].sort(key=lambda x: x["supermarket"])
        
        return jsonify(result)

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=True)