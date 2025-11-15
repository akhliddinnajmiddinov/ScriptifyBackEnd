def organize_result(product):
    orig_price = product.get("price", "N/A")
    difference = "N/A"
    try:
        orig_price = float(orig_price) if orig_price else 0
        amazon_price = product.get('total_amazon_price', 0)
        difference = orig_price - amazon_price
    except Exception as e:
        orig_price = "N/A"
        difference = "N/A"

    product["difference"] = round(difference, 2)