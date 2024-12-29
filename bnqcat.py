from flask import Flask, render_template, request
import pandas as pd
from fuzzywuzzy import fuzz, process
import webbrowser
import threading
import time
import os

app = Flask(__name__, template_folder="templates")

# Get the base directory of the current script
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Load the product data from the CSV file (first file)
df = pd.read_csv(os.path.join(BASE_DIR, "product_list.csv"), header=None, names=["Product Type", "Product Code"])
df["Product Type"] = df["Product Type"].astype(str).str.strip()

# Load the category tree data from the second file
category_df = pd.read_csv(os.path.join(BASE_DIR, "category_tree.csv"), header=None, names=["Category Tree", "Code"])
category_df["Category Tree"] = category_df["Category Tree"].astype(str).str.strip()

# Path to the item_specs.xlsx file
item_specs_file = os.path.join(BASE_DIR, "item_specs.xlsx")

def expand_synonyms(text):
    SYNONYMS = {
        "hose pipe": "garden hose",
        "tap connector": "faucet connector",
        "paint remover": "paint stripper"
    }
    text_lower = text.lower()
    for phrase, expansion in SYNONYMS.items():
        if phrase in text_lower:
            text_lower += " " + expansion
    return text_lower

def find_closest_matches(query, df, n=10, method="combined"):
    query = expand_synonyms(query)

    def partial_score(product_name, q):
        return fuzz.partial_ratio(product_name.lower(), q)

    def token_score(product_name, q):
        return fuzz.token_set_ratio(product_name.lower(), q)

    def combined_score(product_name, q):
        p = partial_score(product_name, q)
        t = token_score(product_name, q)
        return 0.5 * p + 0.5 * t

    if method == "partial":
        df["Score"] = df["Product Type"].apply(lambda x: partial_score(x, query))
    elif method == "token":
        df["Score"] = df["Product Type"].apply(lambda x: token_score(x, query))
    else:
        df["Score"] = df["Product Type"].apply(lambda x: combined_score(x, query))

    top_matches = df.nlargest(n, "Score")[["Product Type", "Product Code", "Score"]]
    return top_matches.values.tolist()

def get_category_tree_by_name(product_name, n=10, method="combined"):
    def partial_score(category, query):
        return fuzz.partial_ratio(category.lower(), query)

    def token_score(category, query):
        return fuzz.token_set_ratio(category.lower(), query)

    def combined_score(category, query):
        p = partial_score(category, query)
        t = token_score(category, query)
        return 0.5 * p + 0.5 * t

    if method == "partial":
        score_func = partial_score
    elif method == "token":
        score_func = token_score
    else:
        score_func = combined_score

    category_df["Score"] = category_df["Category Tree"].apply(lambda x: score_func(x, product_name))
    category_df["Exact Match"] = category_df["Category Tree"].str.contains(product_name, case=False, na=False)
    priority_matches = category_df[category_df["Exact Match"]]

    if not priority_matches.empty:
        top_matches = priority_matches.nlargest(n, "Score")[["Category Tree", "Code", "Score"]]
    else:
        filtered_matches = category_df[category_df["Score"] >= 50]
        top_matches = filtered_matches.nlargest(n, "Score")[["Category Tree", "Code", "Score"]]

    return top_matches.values.tolist()

def get_item_specs(category_code):
    """
    Searches for the given category_code in the 'Category' column of item_specs.xlsx
    and retrieves matching rows from 'Display Name of Field', 'Requirement Level', 'Data Type', 'Description',
    and 'Allowed Value Names'.
    """
    # Load the main sheet (Custom Template File)
    custom_template_df = pd.read_excel(item_specs_file, sheet_name="Custom Template File", usecols=[
        "Display Name of Field", "Category", "Requirement Level", "Data Type", "Description", "Allowed Values"
    ])
    allowed_values_df = pd.read_excel(item_specs_file, sheet_name="Allowed Values", usecols=[
        "Allowed Value Group ID", "Allowed Value Name (optional)"
    ])

    category_code = category_code.strip()
    custom_template_df.columns = custom_template_df.columns.str.strip()
    allowed_values_df.columns = allowed_values_df.columns.str.strip()

    matching_rows = custom_template_df[custom_template_df["Category"].apply(
        lambda x: any(code.strip() == category_code for code in str(x).split("|^|"))
    )]

    results = []
    for _, row in matching_rows.iterrows():
        description = row["Description"]
        allowed_values = row["Allowed Values"]
        allowed_value_names = []

        if pd.notna(allowed_values):
            try:
                keyword = allowed_values.split("for")[1].split("Allowed")[0].strip()
                allowed_value_names = allowed_values_df[
                    allowed_values_df["Allowed Value Group ID"].str.contains(keyword, na=False)
                ]["Allowed Value Name (optional)"].dropna().tolist()
            except IndexError:
                pass

        results.append([
            row["Display Name of Field"],
            row["Requirement Level"],
            row["Data Type"],
            description,
            allowed_value_names
        ])

    return results

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/search', methods=['POST'])
def search():
    query = request.form['query']
    num_results = int(request.form.get('num_results', 10))
    fuzzy_method = request.form.get('fuzzy_method', 'combined')

    results = find_closest_matches(query, df, n=num_results, method=fuzzy_method)
    return render_template('results.html', results=results)

@app.route('/category', methods=['POST'])
def category():
    selected_product_name = request.form['selected_name']
    num_category_results = int(request.form.get('num_category_results', 10))
    category_fuzzy_method = request.form.get('category_fuzzy_method', 'combined')

    category_matches = get_category_tree_by_name(
        product_name=selected_product_name,
        n=num_category_results,
        method=category_fuzzy_method
    )

    return render_template(
        'category.html',
        category_matches=category_matches,
        selected_name=selected_product_name,
        num_category_results=num_category_results,
        category_fuzzy_method=category_fuzzy_method
    )

@app.route('/item_specs', methods=['POST'])
def item_specs():
    selected_category_code = request.form['selected_category_code']
    specs = get_item_specs(selected_category_code)
    return render_template('item_specs.html', specs=specs, category_code=selected_category_code)

if __name__ == '__main__':
    def open_browser():
        time.sleep(1)
        webbrowser.open_new('http://127.0.0.1:5000/')

    threading.Thread(target=open_browser).start()
    app.run(debug=True)
